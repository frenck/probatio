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

import re
from dataclasses import dataclass, field
from typing import Any

from probatio.codecs._regex_safety import is_catastrophic
from probatio.codecs._shared import FORMAT_BY_TYPE, STRING_TYPES
from probatio.error import ContainsInvalid, Invalid, SchemaError
from probatio.markers import Forbidden, Marker, Optional, Remove, Required, Undefined
from probatio.schema import ALLOW_EXTRA, Schema, recursion_guard
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
    Epoch,
    Equal,
    ExactSequence,
    FqdnUrl,
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
    Secret,
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
# identity to match against.
_BOOLEAN_FUNC = Boolean.__wrapped__

# The deepest a decoded JSON Schema may nest. Generous for any real schema (which
# rarely nests past a handful of levels), but low enough that even the most
# stack-hungry decode path (a typeless ``contains`` chain, which spends several
# frames per level) stays well under Python's recursion limit rather than leaking
# a RecursionError before this guard fires.
_MAX_SCHEMA_DEPTH = 100


def to_json_schema(schema: Any) -> dict[str, Any]:
    """Convert a schema (or ``Schema``) into a JSON Schema dictionary."""
    return _convert(schema, required_default=False, allow_extra=False)


def _convert(node: Any, *, required_default: bool, allow_extra: bool) -> dict[str, Any]:
    """Dispatch a schema node to the right JSON Schema renderer."""
    if isinstance(node, Schema):
        return _convert(
            node.schema,
            required_default=node.required,
            allow_extra=node.extra == ALLOW_EXTRA,
        )

    if isinstance(node, dict):
        return _convert_mapping(
            node,
            required_default=required_default,
            allow_extra=allow_extra,
        )

    if isinstance(node, list | tuple | set | frozenset):
        return _convert_sequence(node)

    return _convert_leaf(node)


def _child(node: Any) -> dict[str, Any]:
    """Convert a nested node with default (non-required, closed) settings."""
    return _convert(node, required_default=False, allow_extra=False)


def _convert_mapping(
    node: dict[Any, Any],
    *,
    required_default: bool,
    allow_extra: bool,
) -> dict[str, Any]:
    """Render a mapping schema as a JSON Schema object."""
    properties: dict[Any, Any] = {}
    required: list[Any] = []
    additional: Any = allow_extra
    for key, value in node.items():
        if isinstance(key, Remove):
            continue

        if isinstance(key, Forbidden):
            properties[key.schema] = False
            continue

        marker = key if isinstance(key, Marker) else None
        name = marker.schema if marker is not None else key
        if isinstance(name, type) or callable(name):
            additional = _child(value)
            continue

        properties[name] = _property(marker, value)
        if isinstance(marker, Required) or (
            not isinstance(marker, Optional) and required_default
        ):
            required.append(name)

    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional,
    }
    if required:
        result["required"] = required

    return result


def _property(marker: Marker | None, value: Any) -> dict[str, Any]:
    """Render one mapping value, attaching a description and default if present."""
    prop = _child(value)
    if marker is not None and marker.description:
        prop = {**prop, "description": marker.description}
    if isinstance(marker, Optional | Required) and not isinstance(
        marker.default,
        Undefined,
    ):
        prop = {**prop, "default": marker.default()}

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


def _convert_sequence(node: Any) -> dict[str, Any]:
    """Render a sequence/set schema as a JSON Schema array."""
    items = [_child(element) for element in _ordered(node)]

    result: dict[str, Any] = {"type": "array"}
    if len(items) == 1:
        result["items"] = items[0]
    elif items:
        result["items"] = {"anyOf": items}

    return result


def _convert_leaf(node: Any) -> dict[str, Any]:
    """Render a leaf node: a type, a literal, or a validator."""
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
        merged: dict[str, Any] = {}
        for validator in node.validators:
            merged.update(_child(validator))
        return _retarget_length(merged)

    return _convert_constraint(node)


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


def _convert_equality(node: Any) -> dict[str, Any] | None:
    """Render the equality/membership validators as enum/const/not, or None."""
    if isinstance(node, In):
        return {"enum": _ordered(node.container)}

    if isinstance(node, NotIn):
        return {"not": {"enum": _ordered(node.container)}}

    if isinstance(node, Equal):
        return {"const": node.target}

    if isinstance(node, Literal):
        return {"const": node.lit}

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
        return {"type": "string", "pattern": node.pattern.pattern}

    if isinstance(node, Maybe):
        return {"anyOf": [{"type": "null"}, _child(node.validator)]}

    temporal = _convert_temporal_node(node)
    if temporal is not None:
        return temporal

    # A Unix timestamp is an integer on the wire; the datetime is internal.
    if isinstance(node, Epoch):
        return {"type": "integer"}

    if isinstance(node, Unique):
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

    if isinstance(node, Percentage):
        return {"type": "number", "minimum": _PERCENT_MIN, "maximum": _PERCENT_MAX}

    if isinstance(node, MultipleOf):
        return {"multipleOf": node.factor}

    if isinstance(node, Base64):
        return {"type": "string", "contentEncoding": "base64"}

    # ``writeOnly`` is JSON Schema's marker for a secret (a password field).
    if isinstance(node, Secret):
        return {**_child(node.schema), "writeOnly": True}

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


def _convert_range(node: Range) -> dict[str, Any]:
    """Render a Range as JSON Schema minimum/maximum bounds."""
    result: dict[str, Any] = {}
    if node.min is not None:
        result["minimum" if node.min_included else "exclusiveMinimum"] = node.min
    if node.max is not None:
        result["maximum" if node.max_included else "exclusiveMaximum"] = node.max

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


# JSON Schema "format" values that map to a built probatio string validator.
# Email/Url are factories (like voluptuous), so they are called once here.
_FROM_FORMATS: dict[str, Any] = {
    "email": Email(),
    "uri": Url(),
    "url": Url(),
    "date-time": Datetime(),
    "date": Date(),
    "time": Time(),
    "ipv4": IPv4Address(),
    "ipv6": IPv6Address(),
    "uuid": UUID(),
    "hostname": Hostname(),
}
# JSON Schema scalar types that map to a fixed probatio fragment.
_SIMPLE_TYPES: dict[str, Any] = {"boolean": bool, "null": None}


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

    if node.get("writeOnly") is True:
        result = Secret(result)
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


def _from_const(value: Any) -> Any:
    """Build a const equality check.

    A scalar is returned as a literal (a ``Schema`` validates a literal by
    equality). A list or dict literal would instead be read as a structural
    sub-schema, so it is wrapped in ``Equal`` to keep const's equality semantics.
    """
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

        message = "value must not match the 'not' schema"
        raise Invalid(message)


def _from_enum(values: Any) -> In:
    """Build an In from a JSON Schema ``enum``, rejecting a non-array."""
    if not isinstance(values, list):
        message = f"JSON Schema 'enum' must be an array, got {type(values).__name__}"
        raise SchemaError(message)
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
    """Resolve a local JSON pointer (``#/a/b``, ``#/a/0``) against the document."""
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
    """Dispatch on the ``type`` keyword, defaulting to an accept-anything schema."""
    json_type = node.get("type")
    if isinstance(json_type, list):
        return _from_type_list(node, json_type, ctx)

    # Keep malformed ``type`` values from leaking as hashing or membership errors.
    if json_type is not None and not isinstance(json_type, str):
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
        base = int if json_type == "integer" else AnyValidator(int, float)
        return _from_number(node, base=base)

    # An unrecognized type keyword: ignore it and honor any constraint keywords on
    # their own, so the type does not swallow the rest of the schema. A node with
    # no constraint accepts any value.
    combined = _combine_constraints(node, ctx)
    return object if combined is None else combined


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


def _combine_constraints(node: dict[str, Any], ctx: _Decode) -> Any:
    """Combine a node's standalone constraint keywords into one validator, or None.

    With no ``type``, a JSON Schema still carries meaning through keywords like
    ``minimum``, ``minLength``, ``multipleOf``, ``uniqueItems``, and ``contains``.
    Each becomes its matching validator so the encoder's typeless output (a bare
    ``Range``, ``Length``, ``MultipleOf``, ``Unique``, or ``ContainsCount``) round
    trips. None means the node carries no recognized constraint.
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
    if node.get("uniqueItems") is True:
        constraints.append(Unique())
    if "contains" in node:
        constraints.append(_from_contains(node, ctx))

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
    if isinstance(additional, dict):
        mapping[str] = _from_node(additional, ctx)

    base = _object_base(mapping, additional)
    min_props = _item_count(node, "minProperties")
    max_props = _item_count(node, "maxProperties")
    if min_props is not None or max_props is not None:
        return All(base, Length(min=min_props, max=max_props))

    return base


def _object_base(mapping: dict[Any, Any], additional: Any) -> Any:
    """Pick the base object schema from the property map and additionalProperties.

    A declared property set is a closed contract (probatio's deliberate strict
    default). But ``{"type": "object"}`` with no declared properties and no
    explicit ``additionalProperties`` is "any object", not a closed empty one; an
    explicit ``additionalProperties: false`` keeps an empty object closed.
    """
    if additional is True:
        return Schema(mapping, extra=ALLOW_EXTRA)

    if not mapping and additional is None:
        return dict

    return mapping


def _from_key(name: str, subschema: Any, *, required: bool) -> Marker:
    """Build the Required/Optional marker for one object property."""
    marker_cls = Required if required else Optional
    description = subschema.get("description") if isinstance(subschema, dict) else None
    if isinstance(subschema, dict) and "default" in subschema:
        return marker_cls(name, default=subschema["default"], description=description)
    return marker_cls(name, description=description)


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
    round-trips an ``ExactSequence``. A bool ``items`` (``false`` forbids extra
    items, ``true`` allows any) carries no per-item schema, so it is treated as an
    unconstrained list rather than fed to the node decoder.
    """
    prefix = node.get("prefixItems")
    if prefix is not None:
        return _from_prefix_items(prefix, node, ctx)

    items = node.get("items")
    if isinstance(items, bool):
        items = None
    elif items is not None and not isinstance(items, dict):
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

    if items is None:
        # No item schema: any list. Length, uniqueItems, and contains still apply,
        # so a constrained array accepts any element ([object]) but must satisfy
        # them.
        if not bounded and not has_contains and not has_unique:
            return list
        sequence: Any = [object]
    elif isinstance(items, dict) and "anyOf" in items:
        sequence = [_from_node(sub, ctx) for sub in items["anyOf"]]
    else:
        sequence = [_from_node(items, ctx)]

    constraints: list[Any] = []
    if bounded:
        constraints.append(Length(min=min_items, max=max_items))
    if has_unique:
        constraints.append(Unique())
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
            message = "value is not a collection"
            raise ContainsInvalid(message) from exc

        count = 0
        for element in items:
            try:
                self._schema(element)
            except Invalid:
                continue
            count += 1

        if count < self._min:
            message = f"expected at least {self._min} matching item(s)"
            raise ContainsInvalid(message)
        if self._max is not None and count > self._max:
            message = f"expected at most {self._max} matching item(s)"
            raise ContainsInvalid(message)

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

    # Draft-04: ``exclusiveMinimum: true`` flips ``minimum`` to exclusive.
    if isinstance(raw_exclusive, bool):
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
