"""Format validators that check structure or a checksum, no extra dependency.

``CreditCard`` (Luhn), ``IBAN`` (mod-97), ``DataURI`` (RFC 2397), and ``E164``
(international phone format). Each validates and returns the value unchanged; none
of them reach a network or a database, so they check shape and checksums, not
whether the thing actually exists.
"""

from __future__ import annotations

import base64
import typing

from probatio.error import ValueInvalid
from probatio.validators._base import _SafeValidator

_DIGITS = frozenset("0123456789")
_LETTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_IBAN_CHARS = _DIGITS | _LETTERS
_NONZERO = frozenset("123456789")
_CARD_MIN = 12
_CARD_MAX = 19
_IBAN_MIN = 15
_IBAN_MAX = 34
_E164_MAX = 15


def _luhn_ok(digits: str) -> bool:
    """Whether a digit string satisfies the Luhn checksum (mod-10)."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = ord(char) - ord("0")
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


class CreditCard(_SafeValidator):
    """Require a credit card number that passes the Luhn checksum.

    Accepts a digit string, optionally grouped with spaces or hyphens. The 12 to
    19 digits (the ISO/IEC 7812 range) must pass the Luhn check. The value is
    returned unchanged; this is a checksum, not a check that the card exists.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is a Luhn-valid card number, else raise."""
        if not isinstance(value, str):
            raise ValueInvalid(
                self.msg or "expected a credit card number", code="credit_card"
            )
        digits = value.replace(" ", "").replace("-", "")
        if (
            not _DIGITS.issuperset(digits)
            or not _CARD_MIN <= len(digits) <= _CARD_MAX
            or not _luhn_ok(digits)
        ):
            raise ValueInvalid(
                self.msg or "invalid credit card number", code="credit_card"
            )
        return value


def _valid_iban(compact: str) -> bool:
    """Whether a space-free, upper-cased IBAN passes ISO 13616 structure + mod-97."""
    if not _IBAN_MIN <= len(compact) <= _IBAN_MAX or not _IBAN_CHARS.issuperset(
        compact
    ):
        return False
    if not (
        compact[0] in _LETTERS
        and compact[1] in _LETTERS
        and compact[2] in _DIGITS
        and compact[3] in _DIGITS
    ):
        return False
    # Move the first four characters to the end, turn letters into numbers
    # (A=10 .. Z=35), and check the resulting integer is 1 modulo 97.
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(int(char, 36)) for char in rearranged)
    return int(numeric) % 97 == 1


class IBAN(_SafeValidator):
    """Require an IBAN that passes the ISO 13616 mod-97 checksum.

    Accepts an IBAN, optionally grouped with spaces. The structure (two letters,
    two check digits, then alphanumerics) and the mod-97 checksum are validated;
    the per-country length is not. The value is returned unchanged.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is a checksum-valid IBAN, else raise."""
        if not isinstance(value, str):
            raise ValueInvalid(self.msg or "expected an IBAN", code="iban")
        if not _valid_iban(value.replace(" ", "").upper()):
            raise ValueInvalid(self.msg or "invalid IBAN", code="iban")
        return value


class DataURI(_SafeValidator):
    """Require an RFC 2397 data URI (``data:[<mediatype>][;base64],<data>``).

    The ``data:`` scheme, the comma between the metadata and the data, a
    ``type/subtype`` media type when one is given, and a valid Base64 payload when
    ``;base64`` is declared are all checked. The value is returned unchanged.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is a well-formed data URI, else raise."""
        if not isinstance(value, str):
            raise ValueInvalid(self.msg or "expected a data URI", code="data_uri")
        header, separator, data = value.partition(",")
        if not header.startswith("data:") or not separator:
            raise ValueInvalid(self.msg or "invalid data URI", code="data_uri")
        params = header[len("data:") :].split(";")
        media_type = params[0]
        if media_type and "/" not in media_type:
            raise ValueInvalid(self.msg or "invalid data URI", code="data_uri")
        if "base64" in params[1:]:
            try:
                base64.b64decode(data, validate=True)
            except ValueError as exc:
                raise ValueInvalid(
                    self.msg or "invalid data URI", code="data_uri"
                ) from exc
        return value


class E164(_SafeValidator):
    """Require a phone number in international E.164 format.

    A leading ``+``, a first digit 1 to 9, then up to 14 more digits (15 digits
    total at most). This is a format check, not a guarantee the number is assigned
    or dialable, which needs a phone-number database. The value is returned
    unchanged.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is a valid E.164 number, else raise."""
        if not isinstance(value, str):
            raise ValueInvalid(self.msg or "expected a phone number", code="e164")
        digits = value[1:]
        if (
            not value.startswith("+")
            or not 2 <= len(digits) <= _E164_MAX
            or digits[0] not in _NONZERO
            or not _DIGITS.issuperset(digits)
        ):
            raise ValueInvalid(self.msg or "invalid phone number", code="e164")
        return value
