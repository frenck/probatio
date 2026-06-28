"""Identifier validators: UUID and MAC address.

Both coerce to a canonical form rather than just checking a pattern: ``UUID``
returns a ``uuid.UUID`` and ``MacAddress`` returns the normalized
colon-separated lowercase string, since that canonical value is the point.
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
    """Require a ULID string, returning it normalized to upper case.

    A ULID is 26 Crockford base32 characters. The value is validated and
    upper-cased; it is not parsed into a dedicated type (that needs a third-party
    library), so a plain string comes back.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> str:
        """Return the normalized ULID, else raise ValueInvalid."""
        if not isinstance(value, str):
            raise ValueInvalid(self.msg or "expected a ULID", code="ulid")
        candidate = value.upper()
        if len(candidate) != _ULID_LENGTH or not _ULID_CHARS.issuperset(candidate):
            raise ValueInvalid(self.msg or "expected a ULID", code="ulid")
        return candidate


class UUID(_SafeValidator):
    """Validate a UUID, returning a ``uuid.UUID``.

    Accepts any form ``uuid.UUID`` parses (hyphenated, bare hex, urn, braces) and
    an existing ``uuid.UUID``. With ``version`` set, the parsed UUID must be that
    version.
    """

    def __init__(self, msg: str | None = None, version: int | None = None) -> None:
        """Store an optional custom message and an optional version to require."""
        self.msg = msg
        self.version = version

    def __call__(self, value: typing.Any) -> uuid_module.UUID:
        """Return the parsed UUID, else raise UuidInvalid."""
        try:
            result = (
                value
                if isinstance(value, uuid_module.UUID)
                else uuid_module.UUID(str(value))
            )
        except (ValueError, TypeError) as exc:
            raise UuidInvalid(self.msg or "expected a UUID") from exc
        if self.version is not None and result.version != self.version:
            message = self.msg or f"expected a version {self.version} UUID"
            raise UuidInvalid(message)
        return result


class MacAddress(_SafeValidator):
    """Validate a MAC address, normalized to ``aa:bb:cc:dd:ee:ff`` by default.

    Accepts the common separators (colon, hyphen, dot) and bare hex. By default
    the result is canonicalized to lowercase, colon-separated form. Pass
    ``upper=True`` for uppercase, and ``separator=`` to change the separator (for
    example ``"-"``, or ``""`` for bare hex). Pass ``normalize=False`` to validate
    only and return the input unchanged; ``upper`` and ``separator`` then have no
    effect.
    """

    def __init__(
        self,
        normalize: bool = True,
        *,
        upper: bool = False,
        separator: str = ":",
        msg: str | None = None,
    ) -> None:
        """Store the normalization options and an optional message."""
        self.normalize = normalize
        self.upper = upper
        self.separator = separator
        self.msg = msg

    def __call__(self, value: typing.Any) -> str:
        """Return the MAC address, normalized unless ``normalize`` is False."""
        if not isinstance(value, str):
            raise MacAddressInvalid(self.msg or "expected a MAC address")
        cleaned = value.replace(":", "").replace("-", "").replace(".", "").lower()
        if len(cleaned) != _MAC_LENGTH or not _HEX_CHARS.issuperset(cleaned):
            raise MacAddressInvalid(self.msg or "expected a MAC address")
        if not self.normalize:
            return value
        octets = cleaned.upper() if self.upper else cleaned
        return self.separator.join(
            octets[index : index + 2] for index in range(0, _MAC_LENGTH, 2)
        )
