"""Network validators: IP addresses, networks, hostnames, and ports.

Every validator here checks its value and returns it unchanged. The IP validators
confirm the value parses as an address or network (using the standard library's
``ipaddress`` parsers), and hand the value back as given; reach for
``Coerce(ipaddress.IPv4Address)`` (and the like) when you want the parsed object.
``Hostname`` and ``Fqdn`` are format checks and pass the string through. They
validate with plain character checks, never a backtracking regular expression, so a
crafted input cannot hang them.
"""

from __future__ import annotations

import ipaddress
import re
import typing

from probatio.error import HostnameInvalid, IpInvalid, RangeInvalid
from probatio.validators._base import _SafeValidator

# The characters allowed in a hostname label (RFC 1123): ASCII letters, digits,
# and the hyphen. A frozenset membership test is linear, so no pattern can blow up.
_LABEL_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-",
)
_MAX_HOSTNAME_LENGTH = 253
_MAX_LABEL_LENGTH = 63
_MIN_PORT = 1
_MAX_PORT = 65535


def _reject_bool(value: typing.Any) -> typing.Any:
    """Raise so a bool is not coerced to an address (``ipaddress`` accepts ints)."""
    if isinstance(value, bool):
        message = "a boolean is not an IP address"
        raise TypeError(message)
    return value


# The string grammar ``ipaddress.IPv4Address`` accepts: four dot-separated octets,
# each 0-255 in ASCII digits with no leading zero. Every alternative is bounded and
# unambiguous, so the pattern cannot backtrack pathologically on hostile input.
_IPV4_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])"
_IPV4_PATTERN = re.compile(rf"{_IPV4_OCTET}(?:\.{_IPV4_OCTET}){{3}}")

# CPython's ``ipaddress`` parsers are fragile on hostile input: besides the
# expected ValueError/TypeError, a crafted value can reach an IndexError (an empty
# tuple) or an AttributeError (``'NoneType' object has no attribute 'isascii'`` from
# the prefix parser). A safe validator may only raise ``Invalid``, so every parse
# failure is funnelled through this tuple. The wrapped call is a single stdlib
# function on the value, so this cannot mask a bug in probatio's own code.
_IP_PARSE_ERRORS = (ValueError, TypeError, IndexError, AttributeError)


class IPv4Address(_SafeValidator):
    """Validate an IPv4 address, returning the value unchanged.

    Checks the value parses as an IPv4 address; use ``Coerce(ipaddress.IPv4Address)``
    when you want the parsed ``ipaddress.IPv4Address`` object instead.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it parses as an IPv4 address, else raise IpInvalid."""
        if type(value) is str:
            # The common case, matched directly: constructing an
            # ``ipaddress.IPv4Address`` costs several times the regex match.
            if _IPV4_PATTERN.fullmatch(value) is None:
                raise IpInvalid(self.msg, translation_key="expected_ipv4")
            return value
        # Everything else (int, packed bytes, address objects, str subclasses)
        # keeps the parser's exact acceptance behavior.
        try:
            ipaddress.IPv4Address(_reject_bool(value))
        except _IP_PARSE_ERRORS as exc:
            raise IpInvalid(self.msg, translation_key="expected_ipv4") from exc
        return value


class IPv6Address(_SafeValidator):
    """Validate an IPv6 address, returning the value unchanged.

    Checks the value parses as an IPv6 address; use ``Coerce(ipaddress.IPv6Address)``
    when you want the parsed ``ipaddress.IPv6Address`` object instead.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it parses as an IPv6 address, else raise IpInvalid."""
        try:
            ipaddress.IPv6Address(_reject_bool(value))
        except _IP_PARSE_ERRORS as exc:
            raise IpInvalid(self.msg, translation_key="expected_ipv6") from exc
        return value


class IPAddress(_SafeValidator):
    """Validate an IP address of either version (v4 or v6), returning it unchanged.

    Use ``Coerce(ipaddress.ip_address)`` when you want the parsed
    ``ipaddress.IPv4Address``/``IPv6Address`` object instead.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it parses as an IP address, else raise IpInvalid."""
        try:
            ipaddress.ip_address(_reject_bool(value))
        except _IP_PARSE_ERRORS as exc:
            raise IpInvalid(self.msg, translation_key="expected_ip") from exc
        return value


class IPNetwork(_SafeValidator):
    """Validate a CIDR network, returning the value unchanged.

    Host bits are allowed (``strict=False``), so ``192.0.2.5/24`` is accepted. The
    value is returned as given, not normalized to its network; use
    ``Coerce(lambda v: ipaddress.ip_network(v, strict=False))`` when you want the
    parsed network object.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it parses as a CIDR network, else raise IpInvalid."""
        try:
            ipaddress.ip_network(_reject_bool(value), strict=False)
        except _IP_PARSE_ERRORS as exc:
            raise IpInvalid(self.msg, translation_key="expected_cidr") from exc
        return value


def _check_labels(host: str) -> bool:
    """Return whether every dot-separated label is a valid hostname label."""
    for label in host.split("."):
        if not label or len(label) > _MAX_LABEL_LENGTH:
            return False
        if label[0] == "-" or label[-1] == "-":
            return False
        if not _LABEL_CHARS.issuperset(label):
            return False
    return True


class Hostname(_SafeValidator):
    """Validate a hostname (RFC 1123), returning the string unchanged.

    Each dot-separated label is 1 to 63 characters of ASCII letters, digits, and
    hyphens, and may not start or end with a hyphen. A single trailing dot (the
    root label) is allowed. A single label like ``localhost`` is valid; ``Fqdn``
    is the variant that requires a dotted, fully-qualified name.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> str:
        """Return the value if it is a valid hostname, else raise HostnameInvalid."""
        if not isinstance(value, str):
            raise HostnameInvalid(self.msg, translation_key="expected_hostname")

        host = value.removesuffix(".")
        if not host or len(host) > _MAX_HOSTNAME_LENGTH or not _check_labels(host):
            raise HostnameInvalid(self.msg, translation_key="expected_hostname")

        return value


class Fqdn(_SafeValidator):
    """Validate a fully-qualified domain name (a hostname with at least two labels).

    Same label rules as ``Hostname``, but the name must be dotted (``host.example``
    rather than a bare ``host``).
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> str:
        """Return the value if it is a valid FQDN, else raise HostnameInvalid."""
        if not isinstance(value, str):
            raise HostnameInvalid(self.msg, translation_key="expected_fqdn")

        host = value.removesuffix(".")
        if (
            not host
            or len(host) > _MAX_HOSTNAME_LENGTH
            or "." not in host
            or not _check_labels(host)
        ):
            raise HostnameInvalid(self.msg, translation_key="expected_fqdn")

        return value


class Port(_SafeValidator):
    """Validate a TCP/UDP port number (1 to 65535), returning it as an ``int``."""

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> int:
        """Return the port as an int if in range, else raise RangeInvalid."""
        # ``bool`` is an ``int`` subclass, but true and false are not port numbers.
        if isinstance(value, bool):
            raise RangeInvalid(self.msg, translation_key="expected_port")

        # Do not quietly turn 8080.7 into 8080.
        if isinstance(value, float) and not value.is_integer():
            raise RangeInvalid(self.msg, translation_key="expected_port")

        try:
            port = int(value)
        except Exception as exc:
            # ``int(float('inf'))`` raises OverflowError, and a value's ``__int__``
            # or ``__index__`` is user code that may raise anything; reject cleanly.
            raise RangeInvalid(self.msg, translation_key="expected_port") from exc

        if not _MIN_PORT <= port <= _MAX_PORT:
            raise RangeInvalid(self.msg, translation_key="expected_port")

        return port
