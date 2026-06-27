"""Shared pieces for the schema codecs."""

from __future__ import annotations

from probatio.validators import (
    ASCII,
    E164,
    IBAN,
    ULID,
    UUID,
    Alpha,
    Alphanumeric,
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
    NoWhitespace,
    PrintableASCII,
    Slug,
    StartsWith,
    TimeZone,
)


class _Unsupported:
    """Sentinel a custom serializer returns to defer to the default handling."""

    def __repr__(self) -> str:
        """Render clearly in debug output."""
        return "UNSUPPORTED"


# Returned from a ``custom_serializer`` to mean "I do not handle this node, fall
# back to the default". Shared by ``serialize`` and ``to_openapi``.
UNSUPPORTED = _Unsupported()

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
    TimeZone,
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
