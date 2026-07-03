"""JSON Schema codec: ``to_json_schema`` and ``from_json_schema``.

``to_json_schema`` renders a schema as a JSON Schema dictionary. Anything it does
not recognize becomes an open schema (``{}``) rather than an error.
``from_json_schema`` is the inverse: it builds a ``Schema`` from a JSON Schema
dictionary, for the constructs that map cleanly. ``from_openapi`` is the same
decoder with the OpenAPI 3.0 extras (the ``nullable`` keyword).

The decoder resolves ``$ref`` against ``$defs``/``definitions`` (JSON pointers),
memoizing each target so a reference that cycles back into a node still being
built ties the knot on that node, turning a recursive schema into a recursive
validator instead of looping.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

from probatio.codecs._regex_safety import is_catastrophic
from probatio.codecs._shared import FORMAT_BY_TYPE, STRING_TYPES
from probatio.error import ContainsInvalid, Invalid, SchemaError
from probatio.markers import (
    Alias,
    Exclusive,
    Forbidden,
    Inclusive,
    Marker,
    Optional,
    Remove,
    Required,
    Secret,
    Self,
    Undefined,
    resolve_key,
)
from probatio.schema import ALLOW_EXTRA, REMOVE_EXTRA, Schema, recursion_guard
from probatio.validators import (
    UUID,
    All,
    AsDate,
    AsDatetime,
    AsTime,
    Base64,
    Boolean,
    Capitalize,
    Coerce,
    Contains,
    Date,
    Datetime,
    Email,
    Equal,
    ExactSequence,
    FqdnUrl,
    FromEpoch,
    FromPercentage,
    Hostname,
    In,
    IPv4Address,
    IPv6Address,
    Length,
    Literal,
    Lower,
    Match,
    Maybe,
    MultipleOf,
    NotIn,
    Percentage,
    Port,
    Range,
    SomeOf,
    Strip,
    Time,
    Title,
    Unique,
    Upper,
    Url,
)
from probatio.validators import Any as AnyValidator

_PORT_MIN = 1
_PORT_MAX = 65535
_PERCENT_MIN = 0
_PERCENT_MAX = 100

_PRIMITIVE_TYPES: dict[type, str] = {
    bool: "boolean",
    int: "integer",
    float: "number",
    str: "string",
    type(None): "null",
}
_STRING_FUNCS = frozenset({Lower, Upper, Capitalize, Title, Strip})

# ``Boolean`` is a ``message`` factory, so each ``Boolean()`` is a fresh wrapper.
# They all share ``__wrapped__`` (the undecorated function), which is the stable
# identity to match against. ``functools.wraps`` sets ``__wrapped__`` at runtime,
# where the factory's call type does not advertise it, so read it via ``getattr``
# (no default: ``Boolean`` always carries it, and a None fallback could collide with
# a node that has no ``__wrapped__`` at the identity check below).
_BOOLEAN_FUNC = getattr(Boolean, "__wrapped__")  # noqa: B009

# The deepest a decoded JSON Schema may nest. Generous for any real schema (which
# rarely nests past a handful of levels), but low enough that even the most
# stack-hungry decode path (a typeless ``contains`` chain, which spends several
# frames per level) stays well under Python's recursion limit rather than leaking
# a RecursionError before this guard fires.
_MAX_SCHEMA_DEPTH = 100


def to_json_schema(schema: Any) -> dict[str, Any]:
    """Convert a schema (or ``Schema``) into a JSON Schema dictionary.

    A raw schema that references itself (a dict holding itself as a value, rather
    than the supported ``Self`` marker) has no finite rendering, so the runaway
    recursion is caught and reported as a clean ``SchemaError`` instead of a bare
    ``RecursionError``.
    """
    try:
        return _convert(schema, required_default=False, allow_extra=False)
    except RecursionError as exc:
        message = (
            "schema is too deeply nested or references itself; use the Self "
            "marker for a recursive schema"
        )
        raise SchemaError(message) from exc


def _convert(node: Any, *, required_default: bool, allow_extra: bool) -> dict[str, Any]:
    """Dispatch a schema node to the right JSON Schema renderer."""
    if isinstance(node, Schema):
        # ``REMOVE_EXTRA`` accepts extra keys on input (it strips them from the
        # output), so for input-side fidelity it renders open like ``ALLOW_EXTRA``,
        # not closed like the strict default.
        return _convert(
            node.schema,
            required_default=node.required,
            allow_extra=node.extra in (ALLOW_EXTRA, REMOVE_EXTRA),
        )

    if isinstance(node, dict):
        return _convert_mapping(
            node,
            required_default=required_default,
            allow_extra=allow_extra,
        )

    if isinstance(node, list | tuple | set | frozenset):
        return _convert_sequence(
            node, required_default=required_default, allow_extra=allow_extra
        )

    return _convert_leaf(node)


def _child(node: Any) -> dict[str, Any]:
    """Convert a validator-internal node with default (non-required, closed) settings.

    Used where the validation engine does *not* inherit the enclosing schema's
    required/extra policy: combinator branches, ``Maybe``, ``Contains``, and
    ``ExactSequence`` compile their contents under their own policy. Structural
    nesting (a dict value, a list element) does inherit, and threads the policy
    through ``_convert`` instead.
    """
    return _convert(node, required_default=False, allow_extra=False)


@dataclass
class _ExclusiveGroup:
    """The members of an ``Exclusive`` group and how an empty group is judged."""

    members: list[str] = field(default_factory=list)
    required: bool = False
    has_default: bool = False


class _Groups:
    """Accumulates the group-marker memberships found while walking a mapping."""

    def __init__(self) -> None:
        """Start with no groups recorded."""
        self.alias_required: list[list[str]] = []
        self.inclusive: dict[str, list[str]] = {}
        self.exclusive: dict[str, _ExclusiveGroup] = {}

    def add_alias(self, marker: Alias) -> None:
        """Record a required ``Alias`` (one of its names must be present).

        A ``default`` fills the empty case, so a required Alias carrying one does
        not actually demand a name (the same rule as ``Required`` with a default
        and a required-with-default ``Exclusive`` group); it adds no constraint.
        """
        if marker.required and isinstance(marker.default, Undefined):
            self.alias_required.append(list(marker.input_names))

    def add_inclusive(self, marker: Inclusive, name: str) -> None:
        """Record an ``Inclusive`` member (all-or-none within its group)."""
        self.inclusive.setdefault(marker.group_of_inclusion, []).append(name)

    def add_exclusive(self, marker: Exclusive, name: str) -> None:
        """Record an ``Exclusive`` member (at most one present within its group)."""
        group = self.exclusive.setdefault(marker.group_of_exclusion, _ExclusiveGroup())
        group.members.append(name)
        group.required = group.required or marker.group_required
        group.has_default = group.has_default or not isinstance(
            marker.default, Undefined
        )

    def constraints(self) -> list[dict[str, Any]]:
        """Build the object-level JSON Schema constraints for every recorded group."""
        constraints: list[dict[str, Any]] = [
            # At least one of the alias names must be present.
            {"anyOf": [{"required": [name]} for name in names]}
            for names in self.alias_required
        ]
        constraints += [
            _inclusive_constraint(members)
            for members in self.inclusive.values()
            if len(members) > 1
        ]
        constraints += [
            _exclusive_constraint(group) for group in self.exclusive.values()
        ]
        return [constraint for constraint in constraints if constraint]


def _inclusive_constraint(members: list[str]) -> dict[str, Any]:
    """Render an ``Inclusive`` group as all-or-none: any member pulls in every other."""
    return {
        "dependentRequired": {
            member: [other for other in members if other != member]
            for member in members
        },
    }


def _exclusive_constraint(group: _ExclusiveGroup) -> dict[str, Any]:
    """Render one ``Exclusive`` group as an at-most-one (or exactly-one) constraint.

    A required group with no default demands exactly one member (``oneOf`` over
    the per-member ``required``). Otherwise the group allows at most one: a
    default fills the empty group, so the empty object stays valid. At most one
    is "not any two present", the negation of every pair being present together.
    """
    members = group.members
    if group.required and not group.has_default:
        return {"oneOf": [{"required": [member]} for member in members]}
    pairs = [
        [members[i], members[j]]
        for i in range(len(members))
        for j in range(i + 1, len(members))
    ]
    return {"not": {"anyOf": [{"required": pair} for pair in pairs]}} if pairs else {}


def _convert_mapping(
    node: dict[Any, Any],
    *,
    required_default: bool,
    allow_extra: bool,
) -> dict[str, Any]:
    """Render a mapping schema as a JSON Schema object.

    Nested dict values and variable-key values inherit the enclosing schema's
    required/extra policy, mirroring the validation engine, so a nested object
    keeps its own ``required`` list and open/closed shape. The group markers
    (``Alias``, ``Inclusive``, ``Exclusive``) add object-level constraints,
    combined under ``allOf``.
    """
    properties: dict[Any, Any] = {}
    required: list[Any] = []
    groups = _Groups()
    # Multiple variable keys ({str: int, int: str}) merge into one
    # ``additionalProperties`` schema; ``allow_extra`` seeds the default.
    variable_values: list[dict[str, Any]] = []
    # A ``Forbidden`` over a type/callable key (``Forbidden(str)`` forbids every
    # string key, so every JSON key) closes the object regardless of the extra
    # policy.
    forbid_extra = False
    for key, value in node.items():
        # Resolve the marker chain first, so a nested marker (``Secret(Remove(...))``)
        # is classified by the marker it actually carries, not just the outer wrapper.
        facets = resolve_key(key)
        marker = facets.marker
        name = facets.key
        value_schema = _convert(
            value, required_default=required_default, allow_extra=allow_extra
        )

        if isinstance(marker, Forbidden):
            # A literal forbidden key is a rejected property; a type/callable one
            # forbids a class of keys, which for JSON (string keys) closes the
            # object. Checked before the variable-key branch so ``Forbidden(str)``
            # does not fall through into an accepting ``additionalProperties``.
            if isinstance(name, str):
                properties[name] = False
            else:
                forbid_extra = True
            continue

        if isinstance(name, type) or callable(name):
            # A type/callable key is a variable key. ``Remove`` still validates a
            # present value before dropping it, so its value schema still applies
            # to the keys it matches, the same as a plain variable key.
            variable_values.append(value_schema)
            continue

        if not isinstance(name, str):
            # A non-string literal key never matches a JSON object key (those are
            # strings), so emitting ``properties[name]`` would render an entry
            # ``json.dumps`` coerces to a string the schema does not actually
            # match. Skip it deliberately rather than emit a misleading property.
            continue

        if isinstance(marker, Remove):
            # A removed key is stripped from the output, but a present value is
            # validated first, so input carrying it is valid: emit it as an
            # optional property (never rejected as an extra key).
            properties[name] = value_schema
            continue

        decorated = _decorate_property(
            value_schema,
            marker,
            secret=facets.secret,
            description=facets.description,
        )
        _emit_named_key(
            name,
            decorated,
            marker,
            properties,
            required,
            groups,
            required_default=required_default,
        )

    additional: Any = (
        False
        if forbid_extra
        else _additional_properties(variable_values, allow_extra=allow_extra)
    )
    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional,
    }
    if required:
        result["required"] = required
    constraints = groups.constraints()
    if constraints:
        result["allOf"] = constraints

    return result


def _emit_named_key(  # noqa: PLR0913
    name: str,
    decorated: dict[str, Any],
    marker: Marker | None,
    properties: dict[Any, Any],
    required: list[Any],
    groups: _Groups,
    *,
    required_default: bool,
) -> None:
    """Place a decorated property and record any group membership it carries."""
    if isinstance(marker, Alias):
        # An aliased key is accepted under any of its names, so each renders as a
        # property; the "one name must be present" rule (for a required Alias)
        # becomes an object-level constraint.
        for alias_name in marker.input_names:
            properties[alias_name] = decorated
        groups.add_alias(marker)
        return

    properties[name] = decorated
    if isinstance(marker, Inclusive):
        groups.add_inclusive(marker, name)
    elif isinstance(marker, Exclusive):
        groups.add_exclusive(marker, name)
    # A ``Required`` marker carrying a default does not demand presence (the
    # default fills the key in), so it stays out of ``required``; the ``default``
    # keyword already conveys it.
    elif _is_required(marker, required_default=required_default):
        required.append(name)


def _is_required(marker: Marker | None, *, required_default: bool) -> bool:
    """Whether a mapping key must be present in the emitted schema.

    A ``Required`` marker demands presence unless it carries a default (which
    fills the key in, so the input may omit it). A bare key follows the schema's
    ``required`` default, and an ``Optional`` never demands presence.
    """
    if isinstance(marker, Required):
        return isinstance(marker.default, Undefined)
    if isinstance(marker, Optional):
        return False
    return required_default


def _additional_properties(
    variable_values: list[dict[str, Any]],
    *,
    allow_extra: bool,
) -> Any:
    """Combine the variable-key value schemas into one ``additionalProperties``.

    No variable key falls back to the extra policy (open or closed). One renders
    as its value schema; several ({str: int, int: str}) merge into an ``anyOf``
    so no pair is silently dropped.
    """
    if not variable_values:
        return allow_extra
    if len(variable_values) == 1:
        return variable_values[0]
    return {"anyOf": variable_values}


def _decorate_property(
    prop: dict[str, Any],
    marker: Marker | None,
    *,
    secret: bool = False,
    description: Any = None,
) -> dict[str, Any]:
    """Attach a description, default, and secret flag to a rendered value schema."""
    if description is not None:
        prop = {**prop, "description": description}
    # ``Optional``, ``Required``, ``Alias``, ``Inclusive``, and ``Exclusive`` all
    # carry a ``default``; the others do not.
    factory = getattr(marker, "default", None)
    if factory is not None and not isinstance(factory, Undefined):
        # ``default`` is annotation-only, so a non-JSON default (a ``datetime``,
        # say) is omitted rather than emitted raw and crashing ``json.dumps``.
        default = _json_safe(factory())
        if default is not _UNREPRESENTABLE:
            prop = {**prop, "default": default}
    if secret:
        # ``writeOnly`` is JSON Schema's marker for a secret (a password field).
        prop = {**prop, "writeOnly": True}

    return prop


def _ordered(values: Any) -> list[Any]:
    """List a container's values, sorting a set so the emitted schema is stable.

    A list or tuple keeps the author's order. A set or frozenset has none, so its
    values are sorted by ``repr`` to keep ``to_json_schema`` output deterministic
    across runs (stable snapshots, no spurious schema diffs, no cache misses).
    """
    if isinstance(values, set | frozenset):
        return sorted(values, key=repr)
    return list(values)


def _convert_sequence(
    node: Any,
    *,
    required_default: bool = False,
    allow_extra: bool = False,
) -> dict[str, Any]:
    """Render a sequence/set schema as a JSON Schema array.

    A list or tuple element inherits the enclosing schema's required/extra
    policy, mirroring the validation engine (a set holds only hashable leaves,
    so its policy is moot). Combinator branches reach ``_convert_sequence``
    through ``_child`` with the strict default, matching the engine.
    """
    items = [
        _convert(element, required_default=required_default, allow_extra=allow_extra)
        for element in _ordered(node)
    ]

    result: dict[str, Any] = {"type": "array"}
    if len(items) == 1:
        result["items"] = items[0]
    elif items:
        result["items"] = {"anyOf": items}
    else:
        # An empty sequence schema (``Schema([])``) accepts only the empty list,
        # not any array, so forbid every element rather than leave it open.
        result["maxItems"] = 0

    return result


def _convert_leaf(node: Any) -> dict[str, Any]:
    """Render a leaf node: a type, a literal, or a validator."""
    if node is Self:
        # ``Self`` means "the whole enclosing schema", the recursive reference
        # the decoder already reads back from ``$ref: "#"``. ``#`` targets the
        # document root, which is the top-level schema being encoded (the common
        # recursive-schema case); a ``Self`` inside a separately nested ``Schema``
        # would resolve against its own root, which this cannot express.
        return {"$ref": "#"}

    json_format = getattr(node, "__probatio_json_format__", None)

    if json_format is not None:
        return {"type": "string", "format": json_format}

    if isinstance(node, type):
        return _convert_type(node)

    if node is None:
        return {"type": "null"}

    if isinstance(node, str | int | float | bool):
        return {"const": node}

    validator = _convert_validator(node)
    return validator if validator is not None else {}


def _convert_type(node: type) -> dict[str, Any]:
    """Render a Python type as a JSON Schema type."""
    name = _PRIMITIVE_TYPES.get(node)
    if name is not None:
        return {"type": name}

    if node is dict:
        return {"type": "object"}

    if node is list:
        return {"type": "array"}

    return {}


def _convert_validator(node: Any) -> dict[str, Any] | None:
    """Render a combinator, or delegate to the constraint validators."""
    if isinstance(node, Coerce):
        return _convert_type(node.type) if isinstance(node.type, type) else {}

    if isinstance(node, AnyValidator):
        return {"anyOf": [_child(validator) for validator in node.validators]}

    if isinstance(node, All):
        return _convert_all(node)

    return _convert_constraint(node)


def _convert_all(node: All) -> dict[str, Any]:
    """Merge an All's validators into one schema, or ``allOf`` when keys collide.

    Merging with ``dict.update`` is the common, compact case (``All(int, Range)``
    → one object). But when two validators emit the same keyword (``All(Any(...),
    Any(...))`` both emit ``anyOf``), a plain update drops the earlier one and
    widens the schema. Falling back to ``allOf`` keeps every facet, since a value
    must satisfy them all.
    """
    parts = [_child(validator) for validator in node.validators]
    merged: dict[str, Any] = {}
    collided = False
    for part in parts:
        if merged.keys() & part.keys():
            collided = True
            break
        merged.update(part)

    if collided:
        return {"allOf": [part for part in parts if part]}
    return _retarget_length(merged)


# JSON Schema spells "length" three ways depending on the type: minLength for a
# string, minItems for an array, minProperties for an object. A Length validator
# always renders the string form, so an All that pins an array or object length
# has to move the bounds onto the matching keyword.
_LENGTH_KEYS_BY_TYPE: dict[str, tuple[str, str]] = {
    "array": ("minItems", "maxItems"),
    "object": ("minProperties", "maxProperties"),
}


def _retarget_length(merged: dict[str, Any]) -> dict[str, Any]:
    """Move a merged Length's string-length keys onto the array/object keyword."""
    keys = _LENGTH_KEYS_BY_TYPE.get(merged.get("type", ""))
    if keys is None:
        return merged

    min_key, max_key = keys
    if "minLength" in merged:
        merged[min_key] = merged.pop("minLength")
    if "maxLength" in merged:
        merged[max_key] = merged.pop("maxLength")

    return merged


_UNREPRESENTABLE = object()


def _json_safe(value: Any) -> Any:
    """Convert a value to a JSON-representable form, or ``_UNREPRESENTABLE``.

    ``to_json_schema`` must emit a document ``json.dumps`` accepts (an emitted
    ``const``, ``enum``, ``default``, or numeric bound holding a raw ``datetime``,
    ``Decimal``, ``Enum`` member, or ``bytes`` would otherwise crash the caller).
    Datetimes render ISO, a ``Decimal`` renders a float, an ``Enum`` member
    renders its value, and a tuple or set renders a list (JSON has no tuple, and
    a value on the wire arrives as a list anyway). Anything with no clean JSON
    form is reported unrepresentable so the caller can omit it.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, list | tuple | set | frozenset):
        converted = [_json_safe(item) for item in _ordered(value)]
        return _UNREPRESENTABLE if _UNREPRESENTABLE in converted else converted
    if isinstance(value, dict):
        items = {key: _json_safe(item) for key, item in value.items()}
        if (
            any(not isinstance(key, str) for key in items)
            or _UNREPRESENTABLE in items.values()
        ):
            return _UNREPRESENTABLE
        return items
    return _UNREPRESENTABLE


def _enum(container: Any) -> dict[str, Any]:
    """Render a membership container as an ``enum``, or open when unrepresentable.

    A member with no JSON form (a ``datetime``, an ``Enum``, a ``bytes``) would
    make the emitted enum non-serializable; dropping the constraint to an open
    schema keeps the output valid rather than crashing, since a narrower emission
    is not available.
    """
    values = _json_safe(list(_ordered(container)))
    return {} if values is _UNREPRESENTABLE else {"enum": values}


def _const(value: Any) -> dict[str, Any]:
    """Render an equality target as a ``const``, or open when unrepresentable."""
    converted = _json_safe(value)
    return {} if converted is _UNREPRESENTABLE else {"const": converted}


def _convert_equality(node: Any) -> dict[str, Any] | None:
    """Render the equality/membership validators as enum/const/not, or None."""
    if isinstance(node, In):
        return _enum(node.container)

    if isinstance(node, NotIn):
        enum = _enum(node.container)
        return {"not": enum} if enum else {}

    if isinstance(node, Equal):
        return _const(node.target)

    if isinstance(node, Literal):
        return _const(node.lit)

    # The decoder's JSON-strict enum/const (numbers and booleans kept distinct)
    # re-emit their keyword, so a decoded schema round-trips.
    if isinstance(node, _JsonEnum):
        return _enum(node.values)

    if isinstance(node, _JsonConst):
        return _const(node.value)

    return None


def _convert_constraint(node: Any) -> dict[str, Any] | None:
    """Render a constraint validator, or delegate to the named validators."""
    equality = _convert_equality(node)
    if equality is not None:
        return equality

    if isinstance(node, Range):
        return _convert_range(node)

    if isinstance(node, Length):
        return _convert_length(node)

    if isinstance(node, Match):
        return _convert_match(node)

    if isinstance(node, Maybe):
        return {"anyOf": [{"type": "null"}, _child(node.validator)]}

    temporal = _convert_temporal_node(node)
    if temporal is not None:
        return temporal

    # A Unix timestamp on the wire is a number (``FromEpoch`` takes an int or a
    # fractional-second float); the datetime is internal.
    if isinstance(node, FromEpoch):
        return {"type": "number"}

    if isinstance(node, Unique):
        return {"uniqueItems": True}

    # The decoder's JSON-value uniqueness check re-emits its keyword, so a
    # decoded schema round-trips.
    if isinstance(node, _JsonUnique):
        return {"uniqueItems": True}

    if isinstance(node, Contains):
        return {"contains": _child(node.item)}

    if isinstance(node, ExactSequence):
        return _convert_exact_sequence(node)

    typed = _convert_typed(node)
    if typed is not None:
        return typed

    return _convert_named(node)


def _convert_typed(node: Any) -> dict[str, Any] | None:
    """Render the network, identifier, and numeric-bound validators."""
    for validator_type, json_format in FORMAT_BY_TYPE.items():
        if isinstance(node, validator_type):
            return {"type": "string", "format": json_format}

    if isinstance(node, STRING_TYPES):
        return {"type": "string"}

    if isinstance(node, Port):
        return {"type": "integer", "minimum": _PORT_MIN, "maximum": _PORT_MAX}

    if isinstance(node, Percentage | FromPercentage):
        return {"type": "number", "minimum": _PERCENT_MIN, "maximum": _PERCENT_MAX}

    if isinstance(node, MultipleOf):
        return {"multipleOf": node.factor}

    if isinstance(node, Base64):
        return {"type": "string", "contentEncoding": "base64"}

    # The decoder's JSON-strict numeric types re-emit their keyword, so a
    # decoded schema round-trips.
    if isinstance(node, _JsonNumberType):
        return {"type": "integer" if node.integer else "number"}

    return None


def _convert_named(node: Any) -> dict[str, Any] | None:
    """Render the identity-comparable string and boolean validators."""
    if getattr(node, "__wrapped__", None) is _BOOLEAN_FUNC:
        return {"type": "boolean"}

    if node is Email:
        return {"type": "string", "format": "email"}

    if node in (Url, FqdnUrl):
        return {"type": "string", "format": "uri"}

    if node in _STRING_FUNCS:
        return {"type": "string"}

    return None


# Regex syntax that Python's ``re`` accepts but JSON Schema's ECMA-262 dialect does
# not. A ``pattern`` using one of these would be rejected, or silently behave
# differently, in an external (non-Python) validator. The detection is conservative:
# a false negative (a Python-only construct not listed) emits an invalid pattern, so
# err toward listing; a false positive only drops a valid pattern, the safe direction.
_PYTHON_ONLY_REGEX = re.compile(
    r"\(\?P[<=]"  # named group (?P<n>...) or backreference (?P=n)
    r"|\(\?\#"  # inline comment (?#...)
    r"|\(\?\("  # conditional (?(id)yes|no)
    r"|\(\?>"  # atomic group (?>...)
    r"|\(\?[aiLmsux]+[:)]"  # inline flags (?i) or scoped (?im:...)
    r"|\(\?[aiLmsux]*-[aiLmsux]+:"  # negated/mixed scoped flags (?-i:...)
    r"|(?<!\\)[*+?}]\+"  # possessive quantifier (*+ ++ ?+ }+), not an escape
    r"|\\[AZ]",  # \A / \Z anchors, which ECMA-262 spells ^ / $
)


def _convert_match(node: Match) -> dict[str, Any]:
    """Render a Match as a string, with a JSON Schema ``pattern`` when ECMA-safe.

    JSON Schema patterns are ECMA-262 regular expressions, while ``Match`` holds a
    Python ``re`` pattern. A pattern that uses Python-only syntax is dropped, leaving
    a plain ``{"type": "string"}``, so the emitted schema stays valid for an external
    validator rather than carrying a pattern that validator would reject.

    ``Match`` validates with ``re.match`` (anchored at the start), while a JSON
    Schema ``pattern`` is an unanchored ``re.search``. Wrapping an unanchored
    source as ``^(?:...)`` preserves the start anchoring, so the emitted schema
    does not accept a value with a matching suffix that ``Match`` rejects.

    A ``bytes`` pattern has no JSON Schema (JSON strings are text), so it renders
    as a plain string rather than crashing on the ``str``/``bytes`` mismatch.
    """
    source = node.pattern.pattern
    if isinstance(source, bytes) or _PYTHON_ONLY_REGEX.search(source):
        return {"type": "string"}
    # A source already anchored at the start needs no wrapper; otherwise wrap it
    # (grouped, so a top-level alternation stays under the anchor).
    anchored = source if source.startswith("^") else f"^(?:{source})"
    return {"type": "string", "pattern": anchored}


def _convert_range(node: Range) -> dict[str, Any]:
    """Render a Range as JSON Schema minimum/maximum bounds.

    A non-numeric bound (a ``datetime``, say) has no JSON Schema numeric keyword
    and would make the output non-serializable, so such a bound is omitted rather
    than emitted raw.
    """
    result: dict[str, Any] = {}
    minimum = _json_safe(node.min)
    maximum = _json_safe(node.max)
    if node.min is not None and isinstance(minimum, int | float):
        result["minimum" if node.min_included else "exclusiveMinimum"] = minimum
    if node.max is not None and isinstance(maximum, int | float):
        result["maximum" if node.max_included else "exclusiveMaximum"] = maximum

    return result


def _convert_length(node: Length) -> dict[str, Any]:
    """Render a Length as JSON Schema string-length bounds."""
    result: dict[str, Any] = {}
    if node.min is not None:
        result["minLength"] = node.min
    if node.max is not None:
        result["maxLength"] = node.max

    return result


def _convert_temporal_node(node: Any) -> dict[str, Any] | None:
    """Render any date/time validator (string or As* parser), or None if not one.

    Date and Time subclass Datetime, so they are matched first. The As* parsers
    are not subclasses, but describe the same string on the wire, so they map to
    the same ``format``.
    """
    if isinstance(node, Date | AsDate):
        return _convert_temporal(node, "date")

    if isinstance(node, Time | AsTime):
        return _convert_temporal(node, "time")

    if isinstance(node, Datetime | AsDatetime):
        return _convert_temporal(node, "date-time")

    return None


def _convert_temporal(node: Any, json_format: str) -> dict[str, Any]:
    """Render a Date/Datetime (or its As* parser) as a string, format when ISO.

    The ``format`` keyword only carries meaning for the ISO form; a custom
    ``strptime`` pattern has no JSON Schema equivalent, so the result is a plain
    string in that case. This makes ``Datetime()`` round-trip with the decoder,
    which reads ``format: date-time`` back into a ``Datetime``. The string
    validators mark ISO with their ``DEFAULT_FORMAT``; the ``As*`` parsers use
    ``format=None``, so comparing against ``DEFAULT_FORMAT`` (absent, so ``None``)
    covers both.
    """
    result: dict[str, Any] = {"type": "string"}
    if node.format == getattr(node, "DEFAULT_FORMAT", None):
        result["format"] = json_format
    return result


def _convert_exact_sequence(node: ExactSequence) -> dict[str, Any]:
    """Render an ExactSequence as a fixed-length positional (``prefixItems``) array.

    Each position becomes one entry in ``prefixItems``; ``items: false`` forbids
    extra elements and the matching ``minItems``/``maxItems`` pin the length, so
    the array must have exactly the listed positions.
    """
    prefix = [_child(validator) for validator in node.validators]
    return {
        "type": "array",
        "prefixItems": prefix,
        "items": False,
        "minItems": len(prefix),
        "maxItems": len(prefix),
    }


def _iso_parsable(value: str) -> str:
    """Normalize an RFC 3339 string for ``fromisoformat``.

    RFC 3339 allows a lowercase ``z`` suffix; ``fromisoformat`` accepts only the
    uppercase form, so the suffix is normalized before parsing.
    """
    return value[:-1] + "Z" if value.endswith("z") else value


class _JsonDateTime:
    """Decode of ``format: date-time``: an RFC 3339 timestamp.

    ``Datetime()`` validates one ``strptime`` format (fractional seconds and a
    literal ``Z`` both mandatory), which rejects most valid RFC 3339 timestamps:
    ``2024-01-01T00:00:00Z``, any numeric UTC offset. The decoded validator
    parses with ``fromisoformat`` instead, which accepts the RFC 3339 forms
    (``Z`` or an offset, any fraction length, lowercase markers). A timestamp
    without an offset is accepted too: the spec requires one, but probatio's own
    temporal validators treat naive timestamps as valid, and rejecting them
    would surprise more than it protects.
    """

    __probatio_json_format__ = "date-time"

    def __repr__(self) -> str:
        """Render readably for error paths."""
        return "JsonDateTime()"

    def __call__(self, value: Any) -> Any:
        """Return the value if it is an RFC 3339 timestamp, else raise Invalid."""
        # ``fromisoformat`` also accepts a bare date, which ``date-time``
        # forbids, so the date/time separator at position 10 is checked first.
        ok = isinstance(value, str) and len(value) > 10 and value[10] in "Tt"
        if ok:
            try:
                datetime.datetime.fromisoformat(_iso_parsable(value))
            except ValueError:
                ok = False
        if not ok:
            raise Invalid(translation_key="expected_iso_datetime")
        return value


class _JsonTime:
    """Decode of ``format: time``: an RFC 3339 time of day.

    ``Time()`` validates ``%H:%M:%S`` only, rejecting fractional seconds and UTC
    offsets that are valid per the spec. The decoded validator parses with
    ``fromisoformat`` and requires at least ``HH:MM:SS`` (the spec's
    partial-time; ``fromisoformat`` alone would accept ``14:30``). As with
    ``date-time``, the offset stays optional.
    """

    __probatio_json_format__ = "time"

    def __repr__(self) -> str:
        """Render readably for error paths."""
        return "JsonTime()"

    def __call__(self, value: Any) -> Any:
        """Return the value if it is an RFC 3339 time, else raise Invalid."""
        ok = isinstance(value, str) and len(value) >= 8
        if ok:
            try:
                datetime.time.fromisoformat(_iso_parsable(value))
            except ValueError:
                ok = False
        if not ok:
            raise Invalid(translation_key="expected_iso_time")
        return value


# JSON Schema "format" values that map to a built probatio string validator.
# Email/Url are factories (like voluptuous), so they are called once here.
_FROM_FORMATS: dict[str, Any] = {
    "email": Email(),
    "uri": Url(),
    "url": Url(),
    "date-time": _JsonDateTime(),
    "date": Date(),
    "time": _JsonTime(),
    "ipv4": IPv4Address(),
    "ipv6": IPv6Address(),
    "uuid": UUID(),
    "hostname": Hostname(),
}
# JSON Schema scalar types that map to a fixed probatio fragment.
_SIMPLE_TYPES: dict[str, Any] = {"boolean": bool, "null": None}


class _JsonNumberType:
    """Decode of ``type: integer``/``number`` under the JSON data model.

    Python's ``bool`` subclasses ``int``, so a plain type check accepts ``True``
    as an integer and rejects ``1.0``, both against the spec: JSON has no
    boolean-as-number, and Draft 2020-12 defines ``integer`` as any number with
    a zero fractional part.
    """

    def __init__(self, *, integer: bool) -> None:
        """Remember whether the fractional part must be zero (read as ``.integer``)."""
        self.integer = integer

    def __repr__(self) -> str:
        """Render readably for error paths."""
        return "JsonInteger()" if self.integer else "JsonNumber()"

    def __call__(self, value: Any) -> Any:
        """Return the value if it is a JSON number (an integer when required)."""
        bad = isinstance(value, bool) or not isinstance(value, int | float)
        if not bad and self.integer and isinstance(value, float):
            bad = not value.is_integer()
        if bad:
            raise Invalid(
                translation_key="expected_type",
                placeholders={"expected": "integer" if self.integer else "number"},
            )
        return value


_JSON_INTEGER = _JsonNumberType(integer=True)
_JSON_NUMBER = _JsonNumberType(integer=False)


class _DeferredRef:
    """A placeholder for a ``$ref``, resolved once its target schema is built.

    Returned for a recursive reference (a ``$ref`` met while its own target is
    still being built) so the recursion binds to the *referenced node*, not the
    document root. Its ``schema`` is always set before any validation runs.
    """

    # Validating a ``$ref`` re-enters the same schema, so the code generator must
    # not compile a mapping holding one: a deep failure would make every level bail
    # to the interpreted engine and re-validate its whole subtree, an exponential
    # cascade. This marks the value so ``probatio._codegen`` leaves such a mapping
    # interpreted, the same way ``Self`` recursion is left interpreted.
    _probatio_recursive_ref = True

    def __init__(self) -> None:
        """Start unresolved; ``schema`` is filled in when the target finishes."""
        self.schema: Schema | None = None

    def __call__(self, data: Any) -> Any:
        """Validate ``data`` against the resolved target schema, depth-guarded.

        A recursive ``$ref`` (a linked list or tree in the schema) recurses here,
        so it shares the same depth guard as ``Self``: deep or cyclic attacker
        data raises a clean ``Invalid`` instead of a ``RecursionError``.
        """
        if self.schema is None:  # pragma: no cover - set before validation
            message = "unresolved schema reference"
            raise RuntimeError(message)

        with recursion_guard():
            return self.schema(data)


@dataclass
class _Decode:
    """The context threaded through a decode: the root, mode, and ref cache."""

    root: dict[str, Any]
    openapi: bool
    refs: dict[str, _DeferredRef] = field(default_factory=dict)
    # Current nesting depth, guarded so a deeply nested untrusted schema raises a
    # clean SchemaError instead of exhausting the Python stack with RecursionError.
    depth: int = 0


def from_json_schema(schema: dict[str, Any]) -> Schema:
    """Build a ``Schema`` from a JSON Schema dictionary.

    This is the inverse of ``to_json_schema`` for the constructs that map cleanly:
    objects (with ``properties``, ``required``, ``additionalProperties``), arrays
    (``items``, ``minItems``/``maxItems``), the primitive types, ``enum``,
    ``const``, ``anyOf``, ``allOf``, ``oneOf`` (with its exact "one branch only"
    semantics), a ``type`` array like ``["string", "null"]``, and the string and
    number constraints. ``$ref`` is resolved against ``$defs``/``definitions``. A
    permissive keyword probatio does not model is ignored, so a partial schema still
    yields a usable validator; a *restrictive* one it cannot honor is refused, since
    silently dropping a constraint would widen an untrusted schema (see
    ``_UNSUPPORTED_KEYWORDS``).

    The schema may come from an untrusted source, so two safeguards apply: a
    ``pattern`` that backtracks catastrophically (a nested unbounded quantifier)
    is refused with ``SchemaError`` rather than compiled, and a document nested
    past ``_MAX_SCHEMA_DEPTH`` levels is refused rather than overflowing the
    stack. Both are conservative; an unusual but legitimate schema can trip them.
    """
    return _decode(schema, openapi=False)


def from_openapi(schema: dict[str, Any]) -> Schema:
    """Build a ``Schema`` from an OpenAPI Schema object.

    The same decoder as ``from_json_schema`` plus the OpenAPI 3.0 ``nullable``
    keyword (a nullable value also accepts ``None``). The inverse of ``to_openapi``
    for the constructs that map cleanly.
    """
    return _decode(schema, openapi=True)


def _decode(schema: dict[str, Any], *, openapi: bool) -> Schema:
    """Run a decode from the root schema, wrapping the result in a Schema.

    The schema is untrusted, and exhaustively type-checking every field of an
    arbitrary document is impractical, so the decode fails closed: a structural
    mismatch a specific check did not already catch (a bool where a list was
    expected, an unhashable ``format``, and the like) is converted to a clean
    ``SchemaError`` rather than leaking the raw ``TypeError``/``AttributeError``.
    A ``SchemaError`` a specific check raised keeps its own message.
    """
    try:
        node = _from_node(schema, _Decode(root=schema, openapi=openapi))
    except SchemaError:
        raise
    except (TypeError, AttributeError, KeyError, IndexError, ValueError) as exc:
        message = f"could not decode the schema; it is malformed: {exc}"
        raise SchemaError(message) from exc
    return node if isinstance(node, Schema) else Schema(node)


def _from_node(node: Any, ctx: _Decode) -> Any:
    """Convert one JSON Schema node into a probatio schema fragment, depth-guarded."""
    ctx.depth += 1
    try:
        if ctx.depth > _MAX_SCHEMA_DEPTH:
            message = (
                f"JSON Schema nests deeper than {_MAX_SCHEMA_DEPTH} levels; "
                "refusing to decode it"
            )
            raise SchemaError(message)
        return _build_node(node, ctx)
    finally:
        ctx.depth -= 1


def _build_node(node: Any, ctx: _Decode) -> Any:
    """Convert one JSON Schema node into a probatio schema fragment.

    A node is normally an object, but JSON Schema also allows a boolean schema:
    ``true`` accepts any value, ``false`` accepts none. The ``writeOnly`` and
    (in OpenAPI mode) ``nullable`` keywords wrap whatever the node produces, so
    they apply uniformly, including to ``enum``, ``const``, ``anyOf``, ``allOf``,
    and ``$ref`` nodes.
    """
    if isinstance(node, bool):
        return object if node else In([])

    if not isinstance(node, dict):
        message = (
            f"JSON Schema node must be an object or boolean, got {type(node).__name__}"
        )
        raise SchemaError(message)

    _reject_unsupported(node)

    facets = _collect_facets(node, ctx)
    if not facets:
        result: Any = object
    elif len(facets) == 1:
        result = facets[0]
    else:
        result = All(*facets)

    if ctx.openapi and node.get("nullable") is True:
        result = Maybe(result)

    return result


def _collect_facets(node: dict[str, Any], ctx: _Decode) -> list[Any]:
    """Collect every facet of a node, to be ANDed together.

    JSON Schema keywords are conjunctive: a value must satisfy every facet
    present, including combinators, sibling types, and constraints. Dropping any
    of them would widen an untrusted schema.
    """
    facets: list[Any] = []
    if "$ref" in node:
        facets.append(_from_ref(node["$ref"], ctx))
    if "const" in node:
        facets.append(_from_const(node["const"]))
    elif "enum" in node:
        facets.append(_from_enum(node["enum"]))
    if "not" in node:
        facets.append(_Not(_from_node(node["not"], ctx)))
    if "allOf" in node:
        facets.append(_from_combinator(node["allOf"], "allOf", All, ctx))
    if "anyOf" in node:
        facets.append(_from_combinator(node["anyOf"], "anyOf", AnyValidator, ctx))
    if "oneOf" in node:
        facets.append(_from_oneof(node["oneOf"], ctx))

    typed = _typed_facet(node, ctx)
    if typed is not None:
        facets.append(typed)

    return facets


def _typed_facet(node: dict[str, Any], ctx: _Decode) -> Any:
    """Return the ``type``-based or standalone-constraint facet of a node, or None.

    None means a node carries neither a ``type`` nor a recognized constraint
    keyword, so a node that is only a combinator (an ``allOf`` with no sibling
    assertions) does not pick up a redundant accept-anything facet.
    """
    if "type" in node:
        return _from_typed(node, ctx)
    return _combine_constraints(node, ctx)


# Restrictive keywords probatio does not implement. Silently ignoring one would
# widen an untrusted schema (accept data the author meant to forbid), so the
# decoder fails closed and refuses the document instead.
_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "if",
        "propertyNames",
        "patternProperties",
        "dependentRequired",
        "dependentSchemas",
        "dependencies",
        # Draft 2019-09/2020-12 keywords probatio does not evaluate; ignoring one
        # would widen the schema (accept data the author forbade), so fail closed.
        "unevaluatedProperties",
        "unevaluatedItems",
        # Dynamic references are restrictive (they point at a constraint), so they
        # fail closed too. Their anchors are declarations, not constraints: with
        # every dynamic reference refused, a leftover anchor is inert, so anchors
        # are not refused.
        "$dynamicRef",
        "$recursiveRef",
    },
)


def _reject_unsupported(node: dict[str, Any]) -> None:
    """Refuse a node carrying a restrictive keyword probatio cannot honor."""
    unsupported = _UNSUPPORTED_KEYWORDS & node.keys()
    if unsupported:
        names = ", ".join(sorted(unsupported))
        message = (
            f"JSON Schema keyword(s) not supported; refusing to silently ignore a "
            f"constraint: {names}"
        )
        raise SchemaError(message)


def _json_equal(a: Any, b: Any) -> bool:
    """Equality under JSON's type model: a boolean is never equal to a number.

    Python's ``==`` conflates them (``1 == True``), so a decoded ``enum`` or
    ``const`` would accept booleans for numbers and the reverse, against the
    JSON data model. Numbers still compare across int/float (``1 == 1.0``),
    which matches the spec. Containers compare element-wise so a nested boolean
    stays distinct too.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    # The value side can be a hostile subclass whose __len__, __iter__,
    # __getitem__, or key equality raises, so the container walks are guarded
    # just like the plain equality: any failure is a mismatch, never a leak.
    try:
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(map(_json_equal, a, b))
        if isinstance(a, dict) and isinstance(b, dict):
            return a.keys() == b.keys() and all(
                _json_equal(item, b[key]) for key, item in a.items()
            )
        return bool(a == b)
    except Exception:  # noqa: BLE001 - the value's dunders are user code; never leak
        return False


def _needs_json_equality(value: Any) -> bool:
    """Whether Python ``==`` could conflate the value with a boolean or number.

    Only booleans and numbers (anywhere in the value) are ambiguous; strings,
    null, and containers of them compare identically under both models, so those
    keep the plain validators and their round-trip shape.
    """
    if isinstance(value, bool | int | float):
        return True
    if isinstance(value, list):
        return any(_needs_json_equality(item) for item in value)
    if isinstance(value, dict):
        return any(_needs_json_equality(item) for item in value.values())
    return False


class _JsonConst:
    """Decode of ``const`` holding a number or boolean: JSON-strict equality."""

    def __init__(self, value: Any) -> None:
        """Store the value the input must equal (read as ``.value``)."""
        self.value = value

    def __repr__(self) -> str:
        """Render readably for error paths."""
        return f"JsonConst({self.value!r})"

    def __call__(self, value: Any) -> Any:
        """Return the value if it JSON-equals the const, else raise Invalid."""
        if not _json_equal(value, self.value):
            raise Invalid(
                translation_key="value_not_equal",
                placeholders={"target": self.value},
            )
        return value


class _JsonEnum:
    """Decode of ``enum`` holding numbers or booleans: JSON-strict membership."""

    def __init__(self, values: list[Any]) -> None:
        """Store the allowed members (read as ``.values``)."""
        self.values = values

    def __repr__(self) -> str:
        """Render readably for error paths."""
        return f"JsonEnum({self.values!r})"

    def __call__(self, value: Any) -> Any:
        """Return the value if a member JSON-equals it, else raise Invalid."""
        if not any(_json_equal(value, member) for member in self.values):
            raise Invalid(
                translation_key="value_one_of",
                placeholders={"values": self.values},
            )
        return value


def _from_const(value: Any) -> Any:
    """Build a const equality check.

    A scalar is returned as a literal (a ``Schema`` validates a literal by
    equality). A list or dict literal would instead be read as a structural
    sub-schema, so it is wrapped in ``Equal`` to keep const's equality semantics.
    A value carrying a number or boolean anywhere gets the JSON-strict check,
    since Python equality would conflate ``1`` with ``True``.
    """
    if _needs_json_equality(value):
        return _JsonConst(value)
    if isinstance(value, list | dict):
        return Equal(value)
    return value


class _Not:
    """Decode of JSON Schema ``not``: accept a value only if the subschema rejects it."""

    def __init__(self, subschema: Any) -> None:
        """Compile the subschema the value must NOT match."""
        self._schema = Schema(subschema)

    def __repr__(self) -> str:
        """Render readably for error paths."""
        return f"Not({self._schema.schema!r})"

    def __call__(self, value: Any) -> Any:
        """Return the value if the subschema rejects it, else raise Invalid."""
        try:
            self._schema(value)
        except Invalid:
            return value

        raise Invalid(translation_key="must_not_match_not_schema")


def _unique_key(value: Any) -> Any:
    """Reduce a JSON value to a hashable key with JSON equality semantics.

    Lists and objects (unhashable in Python, but comparable JSON values) are
    frozen recursively. Booleans are tagged so they stay distinct from ``1``
    and ``0``; plain numbers keep Python's cross-type equality (``1 == 1.0``),
    both as JSON equality demands. Anything that is not a JSON value falls
    through unfrozen; an unhashable one is reported by the caller.
    """
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, list):
        return ("list", tuple(_unique_key(item) for item in value))
    if isinstance(value, dict):
        return (
            "dict",
            frozenset((key, _unique_key(item)) for key, item in value.items()),
        )
    return value


class _JsonUnique:
    """Decode of ``uniqueItems``: value-based uniqueness over JSON data.

    ``Unique()`` builds a ``set`` of the items (voluptuous parity), so an array
    of arrays or objects, all valid and comparable JSON, is rejected as
    "unhashable" instead of compared. This validator freezes JSON containers
    into hashable keys first, keeping the check linear. Per the spec the
    keyword only constrains arrays, so any other value passes vacuously.
    """

    def __repr__(self) -> str:
        """Render readably for error paths."""
        return "JsonUnique()"

    def __call__(self, value: Any) -> Any:
        """Return the value if its items are distinct JSON values, else raise."""
        if not isinstance(value, list | tuple):
            return value

        seen: set[Any] = set()
        duplicates: list[Any] = []
        for item in value:
            try:
                key = _unique_key(item)
                new = key not in seen
                if new:
                    seen.add(key)
            except TypeError as exc:
                raise Invalid(
                    translation_key="contains_unhashable_elements",
                    placeholders={"detail": str(exc)},
                ) from exc
            if not new:
                duplicates.append(item)

        if duplicates:
            raise Invalid(
                translation_key="contains_duplicate_items",
                placeholders={"items": duplicates},
            )
        return value


def _from_enum(values: Any) -> Any:
    """Build a membership check from a JSON Schema ``enum``, rejecting a non-array.

    An enum carrying a number or boolean anywhere gets the JSON-strict check
    (``In`` uses Python ``==``, which would conflate ``1`` with ``True``); a
    purely string/null enum keeps ``In`` and its friendlier miss suggestions.
    """
    if not isinstance(values, list):
        message = f"JSON Schema 'enum' must be an array, got {type(values).__name__}"
        raise SchemaError(message)
    if any(_needs_json_equality(value) for value in values):
        return _JsonEnum(list(values))
    return In(list(values))


def _from_combinator(
    subschemas: Any,
    keyword: str,
    factory: Any,
    ctx: _Decode,
) -> Any:
    """Build an Any/All from ``anyOf``/``allOf``, rejecting a non-array."""
    if not isinstance(subschemas, list):
        message = (
            f"JSON Schema {keyword!r} must be an array, got {type(subschemas).__name__}"
        )
        raise SchemaError(message)
    return factory(*[_from_node(sub, ctx) for sub in subschemas])


def _from_oneof(subschemas: Any, ctx: _Decode) -> Any:
    """Decode ``oneOf`` with its exact "one and only one branch matches" semantics.

    ``SomeOf`` with ``min_valid == max_valid == 1`` is exactly that: a value
    matching zero or two-or-more branches is rejected, unlike the looser ``anyOf``.
    This keeps an untrusted ``oneOf`` from widening into "any branch matches".
    """
    if not isinstance(subschemas, list):
        message = (
            f"JSON Schema 'oneOf' must be an array, got {type(subschemas).__name__}"
        )
        raise SchemaError(message)
    branches = [_from_node(sub, ctx) for sub in subschemas]
    return SomeOf(branches, min_valid=1, max_valid=1)


def _from_ref(ref: str, ctx: _Decode) -> Any:
    """Resolve a ``$ref`` JSON pointer to a (memoized) validator for its target.

    The placeholder is cached before the target is built, so a recursive
    reference resolves to the same deferred validator and ties the knot on the
    referenced node rather than the document root.
    """
    if not isinstance(ref, str):
        message = f"JSON Schema '$ref' must be a string, got {type(ref).__name__}"
        raise SchemaError(message)

    existing = ctx.refs.get(ref)
    if existing is not None:
        return existing

    deferred = _DeferredRef()
    ctx.refs[ref] = deferred
    target = _resolve_pointer(ref, ctx.root)
    deferred.schema = Schema(_from_node(target, ctx))

    return deferred


def _resolve_pointer(ref: str, root: dict[str, Any]) -> Any:
    """Resolve a local JSON pointer (``#``, ``#/a/b``, ``#/a/0``) against the document."""
    if ref == "#":
        # A bare ``#`` is the whole document, the common way a recursive schema
        # references its own root, so there is nothing to traverse.
        return root

    if not ref.startswith("#/"):
        message = f"only local JSON pointers are supported, got {ref!r}"
        raise SchemaError(message)

    target: Any = root
    for raw in ref[2:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        try:
            # A list segment is addressed by an integer index (RFC 6901).
            target = target[int(token)] if isinstance(target, list) else target[token]
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            message = f"cannot resolve JSON pointer {ref!r}"
            raise SchemaError(message) from exc

    return target


def _from_typed(node: dict[str, Any], ctx: _Decode) -> Any:
    """Dispatch on the ``type`` keyword, one of the seven JSON Schema type names.

    Only reached when ``type`` is present (a typeless node is handled by its
    constraints upstream), so the keyword must be a string or an array of them.
    """
    json_type = node.get("type")
    if isinstance(json_type, list):
        return _from_type_list(node, json_type, ctx)

    # A non-string, non-array ``type`` (including an explicit ``null``) is malformed.
    # Reject it rather than letting it leak as a hashing or membership error, or fall
    # through and widen to an accept-anything schema.
    if not isinstance(json_type, str):
        message = (
            f"JSON Schema 'type' must be a string or array, "
            f"got {type(json_type).__name__}"
        )
        raise SchemaError(message)

    if json_type in _SIMPLE_TYPES:
        return _SIMPLE_TYPES[json_type]

    if json_type == "object":
        return _from_object(node, ctx)

    if json_type == "array":
        return _from_array(node, ctx)

    if json_type == "string":
        return _from_string(node)

    if json_type in ("integer", "number"):
        base = _JSON_INTEGER if json_type == "integer" else _JSON_NUMBER
        return _from_number(node, base=base)

    # A non-empty ``type`` that is none of the seven JSON Schema types is malformed.
    # The schema may be untrusted, so it fails closed here rather than ignoring the
    # type and widening to an accept-anything ``object`` that would swallow the
    # sibling constraint keywords and accept input the author meant to forbid.
    message = f"JSON Schema 'type' is not a recognized type name: {json_type!r}"
    raise SchemaError(message)


def _from_type_list(node: dict[str, Any], types: list[Any], ctx: _Decode) -> Any:
    """Render a ``type`` array (``["string", "null"]``) as an Any of each type.

    ``types`` is untrusted JSON, so each entry must be a string: a non-string entry
    (a ``null`` becomes a ``type`` of None, which would otherwise fall through to an
    accept-anything schema and silently widen validation) is refused.
    """
    for name in types:
        if not isinstance(name, str):
            message = (
                f"JSON Schema 'type' array entries must be strings, "
                f"got {type(name).__name__}"
            )
            raise SchemaError(message)

    validators = [
        None if name == "null" else _from_typed({**node, "type": name}, ctx)
        for name in types
    ]
    return AnyValidator(*validators)


_NUMERIC_BOUND_KEYS = frozenset(
    {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"},
)

# Object and array assertion keywords. On a node without a ``type``, these still
# constrain instances of their type (any other instance passes them vacuously),
# so a typeless node carrying one must not decode to an accept-anything schema.
_OBJECT_KEYWORDS = frozenset(
    {
        "properties",
        "required",
        "additionalProperties",
        "minProperties",
        "maxProperties",
    },
)
_ARRAY_KEYWORDS = frozenset({"items", "prefixItems", "minItems", "maxItems"})


class _WhenType:
    """Apply a subschema only to instances of one JSON type.

    JSON Schema object and array keywords constrain only instances of their own
    type; every other value passes them vacuously. This wrapper carries that
    conditional applicability for a typeless node, so ``properties`` or ``items``
    without a ``type`` is honored on matching instances without rejecting the
    rest.
    """

    def __init__(self, base: type, subschema: Any) -> None:
        """Compile the subschema and remember the instance type it applies to."""
        self._base = base
        self._schema = Schema(subschema)

    def __repr__(self) -> str:
        """Render readably for error paths."""
        return f"WhenType({self._base.__name__}, {self._schema.schema!r})"

    def __call__(self, value: Any) -> Any:
        """Validate instances of the type; pass every other value through."""
        if not isinstance(value, self._base):
            return value
        return self._schema(value)


def _combine_constraints(node: dict[str, Any], ctx: _Decode) -> Any:
    """Combine a node's standalone constraint keywords into one validator, or None.

    With no ``type``, a JSON Schema still carries meaning through keywords like
    ``minimum``, ``minLength``, ``multipleOf``, ``uniqueItems``, and ``contains``.
    Each becomes its matching validator so the encoder's typeless output (a bare
    ``Range``, ``Length``, ``MultipleOf``, ``Unique``, or ``ContainsCount``) round
    trips. Object and array assertions (``properties``, ``required``, ``items``,
    and their siblings) also apply without a ``type``, scoped to instances of
    their type. None means the node carries no recognized constraint.
    """
    constraints = _from_constraints(node, ctx)
    if not constraints:
        return None

    if len(constraints) == 1:
        return constraints[0]

    return All(*constraints)


def _from_constraints(node: dict[str, Any], ctx: _Decode) -> list[Any]:
    """Collect the standalone constraint validators present on a node."""
    constraints: list[Any] = []
    has_array = bool(_ARRAY_KEYWORDS & node.keys())
    if _NUMERIC_BOUND_KEYS & node.keys():
        constraints.append(_from_range(node))
    if "multipleOf" in node:
        constraints.append(MultipleOf(_numeric(node, "multipleOf")))
    if "minLength" in node or "maxLength" in node:
        constraints.append(
            Length(
                min=_item_count(node, "minLength"), max=_item_count(node, "maxLength")
            ),
        )
    if "pattern" in node:
        constraints.append(Match(_safe_pattern(node["pattern"])))
    # When array keywords are present, the array facet below reads uniqueItems
    # and contains itself, scoped to arrays; adding them standalone here too
    # would double-apply them.
    if node.get("uniqueItems") is True and not has_array:
        constraints.append(_JsonUnique())
    if "contains" in node and not has_array:
        constraints.append(_from_contains(node, ctx))
    if _OBJECT_KEYWORDS & node.keys():
        constraints.append(_WhenType(dict, _from_object(node, ctx)))
    if has_array:
        constraints.append(_WhenType(list, _from_array(node, ctx)))

    return constraints


def _from_object(node: dict[str, Any], ctx: _Decode) -> Any:
    """Render a JSON Schema object as a mapping schema."""
    properties = node.get("properties", {})
    if not isinstance(properties, dict):
        message = f"JSON Schema 'properties' must be an object, got {type(properties).__name__}"
        raise SchemaError(message)

    required_raw = node.get("required", [])
    if not isinstance(required_raw, list):
        message = f"JSON Schema 'required' must be an array, got {type(required_raw).__name__}"
        raise SchemaError(message)

    # ``required`` entries are property names, so every entry must be a string. A
    # non-string entry (a number, or an unhashable nested array or object) never
    # matches a property name, so it would silently make a required field optional;
    # refuse it rather than honor a malformed document.
    if not all(isinstance(entry, str) for entry in required_raw):
        message = "JSON Schema 'required' must contain only property names (strings)"
        raise SchemaError(message)

    required: set[Any] = set(required_raw)
    mapping: dict[Any, Any] = {}
    for name, subschema in properties.items():
        if subschema is False:
            mapping[Forbidden(name)] = object
            continue
        key = _from_key(name, subschema, required=name in required)
        mapping[key] = _from_node(subschema, ctx)

    additional = node.get("additionalProperties")
    additional_schema = (
        _from_node(additional, ctx) if isinstance(additional, dict) else None
    )

    # A ``required`` name with no ``properties`` entry is still a presence
    # constraint; dropping it would widen an untrusted schema. Its value schema
    # is whatever ``additionalProperties`` says (an undeclared property), or
    # anything.
    for name in sorted(required - properties.keys()):
        mapping[Required(name)] = (
            additional_schema if additional_schema is not None else object
        )

    if additional_schema is not None:
        mapping[str] = additional_schema

    base = _object_base(mapping, additional, declared="properties" in node)
    min_props = _item_count(node, "minProperties")
    max_props = _item_count(node, "maxProperties")
    if min_props is not None or max_props is not None:
        return All(base, Length(min=min_props, max=max_props))

    return base


def _object_base(mapping: dict[Any, Any], additional: Any, *, declared: bool) -> Any:
    """Pick the base object schema from the property map and additionalProperties.

    A declared property set is a closed contract (probatio's deliberate strict
    default). But ``{"type": "object"}`` with no declared properties and no
    explicit ``additionalProperties`` is "any object", not a closed empty one; an
    explicit ``additionalProperties: false`` keeps an empty object closed. And a
    ``required`` list without a ``properties`` set constrains presence only, so
    undeclared extra keys stay allowed.
    """
    if additional is True:
        return Schema(mapping, extra=ALLOW_EXTRA)

    if not declared and additional is None:
        return Schema(mapping, extra=ALLOW_EXTRA) if mapping else dict

    return mapping


def _from_key(name: str, subschema: Any, *, required: bool) -> Marker:
    """Build the Required/Optional marker for one object property.

    A ``writeOnly`` property is a secret, so the key is wrapped in ``Secret`` (its
    value is redacted from error output), the counterpart of the ``writeOnly`` that
    ``to_json_schema`` emits for a ``Secret`` key.

    JSON Schema ``default`` is an annotation: it never satisfies ``required``. A
    probatio ``Required`` marker with a default does (it fills the value in), so a
    required property keeps presence enforcement and drops the default. On an
    optional property the default only fills the output, leaving the accept set
    unchanged, so there it is applied.
    """
    marker_cls = Required if required else Optional
    description = subschema.get("description") if isinstance(subschema, dict) else None
    if not required and isinstance(subschema, dict) and "default" in subschema:
        marker: Marker = marker_cls(
            name,
            default=subschema["default"],
            description=description,
        )
    else:
        marker = marker_cls(name, description=description)

    if isinstance(subschema, dict) and subschema.get("writeOnly") is True:
        return Secret(marker)
    return marker


def _from_prefix_items(prefix: Any, node: dict[str, Any], ctx: _Decode) -> Any:
    """Decode a closed positional ``prefixItems`` array into an ``ExactSequence``.

    Only the closed form (``items: false``, what ``to_json_schema`` emits for an
    ``ExactSequence``) maps cleanly. With ``items`` absent or a schema, JSON Schema
    allows additional items beyond the prefix, which ``ExactSequence`` (a
    fixed-length tuple) cannot represent, so the open tail is refused rather than
    silently rejecting valid arrays that carry extra items.
    """
    if not isinstance(prefix, list):
        message = (
            f"JSON Schema 'prefixItems' must be an array, got {type(prefix).__name__}"
        )
        raise SchemaError(message)

    if node.get("items") is not False:
        message = (
            "JSON Schema 'prefixItems' is only supported with 'items': false "
            "(a closed, fixed-length array); a schema or open tail does not map "
            "to a probatio sequence"
        )
        raise SchemaError(message)

    return ExactSequence([_from_node(element, ctx) for element in prefix])


def _from_array(node: dict[str, Any], ctx: _Decode) -> Any:
    """Render a JSON Schema array as a sequence schema, honoring item-count bounds.

    ``prefixItems`` with ``items: false`` (a closed, fixed-length positional array)
    round-trips an ``ExactSequence``. Without ``prefixItems``, ``items: false``
    forbids every element (only the empty array validates) and ``items: true``
    carries no per-item schema, so it reads as an unconstrained list.
    """
    prefix = node.get("prefixItems")
    if prefix is not None:
        return _from_prefix_items(prefix, node, ctx)

    items = node.get("items")
    if items is True:
        items = None
    elif items is not None and items is not False and not isinstance(items, dict):
        # The Draft-4 positional form ``items: [schema, ...]`` is not supported;
        # the supported positional form is ``prefixItems``. Refuse it cleanly
        # rather than leaking a TypeError from the node decoder.
        message = (
            "JSON Schema array 'items' must be an object; the positional list "
            "form is not supported (use 'prefixItems')"
        )
        raise SchemaError(message)

    min_items = _item_count(node, "minItems")
    max_items = _item_count(node, "maxItems")
    bounded = min_items is not None or max_items is not None
    has_contains = "contains" in node
    has_unique = node.get("uniqueItems") is True

    if items is False:
        # ``items: false`` with no ``prefixItems``: no element is allowed, so
        # only the empty array validates (an empty sequence schema is exactly
        # that).
        sequence: Any = []
    elif items is None:
        # No item schema: any list. Length, uniqueItems, and contains still apply,
        # so a constrained array accepts any element ([object]) but must satisfy
        # them.
        if not bounded and not has_contains and not has_unique:
            return list
        sequence = [object]
    elif items.keys() == {"anyOf"}:
        # The encoder renders a multi-item sequence schema ([int, str]) as an
        # ``items`` carrying only an ``anyOf``; decode that shape back to the
        # branch list. Any sibling keyword beside the ``anyOf`` makes it a
        # normal node whose facets must all apply, handled below.
        sequence = [_from_node(sub, ctx) for sub in items["anyOf"]]
    else:
        sequence = [_from_node(items, ctx)]

    constraints: list[Any] = []
    if bounded:
        constraints.append(Length(min=min_items, max=max_items))
    if has_unique:
        constraints.append(_JsonUnique())
    if has_contains:
        constraints.append(_from_contains(node, ctx))
    if constraints:
        return All(sequence, *constraints)

    return sequence


def _from_contains(node: dict[str, Any], ctx: _Decode) -> Any:
    """Build a contains check, honoring ``minContains``/``maxContains`` counts.

    JSON Schema ``contains`` requires at least one element to match a subschema
    (the spec default of ``minContains: 1``); a count bound sets how many. This
    is schema-matching, not membership, so it must not decode to probatio's
    ``Contains`` (which tests whether a literal value is an element). The
    counting validator carries the right semantics for the plain case too.
    """
    item = _from_node(node["contains"], ctx)
    min_count = _item_count(node, "minContains")
    max_count = _item_count(node, "maxContains")
    return _ContainsCount(item, 1 if min_count is None else min_count, max_count)


class _ContainsCount:
    """Require between ``minContains`` and ``maxContains`` items to match a schema."""

    def __init__(self, item_schema: Any, minimum: int, maximum: int | None) -> None:
        """Compile the item schema and store the count bounds."""
        self._schema = Schema(item_schema)
        self._min = minimum
        self._max = maximum

    def __repr__(self) -> str:
        """Render readably for error paths."""
        return f"ContainsCount(min={self._min}, max={self._max})"

    def __call__(self, value: Any) -> Any:
        """Return the value if the matching-item count is in range, else raise."""
        try:
            items = list(value)
        except TypeError as exc:
            raise ContainsInvalid(translation_key="not_a_collection") from exc

        count = 0
        for element in items:
            try:
                self._schema(element)
            except Invalid:
                continue
            count += 1

        if count < self._min:
            raise ContainsInvalid(
                translation_key="min_contains",
                placeholders={"min": self._min},
            )
        if self._max is not None and count > self._max:
            raise ContainsInvalid(
                translation_key="max_contains",
                placeholders={"max": self._max},
            )

        return value


def _item_count(node: dict[str, Any], key: str) -> int | None:
    """Read a non-negative integer item-count bound (``minItems``/``maxItems``), or None.

    A non-integer or negative bound would otherwise leak a TypeError from the
    ``Length`` check or silently validate data under a malformed count, so it is
    refused at decode with a clean ``SchemaError``. The JSON Schema count keywords
    are non-negative integers.
    """
    value = node.get(key)
    if value is None:
        return None

    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        message = f"JSON Schema {key!r} must be a non-negative integer, got {value!r}"
        raise SchemaError(message)

    return value


def _numeric(node: dict[str, Any], key: str) -> Any:
    """Read a numeric bound (``minimum``/``multipleOf``/...), or None.

    Reject bad bounds while decoding, before they can leak as comparison or
    modulo errors during validation.
    """
    value = node.get(key)
    if value is None or (
        isinstance(value, int | float) and not isinstance(value, bool)
    ):
        return value
    message = f"JSON Schema {key!r} must be a number, got {type(value).__name__}"
    raise SchemaError(message)


def _safe_pattern(pattern: Any) -> Any:
    """Reject a catastrophically backtracking ``pattern`` from an untrusted schema.

    The pattern may come from an untrusted document. Reject non-strings,
    catastrophic patterns, and invalid regular expressions while decoding.
    """
    if not isinstance(pattern, str):
        message = (
            f"JSON Schema 'pattern' must be a string, got {type(pattern).__name__}"
        )
        raise SchemaError(message)

    if is_catastrophic(pattern):
        message = (
            f"refusing to compile a potentially catastrophic regular "
            f"expression from an untrusted schema: {pattern!r}"
        )
        raise SchemaError(message)

    try:
        re.compile(pattern)
    except re.error as exc:
        message = (
            f"JSON Schema 'pattern' is not a valid regular expression: {pattern!r}"
        )
        raise SchemaError(message) from exc

    return pattern


def _from_string(node: dict[str, Any]) -> Any:
    """Render a JSON Schema string, attaching format and length constraints.

    A ``format`` that names a probatio validator (``date-time``, ``ipv4``,
    ``uuid``, and the rest of ``_FROM_FORMATS``) becomes that validator, and
    ``contentEncoding: base64`` becomes ``Base64`` (so a ``Base64`` round-trips);
    everything else stays a plain string with the length and pattern constraints.
    """
    # ``format`` comes from an untrusted document; a non-string value (a dict, say)
    # is not a hashable lookup key and is not a known format, so treat it as absent.
    fmt = node.get("format", "")
    base = _FROM_FORMATS.get(fmt, str) if isinstance(fmt, str) else str

    # ``contentEncoding: base64`` (JSON Schema) and ``format: byte`` (OpenAPI)
    # both mean a base64 string.
    if base is str and (
        node.get("contentEncoding") == "base64" or node.get("format") == "byte"
    ):
        base = Base64()

    constraints: list[Any] = []
    if "minLength" in node or "maxLength" in node:
        constraints.append(
            Length(
                min=_item_count(node, "minLength"), max=_item_count(node, "maxLength")
            ),
        )
    if "pattern" in node:
        constraints.append(Match(_safe_pattern(node["pattern"])))
    if not constraints:
        return base

    return All(base, *constraints)


def _from_number(node: dict[str, Any], *, base: Any) -> Any:
    """Render a numeric JSON Schema, attaching range and multiple constraints."""
    constraints: list[Any] = []
    if _NUMERIC_BOUND_KEYS & node.keys():
        constraints.append(_from_range(node))
    if "multipleOf" in node:
        constraints.append(MultipleOf(_numeric(node, "multipleOf")))
    if not constraints:
        return base

    return All(base, *constraints)


def _from_range(node: dict[str, Any]) -> Range:
    """Build a Range from JSON Schema minimum/maximum bounds.

    The Draft 2020-12 form makes ``minimum`` and ``exclusiveMinimum`` independent
    numbers, so when both are present the binding lower bound is the more
    restrictive one. The Draft-04 form (``exclusiveMinimum: true`` beside a
    ``minimum``) reads the same way once the boolean is resolved.
    """
    minimum, min_included = _resolve_bound(node, "minimum", "exclusiveMinimum")
    maximum, max_included = _resolve_bound(node, "maximum", "exclusiveMaximum")
    return Range(
        min=minimum,
        max=maximum,
        min_included=min_included,
        max_included=max_included,
    )


def _resolve_bound(
    node: dict[str, Any],
    inclusive_key: str,
    exclusive_key: str,
) -> tuple[Any, bool]:
    """Resolve one bound to (value, included), reconciling inclusive and exclusive.

    Handles the Draft-04 boolean ``exclusive*`` (a flag on ``minimum``) and the
    Draft 2020-12 numeric ``exclusive*`` (a bound in its own right). When both an
    inclusive and a numeric exclusive bound are present, the tighter one wins.
    """
    inclusive = _numeric(node, inclusive_key)
    raw_exclusive = node.get(exclusive_key)

    # Draft-04: ``exclusiveMinimum: true`` flips ``minimum`` to exclusive. The
    # boolean form is only meaningful beside its inclusive partner (Draft 4
    # requires it); without one there is no bound to flip, so the document is
    # malformed and silently producing no constraint would widen it.
    if isinstance(raw_exclusive, bool):
        if inclusive is None:
            message = (
                f"JSON Schema boolean {exclusive_key!r} (Draft 4 form) requires "
                f"{inclusive_key!r} beside it"
            )
            raise SchemaError(message)
        return inclusive, not raw_exclusive

    exclusive = _numeric(node, exclusive_key)
    if exclusive is None:
        return inclusive, True
    if inclusive is None:
        return exclusive, False

    # Both present (Draft 2020-12): keep the tighter lower/upper bound.
    if inclusive_key == "minimum":
        return (exclusive, False) if exclusive >= inclusive else (inclusive, True)
    return (exclusive, False) if exclusive <= inclusive else (inclusive, True)
