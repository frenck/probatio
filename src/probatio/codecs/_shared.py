"""Shared pieces for the schema codecs."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

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
# back to the default". Shared by ``to_field_list`` and ``to_openapi``.
UNSUPPORTED = _Unsupported()


# Returned from ``json_safe`` for a value with no JSON representation, so the
# caller can omit the offending keyword rather than emit an unserializable dict.
UNREPRESENTABLE = object()


@dataclass
class ExclusiveGroup:
    """The members of an ``Exclusive`` group and how an empty group is judged.

    Shared by the JSON Schema and OpenAPI codecs: an ``Exclusive`` group is
    version-independent (``oneOf``/``not`` exist on both), so both codecs must
    render it identically, and one accumulator here keeps them from drifting.
    """

    members: list[str] = field(default_factory=list)
    required: bool = False
    has_default: bool = False


def exclusive_constraint(group: ExclusiveGroup) -> dict[str, Any]:
    """Render one ``Exclusive`` group as at-most-one, or exactly-one when required.

    A required group with no default demands exactly one member (``oneOf`` over the
    per-member ``required``). Otherwise at most one member may appear: the negation
    of any two being present together. Shared so both codecs stay identical.
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


def merge_dependent_required(groups: Iterable[list[str]]) -> dict[str, list[str]]:
    """Merge multi-member all-or-none groups into one ``dependentRequired`` map.

    Each member requires every other member of its group. Group memberships are
    disjoint, so the merged map's connected components recover the original groups
    on decode. Shared so the JSON Schema and OpenAPI 3.1 encoders cannot drift.
    """
    dependent: dict[str, list[str]] = {}
    for members in groups:
        if len(members) > 1:
            for member in members:
                dependent[member] = [other for other in members if other != member]
    return dependent


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
