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
from probatio.markers import Optional, Required, Self, Undefined, resolve_key
from probatio.schema import ALLOW_EXTRA, REMOVE_EXTRA, Schema
from probatio.validators import (
    All,
    AsDate,
    AsDatetime,
    AsTime,
    Base64,
    Capitalize,
    Clamp,
    Coerce,
    Date,
    Datetime,
    Email,
    FqdnUrl,
    FromEpoch,
    FromPercentage,
    In,
    Length,
    Lower,
    Match,
    Maybe,
    MultipleOf,
    Percentage,
    Port,
    Range,
    Strip,
    Time,
    Title,
    Upper,
    Url,
)
from probatio.validators import Any as AnyValidator

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
        return _oa(schema, custom_serializer, openapi_version)
    except RecursionError as exc:
        message = (
            "schema is too deeply nested or references itself; use the Self "
            "marker for a recursive schema"
        )
        raise SchemaError(message) from exc


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
    if isinstance(node, Schema):
        if node.extra in (ALLOW_EXTRA, REMOVE_EXTRA):
            closed = False
        if node.extra == ALLOW_EXTRA:
            additional = True
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

        if isinstance(pkey, AnyValidator):
            props, group = _expand_any_key(
                pkey,
                pval,
                required=isinstance(marker, Required),
                wildcard=value is object,
            )
            properties.update(props)
            if group is not None:
                constraint_groups.append(group)
        elif isinstance(pkey, str):
            properties[pkey] = pval
        else:
            additional = _absorb_extra(pval, additional)

    return _assemble_object(
        properties, required, additional, constraint_groups, closed=closed
    )


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
    constraint_groups: list[list[str]],
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
        result["required"] = required
    if additional:
        # ``True`` (open) or a variable-key value schema.
        result["additionalProperties"] = additional
    elif closed:
        # A closed mapping rejects undeclared keys; an open (REMOVE_EXTRA) one is
        # left without the keyword, accepting extra keys the way it strips them.
        result["additionalProperties"] = False
    if constraint_groups:
        result["anyOf"] = [
            {"required": list(combination)}
            for combination in itertools.product(*constraint_groups)
        ]
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
    if isinstance(node, In):
        return _oa_enum(list(node.container))
    if node in _OPENAPI_FORMATS:
        return {"format": _OPENAPI_FORMATS[node]}

    if isinstance(node, Maybe):
        return _oa_any([None, node.validator], custom, version)
    if isinstance(node, AnyValidator):
        return _oa_any(list(node.validators), custom, version)

    return _oa_typed(node)


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
    """Render an enum (from In or an Enum type), extracting null members.

    Like voluptuous-openapi, an enum marks itself ``nullable`` regardless of the
    OpenAPI version (unlike ``Any``, which splits on version).
    """
    nullable = False
    cleaned: list[Any] = []
    for value in _ordered(values):
        if value is None or value is _NONE_TYPE:
            nullable = True
            continue
        # An enum member with no JSON form (a ``datetime``, an ``Enum``) is
        # rendered JSON-safe, so the emitted enum never crashes ``json.dumps``. A
        # member with no representation at all (``bytes``) drops the whole enum to
        # an open schema rather than leak an unserializable value.
        safe = _json_safe(value)
        if safe is _UNREPRESENTABLE:
            return {"nullable": True} if nullable else {}
        cleaned.append(safe)

    enum_type = _OPENAPI_TYPES.get(type(cleaned[0]), "string") if cleaned else "string"
    result: dict[str, Any] = {"type": enum_type, "enum": cleaned}
    if nullable:
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

    if len(validators) == 1:
        result = _oa(validators[0], custom, version)
        if nullable:
            result["nullable"] = True
        return result

    any_of, nested_nullable = _flatten_any(
        [_oa(validator, custom, version) for validator in validators],
    )
    nullable = nullable or nested_nullable

    if _OPEN_OBJECT in any_of:
        result = dict(_OPEN_OBJECT)
        if nullable:
            result["nullable"] = True
        return result
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
