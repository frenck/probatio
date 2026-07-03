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
# Grouping characters stripped from a phone number when normalizing.
_E164_SEPARATORS = str.maketrans("", "", " -.()")


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
    19 digits (the ISO/IEC 7812 range) must pass the Luhn check. With ``normalize``
    (the default) the grouped separators are stripped and the bare digit string is
    returned; ``normalize=False`` returns the value unchanged. This is a checksum,
    not a check that the card exists.
    """

    def __init__(self, normalize: bool = True, *, msg: str | None = None) -> None:
        """Store the normalization flag and an optional custom message."""
        self.normalize = normalize
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the card number (bare digits when normalizing), else raise."""
        if not isinstance(value, str):
            raise ValueInvalid(
                self.msg,
                code="credit_card",
                translation_key="expected_credit_card_number",
            )

        digits = value.replace(" ", "").replace("-", "")
        if (
            not _DIGITS.issuperset(digits)
            or not _CARD_MIN <= len(digits) <= _CARD_MAX
            or not _luhn_ok(digits)
        ):
            raise ValueInvalid(
                self.msg,
                code="credit_card",
                translation_key="invalid_credit_card_number",
            )
        return digits if self.normalize else value


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
    the per-country length is not. With ``normalize`` (the default) the result is
    the compact, upper-cased form (spaces stripped); ``normalize=False`` returns
    the value unchanged.
    """

    def __init__(self, normalize: bool = True, *, msg: str | None = None) -> None:
        """Store the normalization flag and an optional custom message."""
        self.normalize = normalize
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the IBAN (compact and upper-cased when normalizing), else raise."""
        if not isinstance(value, str):
            raise ValueInvalid(self.msg, code="iban", translation_key="expected_iban")

        compact = value.replace(" ", "").upper()
        if not _valid_iban(compact):
            raise ValueInvalid(self.msg, code="iban", translation_key="invalid_iban")
        return compact if self.normalize else value


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
            raise ValueInvalid(
                self.msg, code="data_uri", translation_key="expected_data_uri"
            )

        header, separator, data = value.partition(",")
        if not header.startswith("data:") or not separator:
            raise ValueInvalid(
                self.msg, code="data_uri", translation_key="invalid_data_uri"
            )

        params = header[len("data:") :].split(";")
        media_type = params[0]
        if media_type and "/" not in media_type:
            raise ValueInvalid(
                self.msg, code="data_uri", translation_key="invalid_data_uri"
            )

        if "base64" in params[1:]:
            try:
                base64.b64decode(data, validate=True)
            except ValueError as exc:
                raise ValueInvalid(
                    self.msg, code="data_uri", translation_key="invalid_data_uri"
                ) from exc

        return value


class E164(_SafeValidator):
    """Require a phone number in international E.164 format.

    A leading ``+``, a first digit 1 to 9, then 1 to 14 more digits (2 to 15 digits
    total). This is a format check, not a guarantee the number is assigned
    or dialable, which needs a phone-number database. With ``normalize`` (the
    default) common grouping characters (spaces, hyphens, dots, parentheses) are
    stripped and the compact ``+<digits>`` form is returned; ``normalize=False``
    rejects those characters and returns the value unchanged.
    """

    def __init__(self, normalize: bool = True, *, msg: str | None = None) -> None:
        """Store the normalization flag and an optional custom message."""
        self.normalize = normalize
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the E.164 number (compact when normalizing), else raise."""
        if not isinstance(value, str):
            raise ValueInvalid(
                self.msg, code="e164", translation_key="expected_phone_number"
            )

        candidate = value.translate(_E164_SEPARATORS) if self.normalize else value
        digits = candidate[1:]
        if (
            not candidate.startswith("+")
            or not 2 <= len(digits) <= _E164_MAX
            or digits[0] not in _NONZERO
            or not _DIGITS.issuperset(digits)
        ):
            raise ValueInvalid(
                self.msg, code="e164", translation_key="invalid_phone_number"
            )

        return candidate
