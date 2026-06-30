"""Field-list codec: ``serialize`` (the voluptuous-serialize shape).

``serialize`` renders a mapping as the field-list shape voluptuous-serialize
produces (what config-flow frontends and LLM tool exporters consume), so those
consumers work on probatio schemas. It takes the same ``custom_serializer`` hook,
which returns a dict to override a node or ``UNSUPPORTED`` to defer.

The format is output-only: voluptuous-serialize has no inverse, so neither does
this codec.
"""

from __future__ import annotations

import enum
from collections.abc import Hashable, Mapping
from typing import Any, cast

from probatio.codecs._shared import UNSUPPORTED
from probatio.markers import Forbidden, Marker, Optional, Required, Undefined
from probatio.schema import Schema
from probatio.validators import (
    ASCII,
    E164,
    IBAN,
    ULID,
    UUID,
    All,
    Alpha,
    Alphanumeric,
    AsDate,
    AsDatetime,
    AsTime,
    Base64,
    ByteLength,
    Capitalize,
    Clamp,
    Coerce,
    CreditCard,
    DataURI,
    Datetime,
    Duration,
    Email,
    EndsWith,
    EnsureList,
    Epoch,
    Fqdn,
    FqdnUrl,
    Hex,
    HexColor,
    HexInt,
    Hostname,
    In,
    IPAddress,
    IPNetwork,
    IPv4Address,
    IPv6Address,
    IsRegex,
    Length,
    Lower,
    MacAddress,
    Maybe,
    MultipleOf,
    NonEmpty,
    NoWhitespace,
    Percentage,
    Port,
    PrintableASCII,
    Range,
    Secret,
    Slug,
    Sorted,
    StartsWith,
    Strip,
    TimeZone,
    Title,
    Upper,
    Url,
)
from probatio.validators import Any as AnyValidator

# probatio-only validators that render as a plain string field for a frontend.
_SERIALIZE_STRING_TYPES = (
    IPv4Address,
    IPv6Address,
    IPAddress,
    IPNetwork,
    MacAddress,
    UUID,
    Hostname,
    Fqdn,
    Slug,
    TimeZone,
    Alpha,
    Alphanumeric,
    ASCII,
    PrintableASCII,
    NoWhitespace,
    StartsWith,
    EndsWith,
    ByteLength,
    HexColor,
    IsRegex,
    Base64,
    Hex,
    ULID,
    CreditCard,
    IBAN,
    DataURI,
    E164,
)
_SERIALIZE_PORT_MIN = 1
_SERIALIZE_PORT_MAX = 65535
_SERIALIZE_PERCENT_MIN = 0
_SERIALIZE_PERCENT_MAX = 100

# The type names voluptuous-serialize emits (note: float -> "float", not
# "number" as in JSON Schema).
_SERIALIZE_TYPES: dict[type, str] = {
    bool: "boolean",
    int: "integer",
    float: "float",
    str: "string",
}

# The format validators, rendered as a ``format`` field by voluptuous-serialize.
# These are the bare functions a voluptuous schema uses (``vol.Email``), so they
# arrive uncalled under the shim.
_SERIALIZE_FORMATS: dict[Any, str] = {Email: "email", Url: "url", FqdnUrl: "fqdnurl"}

# The string transforms, rendered as a boolean flag (``{"lower": True}``).
_SERIALIZE_TRANSFORMS: dict[Any, str] = {
    Lower: "lower",
    Upper: "upper",
    Capitalize: "capitalize",
    Title: "title",
    Strip: "strip",
}


def _enum_select(enum_cls: type[enum.Enum]) -> dict[str, Any]:
    """Render an Enum class as a select of its member values, like the oracle."""
    return {
        "type": "select",
        "options": [(member.value, member.value) for member in enum_cls],
    }


def _serialize_callable(node: Any) -> dict[str, Any] | None:
    """Render a bare format validator or string transform, or None if neither."""
    if not isinstance(node, Hashable):
        # The format/transform tables are keyed by identity, so an unhashable
        # callable cannot be one. Bail before the dict lookup hashes it, leaving
        # it to fall through to the ValueError like the oracle does.
        return None
    fmt = _SERIALIZE_FORMATS.get(node)
    if fmt is not None:
        return {"format": fmt}
    flag = _SERIALIZE_TRANSFORMS.get(node)
    if flag is not None:
        return {flag: True}
    return None


def _allow_none(field: dict[str, Any]) -> dict[str, Any]:
    """Mark a serialized value field as nullable, matching ``Maybe``'s oracle output."""
    return {**field, "allow_none": True}


# A serialized schema is a single value field, or the field list of a mapping.
_Serialized = dict[str, Any] | list[dict[str, Any]]


def serialize(schema: Any, *, custom_serializer: Any = None) -> _Serialized:
    """Render a schema as the field-list shape voluptuous-serialize produces.

    A mapping becomes a list of field dicts (``name``, ``type``, ``required``,
    and so on); any other schema becomes a single value dict. ``custom_serializer``
    is called first for each node and may return a dict to override the default,
    or ``UNSUPPORTED`` to defer.
    """
    if isinstance(schema, Schema):
        schema = schema.schema
    return _serialize_node(schema, custom_serializer)


def _serialize_node(node: Any, custom: Any) -> _Serialized:
    """Render a mapping as a field list, or any other node as a value dict."""
    if isinstance(node, dict):
        # A Forbidden key is a prohibition, not an input field, so it is left out
        # of the field list a frontend would render.
        return [
            _serialize_field(key, value, custom)
            for key, value in node.items()
            if not isinstance(key, Forbidden)
        ]
    return _serialize_value(node, custom)


def _serialize_field(key: Any, value: Any, custom: Any) -> dict[str, Any]:
    """Render one mapping key/value as a field dict."""
    marker = key if isinstance(key, Marker) else None
    field = dict(_serialize_value(value, custom))
    field["name"] = marker.schema if marker is not None else key
    if marker is not None and marker.description is not None:
        field["description"] = marker.description
    field["required"] = isinstance(marker, Required)
    if isinstance(marker, Optional):
        field["optional"] = True
    if isinstance(marker, Optional | Required) and not isinstance(
        marker.default,
        Undefined,
    ):
        field["default"] = marker.default()
    return field


def _serialize_value(node: Any, custom: Any) -> dict[str, Any]:
    """Render a single value schema as a value dict."""
    if custom is not None:
        result = custom(node)
        if result is not UNSUPPORTED:
            return cast("dict[str, Any]", result)
    if isinstance(node, type):
        name = _SERIALIZE_TYPES.get(node)
        if name is not None:
            return {"type": name}
        if issubclass(node, enum.Enum):
            return _enum_select(node)
    if callable(node):
        # The format validators and string transforms are bare functions, so they
        # are matched by identity before the validator dispatch below.
        func_field = _serialize_callable(node)
        if func_field is not None:
            return func_field
    converted = _serialize_validator(node, custom)
    if converted is not None:
        return converted
    if isinstance(node, str | int | float):
        # A literal mapping value (``{"mode": 5}``) is a constant the value must
        # equal. voluptuous-serialize renders it as a ``constant`` field; ``bool``
        # is an ``int`` subclass, so it is covered. ``None`` is not a constant
        # there, so it falls through to the error, matching the oracle.
        return {"type": "constant", "value": node}
    message = f"unable to serialize schema: {node!r}"
    raise ValueError(message)


def _serialize_validator(node: Any, custom: Any) -> dict[str, Any] | None:  # noqa: PLR0911
    """Render a known validator, or None if it is not recognized."""
    if isinstance(node, In):
        # A mapping container carries a label per value, so its items become the
        # (value, label) options; a list/tuple uses each item as its own label.
        container = node.container
        options = (
            list(container.items())
            if isinstance(container, Mapping)
            else [(item, item) for item in container]
        )
        return {"type": "select", "options": options}
    if isinstance(node, Maybe):
        return _allow_none(_serialize_value(node.validator, custom))
    if isinstance(node, AnyValidator):
        # ``Maybe(X)`` compiles to ``Any(None, X)``: a two-member Any with one None
        # branch is the nullable form, so strip the None and mark the remaining
        # member allow_none. voluptuous-serialize only recognized None first;
        # ``Any(X, None)`` is the same nullable shape, so handle either position.
        non_none = [member for member in node.validators if member is not None]
        if len(node.validators) == 2 and len(non_none) == 1:
            return _allow_none(_serialize_value(non_none[0], custom))
        for validator in node.validators:
            converted = _serialize_value(validator, custom)
            if converted:
                return converted
        return {}
    if isinstance(node, All):
        merged: dict[str, Any] = {}
        for validator in node.validators:
            merged.update(_serialize_value(validator, custom))
        return merged
    if isinstance(node, Coerce):
        name = _SERIALIZE_TYPES.get(node.type)
        if name is not None:
            return {"type": name}
        if isinstance(node.type, type) and issubclass(node.type, enum.Enum):
            return _enum_select(node.type)
        # An unmapped coerce target (a function, a custom type) carries no field
        # hint, so it serializes to an open dict rather than raising.
        return {}
    typed = _serialize_typed(node, custom)
    if typed is not None:
        return typed
    return _serialize_constraint(node)


def _serialize_typed(node: Any, custom: Any) -> dict[str, Any] | None:
    """Render the probatio-only validators for a frontend, or None if not one.

    Returns ``{}`` (no field hints, but not an error) for the validators that have
    no voluptuous-serialize equivalent, so a schema using them still serializes
    instead of raising.
    """
    if isinstance(node, _SERIALIZE_STRING_TYPES):
        return {"type": "string"}
    if isinstance(node, Port):
        return {
            "type": "integer",
            "valueMin": _SERIALIZE_PORT_MIN,
            "valueMax": _SERIALIZE_PORT_MAX,
        }
    if isinstance(node, Percentage):
        return {
            "type": "float",
            "valueMin": _SERIALIZE_PERCENT_MIN,
            "valueMax": _SERIALIZE_PERCENT_MAX,
        }
    if isinstance(node, Secret):
        return _serialize_value(node.schema, custom)
    if isinstance(
        node, MultipleOf | Duration | EnsureList | NonEmpty | Sorted | HexInt
    ):
        return {}
    return None


def _serialize_constraint(node: Any) -> dict[str, Any] | None:
    """Render Range/Clamp/Length/Datetime, or None if not recognized."""
    if isinstance(node, Range | Clamp):
        bounds: dict[str, Any] = {}
        if node.min is not None:
            bounds["valueMin"] = node.min
        if node.max is not None:
            bounds["valueMax"] = node.max
        return bounds
    if isinstance(node, Length):
        bounds = {}
        if node.min is not None:
            bounds["lengthMin"] = node.min
        if node.max is not None:
            bounds["lengthMax"] = node.max
        return bounds
    if isinstance(node, Datetime):
        return {"type": "datetime", "format": node.format}
    if isinstance(node, AsDatetime | AsDate | AsTime):
        # Same field shape as Datetime; the ISO default carries no strptime
        # format, so only attach one when the parser was given an explicit format.
        field: dict[str, Any] = {"type": "datetime"}
        if node.format is not None:
            field["format"] = node.format
        return field
    if isinstance(node, Epoch):
        # A Unix timestamp arrives as an integer; the datetime is internal.
        return {"type": "integer"}
    return None
