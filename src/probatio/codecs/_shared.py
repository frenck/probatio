"""Shared pieces for the schema codecs."""

from __future__ import annotations

import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from probatio.validators import (
    ASCII,
    E164,
    IBAN,
    ULID,
    UUID,
    Alpha,
    Alphanumeric,
    AsTimezone,
    ByteLength,
    CreditCard,
    DataURI,
    EndsWith,
    Fqdn,
    Hex,
    HexColor,
    Hostname,
    IPAddress,
    IPNetwork,
    IPv4Address,
    IPv6Address,
    IsRegex,
    MacAddress,
    NormalizeMacAddress,
    NoWhitespace,
    PrintableASCII,
    Slug,
    StartsWith,
    TimeZone,
    TimeZoneInfo,
)


class _Unsupported:
    """Sentinel a custom serializer returns to defer to the default handling."""

    def __repr__(self) -> str:
        """Render clearly in debug output."""
        return "UNSUPPORTED"


# Returned from a ``custom_serializer`` to mean "I do not handle this node, fall
# back to the default". Shared by ``serialize`` and ``to_openapi``.
UNSUPPORTED = _Unsupported()


# Returned from ``json_safe`` for a value with no JSON representation, so the
# caller can omit the offending keyword rather than emit an unserializable dict.
UNREPRESENTABLE = object()


def ordered_values(values: Any) -> list[Any]:
    """List a container's values, sorting a set so the emitted schema is stable.

    A list or tuple keeps the author's order. A set or frozenset has none, so its
    values are sorted by ``repr`` to keep codec output deterministic across runs
    (stable snapshots, no spurious schema diffs, no cache misses).
    """
    if isinstance(values, set | frozenset):
        return sorted(values, key=repr)
    return list(values)


def json_safe(value: Any) -> Any:  # noqa: PLR0911
    """Convert a value to a JSON-representable form, or ``UNREPRESENTABLE``.

    Both codecs must emit a document ``json.dumps`` accepts (an emitted ``const``,
    ``enum``, ``default``, or numeric bound holding a raw ``datetime``, ``Decimal``,
    ``Enum`` member, or ``bytes`` would otherwise crash the caller). Datetimes
    render ISO, a ``Decimal`` renders a float, an ``Enum`` member renders its
    value, and a tuple or set renders a list (JSON has no tuple, and a value on
    the wire arrives as a list anyway). Anything with no clean JSON form is
    reported unrepresentable so the caller can omit it.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Enum):
        return json_safe(value.value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, list | tuple | set | frozenset):
        converted = [json_safe(item) for item in ordered_values(value)]
        return UNREPRESENTABLE if UNREPRESENTABLE in converted else converted
    if isinstance(value, dict):
        items = {key: json_safe(item) for key, item in value.items()}
        if any(not isinstance(key, str) for key in items) or (
            UNREPRESENTABLE in items.values()
        ):
            return UNREPRESENTABLE
        return items
    return UNREPRESENTABLE


# How a network/identifier validator renders as a string, shared by the JSON
# Schema and OpenAPI codecs so the two cannot drift. ``FORMAT_BY_TYPE`` carries a
# standard ``format`` keyword; ``STRING_TYPES`` has no standard format, so it
# renders as a plain string.
FORMAT_BY_TYPE: dict[type, str] = {
    IPv4Address: "ipv4",
    IPv6Address: "ipv6",
    UUID: "uuid",
    Hostname: "hostname",
    Fqdn: "hostname",
}
STRING_TYPES = (
    IPAddress,
    IPNetwork,
    MacAddress,
    NormalizeMacAddress,
    TimeZone,
    TimeZoneInfo,
    AsTimezone,
    Slug,
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
    Hex,
    ULID,
    CreditCard,
    IBAN,
    DataURI,
    E164,
)
