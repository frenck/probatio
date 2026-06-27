"""Network validators: IP addresses, networks, hostnames, and ports.

The IP validators coerce to the standard library's ``ipaddress`` objects, since
that typed value is the point of using them over a regular expression. ``Hostname``
and ``Fqdn`` are format checks and pass the string through. They validate with
plain character checks, never a backtracking regular expression, so a crafted
input cannot hang them.
"""

from __future__ import annotations

import ipaddress
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


# CPython's ``ipaddress`` parsers are fragile on hostile input: besides the
# expected ValueError/TypeError, a crafted value can reach an IndexError (an empty
# tuple) or an AttributeError (``'NoneType' object has no attribute 'isascii'`` from
# the prefix parser). A safe validator may only raise ``Invalid``, so every parse
# failure is funnelled through this tuple. The wrapped call is a single stdlib
# function on the value, so this cannot mask a bug in probatio's own code.
_IP_PARSE_ERRORS = (ValueError, TypeError, IndexError, AttributeError)


class IPv4Address(_SafeValidator):
    """Validate an IPv4 address, returning an ``ipaddress.IPv4Address``."""

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> ipaddress.IPv4Address:
        """Return the parsed address, else raise IpInvalid."""
        try:
            return ipaddress.IPv4Address(_reject_bool(value))
        except _IP_PARSE_ERRORS as exc:
            raise IpInvalid(self.msg or "expected an IPv4 address") from exc


class IPv6Address(_SafeValidator):
    """Validate an IPv6 address, returning an ``ipaddress.IPv6Address``."""

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> ipaddress.IPv6Address:
        """Return the parsed address, else raise IpInvalid."""
        try:
            return ipaddress.IPv6Address(_reject_bool(value))
        except _IP_PARSE_ERRORS as exc:
            raise IpInvalid(self.msg or "expected an IPv6 address") from exc


class IPAddress(_SafeValidator):
    """Validate an IP address of either version (v4 or v6)."""

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(
        self,
        value: typing.Any,
    ) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
        """Return the parsed address (v4 or v6), else raise IpInvalid."""
        try:
            return ipaddress.ip_address(_reject_bool(value))
        except _IP_PARSE_ERRORS as exc:
            raise IpInvalid(self.msg or "expected an IP address") from exc


class IPNetwork(_SafeValidator):
    """Validate a CIDR network, returning an ``ipaddress`` network object.

    Host bits are allowed (``strict=False``), so ``192.0.2.5/24`` is accepted and
    normalized to its network, matching how configuration usually writes them.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(
        self,
        value: typing.Any,
    ) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
        """Return the parsed network, else raise IpInvalid."""
        try:
            return ipaddress.ip_network(_reject_bool(value), strict=False)
        except _IP_PARSE_ERRORS as exc:
            raise IpInvalid(self.msg or "expected a CIDR network") from exc


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
            raise HostnameInvalid(self.msg or "expected a hostname")
        host = value.removesuffix(".")
        if not host or len(host) > _MAX_HOSTNAME_LENGTH or not _check_labels(host):
            raise HostnameInvalid(self.msg or "expected a hostname")
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
            raise HostnameInvalid(self.msg or "expected a fully-qualified domain name")
        host = value.removesuffix(".")
        if (
            not host
            or len(host) > _MAX_HOSTNAME_LENGTH
            or "." not in host
            or not _check_labels(host)
        ):
            raise HostnameInvalid(self.msg or "expected a fully-qualified domain name")
        return value


class Port(_SafeValidator):
    """Validate a TCP/UDP port number (1 to 65535), returning it as an ``int``."""

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> int:
        """Return the port as an int if in range, else raise RangeInvalid."""
        if isinstance(value, float) and not value.is_integer():
            # A fractional float is not a port; reject it rather than silently
            # truncating ``8080.7`` to ``8080``.
            message = self.msg or "expected a port number between 1 and 65535"
            raise RangeInvalid(message)
        try:
            port = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            # ``int(float('inf'))`` raises OverflowError; reject it cleanly.
            message = self.msg or "expected a port number between 1 and 65535"
            raise RangeInvalid(message) from exc
        if not _MIN_PORT <= port <= _MAX_PORT:
            message = self.msg or "expected a port number between 1 and 65535"
            raise RangeInvalid(message)
        return port
