"""Field-list codec: ``serialize`` (the voluptuous-serialize shape).

``serialize`` renders a mapping as the field-list shape voluptuous-serialize
produces (what config-flow frontends and LLM tool exporters consume), so those
consumers work on probatio schemas. It takes the same ``custom_serializer`` hook,
which returns a dict to override a node or ``UNSUPPORTED`` to defer.

The format is output-only: voluptuous-serialize has no inverse, so neither does
this codec.
"""

from __future__ import annotations

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
    Clamp,
    Coerce,
    CreditCard,
    DataURI,
    Datetime,
    Duration,
    EndsWith,
    EnsureList,
    Epoch,
    Fqdn,
    Hex,
    HexColor,
    Hostname,
    In,
    IPAddress,
    IPNetwork,
    IPv4Address,
    IPv6Address,
    IsRegex,
    Length,
    MacAddress,
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
    TimeZone,
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


def serialize(schema: Any, *, custom_serializer: Any = None) -> Any:
    """Render a schema as the field-list shape voluptuous-serialize produces.

    A mapping becomes a list of field dicts (``name``, ``type``, ``required``,
    and so on); any other schema becomes a single value dict. ``custom_serializer``
    is called first for each node and may return a dict to override the default,
    or ``UNSUPPORTED`` to defer.
    """
    if isinstance(schema, Schema):
        schema = schema.schema
    return _serialize_node(schema, custom_serializer)


def _serialize_node(node: Any, custom: Any) -> Any:
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
    if marker is not None and marker.description:
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
        return {"type": "select", "options": [(item, item) for item in node.container]}
    if isinstance(node, AnyValidator):
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
        return {"type": name} if name is not None else {}
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
    if isinstance(node, MultipleOf | Duration | EnsureList | NonEmpty | Sorted):
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
