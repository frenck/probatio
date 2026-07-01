"""Identifier validators: UUID, ULID, and MAC address.

Every validator here checks its value and returns it unchanged (``UUID`` accepts the
forms ``uuid.UUID`` parses, ``ULID`` a Crockford base32 string, ``MacAddress`` the
common MAC forms). Use ``Coerce(uuid.UUID)`` for the parsed ``uuid.UUID`` object,
``NormalizeMacAddress`` for a canonical MAC string, and ``Upper``/``Lower`` to fold a
ULID's or any string's case.
"""

from __future__ import annotations

import typing
import uuid as uuid_module

from probatio.error import MacAddressInvalid, UuidInvalid, ValueInvalid
from probatio.validators._base import _SafeValidator

_HEX_CHARS = frozenset("0123456789abcdef")
_MAC_LENGTH = 12
# Crockford base32, the ULID alphabet (excludes I, L, O, U).
_ULID_CHARS = frozenset("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
_ULID_LENGTH = 26


class ULID(_SafeValidator):
    """Require a ULID string, returning it unchanged.

    A ULID is 26 Crockford base32 characters, case-insensitive. The value is
    validated and returned as given; use ``Upper`` to fold it to the canonical upper
    case. It is not parsed into a dedicated type (that needs a third-party library).
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is a valid ULID, else raise ValueInvalid."""
        if not isinstance(value, str):
            raise ValueInvalid(self.msg or "expected a ULID", code="ulid")

        if len(value) != _ULID_LENGTH or not _ULID_CHARS.issuperset(value.upper()):
            raise ValueInvalid(self.msg or "expected a ULID", code="ulid")

        return value


class UUID(_SafeValidator):
    """Validate a UUID, returning the value unchanged.

    Accepts any form ``uuid.UUID`` parses (hyphenated, bare hex, urn, braces) and an
    existing ``uuid.UUID``. With ``version`` set, the value must be that version. The
    value is returned as given; use ``Coerce(uuid.UUID)`` for the parsed ``uuid.UUID``
    object instead.
    """

    def __init__(self, msg: str | None = None, version: int | None = None) -> None:
        """Store an optional custom message and an optional version to require."""
        self.msg = msg
        self.version = version

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is a valid UUID, else raise UuidInvalid."""
        try:
            parsed = (
                value
                if isinstance(value, uuid_module.UUID)
                else uuid_module.UUID(str(value))
            )
        except (ValueError, TypeError) as exc:
            raise UuidInvalid(self.msg or "expected a UUID") from exc

        if self.version is not None and parsed.version != self.version:
            message = self.msg or f"expected a version {self.version} UUID"
            raise UuidInvalid(message)

        return value


def _clean_mac(value: typing.Any, msg: str | None) -> str:
    """Validate a MAC address, returning the bare lowercase hex, else raise."""
    if not isinstance(value, str):
        raise MacAddressInvalid(msg or "expected a MAC address")

    cleaned = value.replace(":", "").replace("-", "").replace(".", "").lower()
    if len(cleaned) != _MAC_LENGTH or not _HEX_CHARS.issuperset(cleaned):
        raise MacAddressInvalid(msg or "expected a MAC address")
    return cleaned


class MacAddress(_SafeValidator):
    """Validate a MAC address, returning the value unchanged.

    Accepts the common separators (colon, hyphen, dot) and bare hex. Use
    ``NormalizeMacAddress`` when you want the canonical form.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is a valid MAC address, else raise MacAddressInvalid."""
        _clean_mac(value, self.msg)
        return value


class NormalizeMacAddress(_SafeValidator):
    """Validate a MAC address and return it in canonical form.

    Accepts the common separators (colon, hyphen, dot) and bare hex, and returns the
    lowercase, colon-separated form by default. Pass ``upper=True`` for uppercase, and
    ``separator=`` to change the separator (for example ``"-"``, or ``""`` for bare
    hex).
    """

    def __init__(
        self,
        *,
        upper: bool = False,
        separator: str = ":",
        msg: str | None = None,
    ) -> None:
        """Store the normalization options and an optional message."""
        self.upper = upper
        self.separator = separator
        self.msg = msg

    def __call__(self, value: typing.Any) -> str:
        """Return the MAC address in canonical form, else raise MacAddressInvalid."""
        cleaned = _clean_mac(value, self.msg)
        octets = cleaned.upper() if self.upper else cleaned
        return self.separator.join(
            octets[index : index + 2] for index in range(0, _MAC_LENGTH, 2)
        )
