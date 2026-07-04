"""OpenAPI codec: ``to_openapi``.

``to_openapi`` renders a schema as an OpenAPI Schema object, matching the output
of voluptuous-openapi's ``convert`` so LLM tool calling and MCP consumers work on
probatio schemas. It supports both OpenAPI 3.0 (``nullable``) and 3.1 (``type:
null``) and takes the same ``custom_serializer`` hook, which returns a dict to
override a node or ``UNSUPPORTED`` to defer.

The shape differs from JSON Schema in small but load-bearing ways (the 3.0/3.1
nullable split, ``required`` always present, ``additionalProperties`` only when
open, ``format`` names, a type fallback for bare numeric/string constraints), so
this is a distinct codec rather than a tweak of ``to_json_schema``.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from inspect import isroutine, signature
from types import UnionType
from typing import Any, TypeVar, Union, cast, get_args, get_origin, get_type_hints

from probatio.codecs._shared import (
    FORMAT_BY_TYPE,
    STRING_TYPES,
    UNSUPPORTED,
)
from probatio.codecs._shared import UNREPRESENTABLE as _UNREPRESENTABLE
from probatio.codecs._shared import json_safe as _json_safe
from probatio.codecs._shared import ordered_values as _ordered
from probatio.error import SchemaError
from probatio.markers import (
    Exclusive,
    Inclusive,
    Optional,
    Required,
    Self,
    Undefined,
    resolve_key,
)
from probatio.schema import ALLOW_EXTRA, REMOVE_EXTRA, Schema
from probatio.validators import (
    All,
    AsDate,
    AsDatetime,
    AsTime,
    AsTimedelta,
    Base64,
    Capitalize,
    Clamp,
    Coerce,
    Contains,
    Date,
    Datetime,
    Duration,
    Email,
    Equal,
    ExactSequence,
    FqdnUrl,
    FromEpoch,
    FromPercentage,
    In,
    Length,
    Literal,
    Lower,
    Match,
    Maybe,
    Msg,
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
from probatio.validators import Union as UnionValidator

_NONE_TYPE = type(None)
_V3_0 = "3.0"
_V3_1 = "3.1.0"

_OPENAPI_TYPES: dict[type, str] = {
    bool: "boolean",
    int: "integer",
    float: "number",
    str: "string",
}
# The identity-comparable validators that render as a bare ``format``. The name
# matches voluptuous-openapi, which uses the validator's lower-cased name.
_OPENAPI_FORMATS: dict[Any, str] = {
    Lower: "lower",
    Upper: "upper",
    Capitalize: "capitalize",
    Title: "title",
    Strip: "strip",
    Email: "email",
    Url: "url",
    FqdnUrl: "fqdnurl",
}
_OPEN_OBJECT: dict[str, Any] = {"type": "object", "additionalProperties": True}
_OA_PORT_MIN = 1
_OA_PORT_MAX = 65535
_OA_PERCENT_MIN = 0
_OA_PERCENT_MAX = 100


def to_openapi(
    schema: Any,
    *,
    custom_serializer: Any = None,
    openapi_version: str = _V3_0,
) -> dict[str, Any]:
    """Render a schema as an OpenAPI Schema object.

    ``openapi_version`` is ``"3.0"`` (the default, emitting ``nullable``) or
    ``"3.1.0"`` (emitting ``type: null``). ``custom_serializer`` is called first
    for each node and may return a dict to override the default, or ``UNSUPPORTED``
    to defer.

    A raw schema that references itself (a dict holding itself as a value) has no
    finite rendering, so the runaway recursion is reported as a clean
    ``SchemaError`` rather than a bare ``RecursionError``.
    """
    try:
        rendered = _oa(schema, custom_serializer, openapi_version)
    except RecursionError as exc:
        message = (
            "schema is too deeply nested or references itself; use the Self "
            "marker for a recursive schema"
        )
        raise SchemaError(message) from exc
    return cast("dict[str, Any]", _admit_null(rendered, openapi_version))


def _admit_null(node: Any, version: str) -> Any:
    """Make every nullable schema actually accept null, per the OpenAPI version.

    A ``nullable: true`` schema that also carries an ``enum`` rejects null unless
    null is in the enum (the flag admits the null *type*, not a value outside the
    enumerated set), so null is added to such an enum. On 3.1 there is no
    ``nullable`` keyword at all, so it is rewritten as ``"null"`` on the type.
    """
    if isinstance(node, dict):
        result = {key: _admit_null(value, version) for key, value in node.items()}
        if result.get("nullable") is True:
            _mark_nullable(result, version)
        return result
    if isinstance(node, list):
        return [_admit_null(item, version) for item in node]
    return node


_COMBINATORS = ("anyOf", "oneOf", "allOf")


def _mark_nullable(result: dict[str, Any], version: str) -> None:
    """Rewrite a ``nullable: true`` dict so it actually accepts null on ``version``.

    A ``nullable`` flag is inert on an ``enum`` (null must be a member) and on a
    combinator (3.0 ignores it there), so null is added as an enum member or a
    dedicated branch. On 3.1 there is no ``nullable`` keyword, so it becomes
    ``"null"`` on the type.
    """
    enum = result.get("enum")
    if isinstance(enum, list) and None not in enum:
        result["enum"] = [*enum, None]

    combinator = next((key for key in _COMBINATORS if key in result), None)
    if combinator is not None:
        # A combinator has no type to carry null, so admit it with a branch.
        result[combinator] = [*result[combinator], _oa_null(version)]
        result.pop("nullable", None)
        return

    if version == _V3_1:
        del result["nullable"]
        node_type = result.get("type")
        # The renderer only ever carries ``nullable`` beside a scalar ``type``; a
        # type array is produced here, so there is no list case to widen.
        if isinstance(node_type, str):
            result["type"] = [node_type, "null"]


def _ensure_default(value: dict[str, Any]) -> dict[str, Any]:
    """Give a value a type when it has none, the way voluptuous-openapi does."""
    # A ``$ref`` (a recursive ``Self``) is a complete schema on its own; adding a
    # ``type`` beside it would contradict the reference.
    if "$ref" in value:
        return value
    if all(key not in value for key in ("type", "anyOf", "oneOf", "allOf", "not")):
        bounds = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")
        value["type"] = "number" if any(key in value for key in bounds) else "string"
    return value


def _oa(node: Any, custom: Any, version: str) -> dict[str, Any]:
    """Convert one schema node into an OpenAPI Schema object."""
    additional: Any = None
    # The strict default (``PREVENT_EXTRA``) closes the object; ``ALLOW_EXTRA`` and
    # ``REMOVE_EXTRA`` both accept extra keys, so they stay open. A bare nested dict
    # has no policy of its own and defaults to closed.
    closed = True
    # A ``Schema`` value is itself a valid validator, so schemas can nest. Unwrap
    # every layer: the innermost one does the validation, so its extra policy wins.
    while isinstance(node, Schema):
        closed = node.extra not in (ALLOW_EXTRA, REMOVE_EXTRA)
        additional = True if node.extra == ALLOW_EXTRA else None
        node = node.schema

    if custom is not None:
        result = custom(node)
        if result is not UNSUPPORTED:
            return cast("dict[str, Any]", result)

    if node is Self:
        # ``Self`` is the recursive reference to the whole enclosing schema; ``#``
        # targets the document root, the common top-level recursive-schema case.
        return {"$ref": "#"}

    if isinstance(node, dict):
        return _oa_mapping(node, custom, version, additional, closed=closed)
    if isinstance(node, list | tuple | set | frozenset):
        return _oa_sequence(node, custom, version)

    generic = _oa_generic(node, custom, version)
    if generic is not None:
        return generic

    return _oa_leaf(node, custom, version)


def _oa_generic(node: Any, custom: Any, version: str) -> dict[str, Any] | None:
    """Render a parameterized ``list``/``set``/``tuple``/``dict``, or None.

    Mirrors voluptuous-openapi: a parameterized sequence describes its items by
    the first type argument only (``tuple[int, str]`` becomes an array of int);
    a ``dict[K, V]`` becomes an object whose ``additionalProperties`` come from
    the ``{K: V}`` mapping, with ``V`` being ``Any`` or a ``TypeVar`` meaning an
    open object. Anything else (a bare type, ``frozenset[int]``) returns None.
    """
    origin = get_origin(node)
    args = get_args(node)

    if origin in (list, set, tuple) and args:
        return _oa_sequence([args[0]], custom, version)
    if origin is dict and len(args) == 2:
        key_type, value_type = args
        if value_type is Any or isinstance(value_type, TypeVar):
            return _oa_type(dict, version)
        return _oa_mapping({key_type: value_type}, custom, version, None)
    return None


def _oa_mapping(
    node: dict[Any, Any],
    custom: Any,
    version: str,
    additional: Any,
    *,
    closed: bool = True,
) -> dict[str, Any]:
    """Render a mapping as an OpenAPI object, mirroring convert()'s key rules."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    constraint_groups: list[list[str]] = []
    inclusive: dict[str, list[str]] = {}
    exclusive: dict[str, _OaExclusiveGroup] = {}

    for key, value in node.items():
        facets = resolve_key(key)
        marker = facets.marker
        pkey = facets.key
        pval = _oa(value, custom, version)
        if facets.description:
            pval["description"] = facets.description
        if isinstance(marker, Required | Optional) and not isinstance(
            marker.default,
            Undefined,
        ):
            # A non-JSON default (a ``datetime``, say) is rendered JSON-safe, or
            # omitted when it has no representation, so the emitted document never
            # crashes ``json.dumps``.
            default = _json_safe(marker.default())
            if default is not _UNREPRESENTABLE:
                pval["default"] = default
        if facets.secret:
            pval["writeOnly"] = True
        if isinstance(marker, Required) and not isinstance(pkey, AnyValidator):
            required.append(str(pkey))
        pval = _ensure_default(pval)

        # A group marker adds an object-level constraint (all-or-none, at-most-one)
        # on top of the property it declares, collected here and emitted below.
        if isinstance(marker, Inclusive) and isinstance(pkey, str):
            inclusive.setdefault(marker.group_of_inclusion, []).append(pkey)
        elif isinstance(marker, Exclusive) and isinstance(pkey, str):
            group = exclusive.setdefault(marker.group_of_exclusion, _OaExclusiveGroup())
            group.members.append(pkey)
            group.required = group.required or marker.group_required
            group.has_default = group.has_default or not isinstance(
                marker.default, Undefined
            )

        if isinstance(pkey, AnyValidator):
            props, any_group = _expand_any_key(
                pkey,
                pval,
                required=isinstance(marker, Required),
                wildcard=value is object,
            )
            properties.update(props)
            if any_group is not None:
                constraint_groups.append(any_group)
        elif isinstance(pkey, str):
            properties[pkey] = pval
        else:
            additional = _absorb_extra(pval, additional)

    dependent_required, group_constraints = _group_constraints(
        inclusive, exclusive, version
    )
    constraints = _ObjectConstraints(
        required_any=constraint_groups,
        dependent_required=dependent_required,
        all_of=group_constraints,
    )
    return _assemble_object(
        properties, required, additional, constraints, closed=closed
    )


@dataclass
class _OaExclusiveGroup:
    """The members of an ``Exclusive`` group and how an empty group is judged."""

    members: list[str] = field(default_factory=list)
    required: bool = False
    has_default: bool = False


@dataclass
class _ObjectConstraints:
    """The object-level constraints collected while walking a mapping's keys.

    ``required_any`` is the list of at-least-one name groups (a required ``Any``
    key), combined into one ``anyOf``. ``dependent_required`` is the merged 3.1
    all-or-none map. ``all_of`` holds the remaining group constraints (3.0
    all-or-none and every ``Exclusive`` group).
    """

    required_any: list[list[str]] = field(default_factory=list)
    dependent_required: dict[str, list[str]] = field(default_factory=dict)
    all_of: list[dict[str, Any]] = field(default_factory=list)


def _group_constraints(
    inclusive: dict[str, list[str]],
    exclusive: dict[str, _OaExclusiveGroup],
    version: str,
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    """Build the constraints for the Inclusive and Exclusive groups.

    Returns a ``(dependentRequired, allOf)`` pair. An ``Inclusive`` group is
    all-or-none: on OpenAPI 3.1 (JSON Schema 2020-12) it merges into one
    ``dependentRequired`` sibling, the idiomatic keyword ``from_openapi`` reads
    back into an ``Inclusive`` group. OpenAPI 3.0 lacks ``dependentRequired`` (and
    silently ignores it), so there each group renders under ``allOf`` instead. An
    ``Exclusive`` group (at most one, or exactly one when required with no default)
    always renders under ``allOf``. The ``allOf`` entries never collide on a
    keyword with each other or with the ``dependentRequired`` sibling.
    """
    groups = [members for members in inclusive.values() if len(members) > 1]
    dependent: dict[str, list[str]] = {}
    all_of: list[dict[str, Any]] = []
    if version == _V3_1:
        for members in groups:
            for member in members:
                dependent[member] = [other for other in members if other != member]
    else:
        all_of += [_oa_inclusive_30(members) for members in groups]
    all_of += [
        constraint
        for constraint in (
            _oa_exclusive_constraint(group) for group in exclusive.values()
        )
        if constraint
    ]
    return dependent, all_of


def _oa_inclusive_30(members: list[str]) -> dict[str, Any]:
    """Render an all-or-none group for OpenAPI 3.0, which lacks ``dependentRequired``.

    All-or-none is spelled with the keywords 3.0 does have: exactly one of "every
    member present" or "no member present" holds, which rejects any partial
    combination.
    """
    return {
        "oneOf": [
            {"required": list(members)},
            {"not": {"anyOf": [{"required": [member]} for member in members]}},
        ],
    }


def _oa_exclusive_constraint(group: _OaExclusiveGroup) -> dict[str, Any]:
    """Render one ``Exclusive`` group as at-most-one, or exactly-one when required.

    A required group with no default demands exactly one member (``oneOf`` over the
    per-member ``required``). Otherwise at most one member may appear: the negation
    of any two being present together.
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


def _expand_any_key(
    pkey: AnyValidator,
    pval: dict[str, Any],
    *,
    required: bool,
    wildcard: bool,
) -> tuple[dict[str, Any], list[str] | None]:
    """Expand an ``Any`` key into (properties to add, optional constraint group)."""
    names = [str(item) for item in pkey.validators]
    if required:
        props = {} if wildcard else {name: pval.copy() for name in names}
        return props, names
    return {name: pval.copy() for name in names}, None


def _absorb_extra(pval: dict[str, Any], additional: Any) -> Any:
    """Fold a type-key value into the object's ``additionalProperties``."""
    if pval == _OPEN_OBJECT:
        return True
    return pval if additional is None else additional


def _assemble_object(
    properties: dict[str, Any],
    required: list[str],
    additional: Any,
    constraints: _ObjectConstraints,
    *,
    closed: bool,
) -> dict[str, Any]:
    """Build the final object dict from the collected pieces.

    A closed mapping (the strict ``PREVENT_EXTRA`` default) emits
    ``additionalProperties: false`` so undeclared keys are rejected. An open one
    (``ALLOW_EXTRA``/``REMOVE_EXTRA``, or a variable-key value schema) emits the
    open ``additionalProperties`` and, when it has no declared properties and no
    variable-key schema, stays the bare open-object shape.
    """
    result: dict[str, Any] = {"type": "object"}

    if properties or not additional:
        result["properties"] = properties
        # OpenAPI 3.0 requires ``required`` to be non-empty, so an empty list is
        # omitted rather than emitted (``required: []`` is invalid there).
        if required:
            result["required"] = required
    if additional:
        # ``True`` (open) or a variable-key value schema.
        result["additionalProperties"] = additional
    elif closed:
        # A closed mapping rejects undeclared keys; an open (REMOVE_EXTRA) one is
        # left without the keyword, accepting extra keys the way it strips them.
        result["additionalProperties"] = False
    if constraints.required_any:
        result["anyOf"] = [
            {"required": list(combination)}
            for combination in itertools.product(*constraints.required_any)
        ]
    if constraints.dependent_required:
        # OpenAPI 3.1 all-or-none: a sibling ``from_openapi`` reads back as Inclusive.
        result["dependentRequired"] = constraints.dependent_required
    if constraints.all_of:
        # The remaining group constraints go under ``allOf`` so they never collide
        # on a keyword with each other or with the ``anyOf`` above.
        result["allOf"] = constraints.all_of
    return result


def _oa_sequence(node: Any, custom: Any, version: str) -> dict[str, Any]:
    """Render a sequence schema as an OpenAPI array.

    A single element schema is the item schema. Several elements ([int, str])
    mean "each item matches any of these", so they merge into an ``anyOf`` item
    schema, not a positional ``items`` array (which would wrongly constrain by
    position). An empty sequence accepts only the empty array.
    """
    items = [_ensure_default(_oa(item, custom, version)) for item in _ordered(node)]
    if len(items) == 1:
        return {"type": "array", "items": items[0]}
    if not items:
        return {"type": "array", "maxItems": 0}
    return {"type": "array", "items": {"anyOf": items}}


def _oa_leaf(node: Any, custom: Any, version: str) -> dict[str, Any]:
    """Render a leaf node: a validator, a literal, a type, or None."""
    combinator = _oa_combinator(node, custom, version)
    if combinator is not None:
        return combinator

    if isinstance(node, Coerce):
        node = node.type
    if isinstance(node, str | int | float | bool):
        return {"type": _OPENAPI_TYPES[type(node)], "enum": [node]}
    if node is None:
        return _oa_null(version)

    typed = _oa_type(node, version)
    if typed or not callable(node):
        return typed

    return _oa_callable(node, custom, version)


def _oa_callable(node: Any, custom: Any, version: str) -> dict[str, Any]:
    """Render a bare callable by the type hint of its first parameter.

    Mirrors voluptuous-openapi: inspect a function or method directly, or a
    callable instance through ``__call__``. The first parameter's annotation
    becomes the schema; missing or unusable annotations become an open schema.
    """
    try:
        hints = get_type_hints(
            node if isroutine(node) or isinstance(node, type) else node.__call__
        )
        params = list(signature(node).parameters.keys())
    except (TypeError, NameError, ValueError):
        return {}

    hint = hints.get(params[0], Any) if params else Any
    if hint is Any or isinstance(hint, TypeVar):
        return {}

    if isinstance(hint, UnionType) or get_origin(hint) is Union:
        members = [arg for arg in get_args(hint) if not isinstance(arg, TypeVar)]
        if len(members) > 1:
            hint = AnyValidator(*members)
        elif len(members) == 1 and members[0] is not _NONE_TYPE:
            hint = members[0]
        else:
            return {}

    return _ensure_default(_oa(hint, custom, version))


def _oa_combinator(node: Any, custom: Any, version: str) -> dict[str, Any] | None:
    """Render the combinators and constraint validators, or None if not one."""
    if isinstance(node, All):
        return _oa_all(node, custom, version)
    if isinstance(node, Clamp | Range):
        return _oa_range(node, version)
    if isinstance(node, Length):
        return _oa_length(node)

    # Date and Time subclass Datetime, so they must be matched before it. The As*
    # parsers are not subclasses, but describe the same string on the wire.
    if isinstance(node, Time | AsTime):
        return {"type": "string", "format": "time"}
    if isinstance(node, Date | AsDate):
        return {"type": "string", "format": "date"}
    if isinstance(node, Datetime | AsDatetime):
        return {"type": "string", "format": "date-time"}

    if isinstance(node, FromEpoch):
        # A Unix timestamp on the wire is a number (``FromEpoch`` takes an int or a
        # fractional-second float); the datetime is internal.
        return {"type": "number"}
    if isinstance(node, Match):
        source = node.pattern.pattern
        # A bytes pattern has no OpenAPI form (schema strings are text), so it
        # renders as a plain string rather than crashing on the missing ``.pattern``.
        if isinstance(source, bytes):
            return {"type": "string"}
        return {"pattern": source}
    if isinstance(node, Equal | Literal):
        return _oa_enum([node.target if isinstance(node, Equal) else node.lit])
    if isinstance(node, In):
        return _oa_enum(list(node.container))
    if isinstance(node, NotIn):
        enum = _oa_enum(list(node.container))
        return {"not": enum} if enum else {}
    if node in _OPENAPI_FORMATS:
        return {"format": _OPENAPI_FORMATS[node]}

    if isinstance(node, Msg):
        # ``Msg`` only swaps the error message; the shape is the wrapped validator.
        return _oa(node.validator, custom, version)
    if isinstance(node, Maybe):
        return _oa_any([None, node.validator], custom, version)
    # ``Union``/``Switch`` accept any branch (the discriminant is an optimization),
    # so they render like ``Any``, sharing its version-aware nullable handling.
    if isinstance(node, AnyValidator | UnionValidator):
        return _oa_any(list(node.validators), custom, version)
    if isinstance(node, SomeOf):
        return _oa_some_of(node, custom, version)

    collection = _oa_collection(node, custom, version)
    if collection is not None:
        return collection

    return _oa_typed(node)


def _oa_some_of(node: SomeOf, custom: Any, version: str) -> dict[str, Any]:
    """Render a SomeOf for the counts OpenAPI can express, else an open schema.

    Exactly one branch (``min == max == 1``) is ``oneOf``, at least one
    (``min == 1``, ``max`` the branch count) is ``anyOf``, and every branch
    (``min == max == count``) is ``allOf``; any other count widens to open.
    """
    branches = [_oa(validator, custom, version) for validator in node.validators]
    count = len(branches)
    if node.min_valid == node.max_valid == 1:
        return {"oneOf": branches}
    if node.min_valid == 1 and node.max_valid == count:
        return {"anyOf": branches}
    if node.min_valid == node.max_valid == count:
        return {"allOf": branches}
    return {}


def _oa_collection(node: Any, custom: Any, version: str) -> dict[str, Any] | None:
    """Render the array/string collection constraints, or None if not one.

    ``contains`` and ``prefixItems`` are JSON Schema keywords OpenAPI 3.1 shares
    but 3.0 lacks (and misreads), so on 3.0 the positional/contains constraint is
    dropped to a plain array rather than emitted in a form a 3.0 consumer breaks on.
    """
    if isinstance(node, Unique):
        return {"type": "array", "uniqueItems": True}
    if isinstance(node, Contains):
        if version == _V3_1:
            return {
                "type": "array",
                "contains": _ensure_default(_oa(node.item, custom, version)),
            }
        return {"type": "array"}
    if isinstance(node, ExactSequence):
        if version == _V3_1:
            prefix = [_ensure_default(_oa(v, custom, version)) for v in node.validators]
            return {"type": "array", "prefixItems": prefix, "items": False}
        return {"type": "array"}
    if isinstance(node, Duration | AsTimedelta):
        return {"type": "string", "format": "duration"}
    return None


def _oa_typed(node: Any) -> dict[str, Any] | None:
    """Render the network, identifier, and numeric-bound validators."""
    for validator_type, json_format in FORMAT_BY_TYPE.items():
        if isinstance(node, validator_type):
            return {"type": "string", "format": json_format}

    if isinstance(node, STRING_TYPES):
        return {"type": "string"}
    if isinstance(node, Port):
        return {"type": "integer", "minimum": _OA_PORT_MIN, "maximum": _OA_PORT_MAX}
    if isinstance(node, Percentage | FromPercentage):
        return {
            "type": "number",
            "minimum": _OA_PERCENT_MIN,
            "maximum": _OA_PERCENT_MAX,
        }
    if isinstance(node, MultipleOf):
        return {"type": "number", "multipleOf": node.factor}
    if isinstance(node, Base64):
        return {"type": "string", "contentEncoding": "base64"}

    return None


def _oa_all(node: All, custom: Any, version: str) -> dict[str, Any]:
    """Merge an All's parts, falling back to allOf when keys conflict."""
    merged: dict[str, Any] = {}
    all_of: list[dict[str, Any]] = []
    fallback = False

    for validator in node.validators:
        part = _oa(validator, custom, version)
        if not part or part in all_of or part == _OPEN_OBJECT:
            continue
        if any(part[key] != merged[key] for key in part.keys() & merged.keys()):
            fallback = True
        all_of.append(part)
        if not fallback:
            merged.update(part)

    if fallback:
        return {"allOf": all_of}
    return _ensure_default(_retarget_length(merged))


# A ``Length`` always renders the string-length keys, so an All that pins an
# array or object length has to move the bounds onto the type's own keyword.
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


def _oa_range(node: Clamp | Range, version: str) -> dict[str, Any]:
    """Render a Range or Clamp as OpenAPI numeric bounds (Clamp is inclusive).

    OpenAPI 3.0 (Draft 4) spells an exclusive bound as a boolean flag beside the
    inclusive keyword (``minimum`` plus ``exclusiveMinimum: true``); 3.1 (JSON
    Schema) uses the numeric ``exclusiveMinimum`` form. A non-numeric bound (a
    ``datetime``, say) has no OpenAPI numeric keyword, so it is omitted.
    """
    result: dict[str, Any] = {}
    min_exclusive = isinstance(node, Range) and not node.min_included
    max_exclusive = isinstance(node, Range) and not node.max_included
    minimum = _json_safe(node.min)
    maximum = _json_safe(node.max)
    if node.min is not None and isinstance(minimum, int | float):
        result.update(
            _oa_bound("minimum", minimum, exclusive=min_exclusive, version=version)
        )
    if node.max is not None and isinstance(maximum, int | float):
        result.update(
            _oa_bound("maximum", maximum, exclusive=max_exclusive, version=version)
        )
    return result


def _oa_bound(
    key: str,
    value: float,
    *,
    exclusive: bool,
    version: str,
) -> dict[str, Any]:
    """Render one numeric bound in the version's exclusive form."""
    exclusive_key = "exclusiveMinimum" if key == "minimum" else "exclusiveMaximum"
    if not exclusive:
        return {key: value}
    if version == _V3_1:
        return {exclusive_key: value}
    # OpenAPI 3.0: the boolean flag beside the inclusive bound.
    return {key: value, exclusive_key: True}


def _oa_length(node: Length) -> dict[str, Any]:
    """Render a Length as OpenAPI string-length bounds."""
    result: dict[str, Any] = {}
    if node.min is not None:
        result["minLength"] = node.min
    if node.max is not None:
        result["maxLength"] = node.max
    return result


def _oa_enum(values: list[Any]) -> dict[str, Any]:
    """Render an enum (from In or an Enum type), keeping any null member.

    Null stays *in* the enum (``nullable: true`` admits the null type, not a value
    outside the enumerated set), and a ``nullable`` flag is added on 3.0 so the
    null type passes too (``_admit_null`` rewrites it for 3.1). A single member
    type labels the enum; a mixed-type enum (``In(["a", 1])``) is left untyped so
    it accepts every listed value rather than mislabel by the first member.
    """
    has_null = False
    cleaned: list[Any] = []
    for value in _ordered(values):
        if value is None or value is _NONE_TYPE:
            has_null = True
            continue
        # An enum member with no JSON form (a ``datetime``, an ``Enum``) is
        # rendered JSON-safe. A member with no representation at all (``bytes``)
        # drops the whole enum to open rather than leak an unserializable value.
        safe = _json_safe(value)
        if safe is _UNREPRESENTABLE:
            return {"nullable": True} if has_null else {}
        cleaned.append(safe)

    # OpenAPI requires enum members to be unique, so drop duplicates the container
    # may hold (``In([0, 0])``), keeping first-seen order.
    cleaned = _dedup_preserving_order(cleaned)
    member_types = {type(member) for member in cleaned}
    result: dict[str, Any] = {}
    if len(member_types) == 1:
        result["type"] = _OPENAPI_TYPES.get(cleaned[0].__class__, "string")
    result["enum"] = [*cleaned, None] if has_null else cleaned
    if has_null:
        result["nullable"] = True
    return result


def _oa_null(version: str) -> dict[str, Any]:
    """Render ``None`` per the OpenAPI version."""
    if version == _V3_1:
        return {"type": "null"}
    return {"type": "object", "nullable": True, "description": "Must be null"}


def _oa_any(validators: list[Any], custom: Any, version: str) -> dict[str, Any]:
    """Render an Any (or Maybe), a faithful port of voluptuous-openapi's Any block.

    On 3.0 a top-level ``None`` becomes the ``nullable`` flag; on 3.1 it stays a
    ``{"type": "null"}`` branch. Branches are flattened, de-duplicated (treating a
    nullable and non-nullable twin as one), and same-type enums merged.
    """
    nullable = False
    if version == _V3_0 and any(v is None or v is _NONE_TYPE for v in validators):
        validators = [v for v in validators if v is not None and v is not _NONE_TYPE]
        nullable = True

    if not validators:
        # Every branch was ``None`` (an ``Any(None, None)``), so only null is
        # accepted; an empty ``anyOf`` is invalid, so render the null schema.
        return _oa_null(version)

    if len(validators) == 1:
        result = _oa(validators[0], custom, version)
        if nullable:
            result["nullable"] = True
        return result

    any_of, nested_nullable = _flatten_any(
        [_oa(validator, custom, version) for validator in validators],
    )
    nullable = nullable or nested_nullable

    return _collapse_any(_dedup_any(any_of), nullable=nullable)


def _flatten_any(any_of: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Inline nested anyOf entries, reporting whether any carried ``nullable``."""
    flattened: list[dict[str, Any]] = []
    nullable = False

    for item in any_of:
        if item.get("anyOf"):
            flattened.extend(item["anyOf"])
            nullable = nullable or bool(item.get("nullable"))
        else:
            flattened.append(item)

    return flattened, nullable


def _dedup_preserving_order(values: list[Any]) -> list[Any]:
    """Drop duplicate enum values by equality, keeping first-seen order.

    Used when a member is unhashable (an enum of lists or dicts, valid in JSON
    Schema), where ``list(set(...))`` would raise. Enums are short, so the
    quadratic scan does not matter.
    """
    result: list[Any] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _dedup_any(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """De-duplicate branches, unifying nullable twins and merging same-type enums."""
    out: list[dict[str, Any]] = []
    for item in items:
        if item in out:
            continue
        probe = dict(item)
        if item.get("nullable"):
            probe.pop("nullable")
            if probe in out:
                out[out.index(probe)]["nullable"] = True
                continue
        probe["nullable"] = True
        if probe in out:
            continue
        twin = _enum_twin(item, out)
        if twin is not None:
            if item.get("nullable"):
                twin["nullable"] = True
            combined = twin["enum"] + item["enum"]
            try:
                # Match voluptuous-openapi's ``list(set(...))`` for the common
                # hashable case, so the converted output stays identical.
                twin["enum"] = list(set(combined))
            except TypeError:
                # Unhashable enum members (an enum of lists or dicts) cannot go
                # through a set; dedup by equality instead, keeping order. The
                # oracle cannot convert these at all, so there is nothing to match.
                twin["enum"] = _dedup_preserving_order(combined)
            continue
        out.append(item)

    return out


def _collapse_any(any_of: list[dict[str, Any]], *, nullable: bool) -> dict[str, Any]:
    """Collapse a de-duplicated anyOf to one entry where possible, applying nullable."""
    null_count = sum(1 for item in any_of if item.get("nullable") is True)
    if nullable or null_count > 1:
        nullable = True
        any_of = [
            {key: value for key, value in item.items() if key != "nullable"}
            for item in any_of
        ]

    result: dict[str, Any] = any_of[0] if len(any_of) == 1 else {"anyOf": any_of}
    if nullable:
        result["nullable"] = True
    return result


def _enum_twin(
    item: dict[str, Any],
    merged: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find an already-merged entry that shares this item's enum type, if any.

    A *non-empty* enum is required on both sides, matching voluptuous-openapi's
    truthiness check (an empty enum, as ``In([None])`` produces, never merges).
    """
    if not item.get("enum"):
        return None
    for candidate in merged:
        if candidate.get("enum") and candidate.get("type") == item.get("type"):
            return candidate
    return None


def _oa_type(node: Any, version: str) -> dict[str, Any]:
    """Render a Python type as an OpenAPI Schema object."""
    if node in _OPENAPI_TYPES:
        return {"type": _OPENAPI_TYPES[node]}

    if isinstance(node, type):
        if node is dict:
            return dict(_OPEN_OBJECT)
        if node in (list, set, tuple):
            return {"type": "array", "items": _ensure_default({})}
        if issubclass(node, Enum):
            return _oa_enum([item.value for item in node])
        if node is _NONE_TYPE:
            return _oa_null(version)

    if node is object:
        return dict(_OPEN_OBJECT)
    return {}
