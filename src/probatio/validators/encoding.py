"""Validators for encoded strings: Base64/hex, and JSON.

``JSONString`` validates that a string is valid JSON (and optionally that the decoded
value matches an inner schema) and returns the string unchanged. ``FromJSONString`` is
the decoding sibling: it parses the string with the standard library's ``json`` and
returns the decoded value.
"""

from __future__ import annotations

import base64
import binascii
import json
import typing

from probatio.error import (
    CoerceInvalid,
    JsonInvalid,
    ValueInvalid,
)
from probatio.schema import compile_schema
from probatio.validators._base import _SafeValidator


class Base64(_SafeValidator):
    """Require a valid Base64 string, returning it unchanged.

    This validates the encoding; it does not decode. Use ``Coerce`` with
    ``base64.b64decode`` if you want the bytes.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is valid Base64, else raise ValueInvalid."""
        if not isinstance(value, str | bytes):
            raise ValueInvalid(
                self.msg, code="base64", translation_key="expected_base64_string"
            )
        try:
            base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueInvalid(
                self.msg, code="base64", translation_key="expected_base64_string"
            ) from exc
        return value


class Hex(_SafeValidator):
    """Require a valid hexadecimal string, returning it unchanged."""

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is valid hex, else raise ValueInvalid."""
        if not isinstance(value, str):
            raise ValueInvalid(
                self.msg, code="hex", translation_key="expected_hex_string"
            )
        try:
            bytes.fromhex(value)
        except ValueError as exc:
            raise ValueInvalid(
                self.msg, code="hex", translation_key="expected_hex_string"
            ) from exc
        return value


class HexInt(_SafeValidator):
    """Parse a hexadecimal integer to an ``int``.

    Accepts an ``int`` (returned unchanged) or a string read base 16 (a leading
    ``0x`` is optional), so ``"0x1A"``, ``"1a"``, and ``26`` all yield ``26``. A
    ``bool`` is rejected (it is an ``int`` subclass, but never a hex integer
    anyone meant to write), and anything else raises ``CoerceInvalid``, so the
    result is always an ``int``. To render an ``int`` back as a hex string, use a
    coercion (``Coerce(lambda value: format(value, "#x"))``); that is output
    formatting, not validation.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def _error(self) -> CoerceInvalid:
        """Build the coercion error for a value that is not a hex integer."""
        return CoerceInvalid(
            self.msg,
            code="hex_int",
            translation_key="expected_hexadecimal_integer",
        )

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value parsed as a base-16 integer, else raise CoerceInvalid."""
        if isinstance(value, bool):
            raise self._error()
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value, 16)
            except ValueError as exc:
                raise self._error() from exc
        raise self._error()


class FromJSONString(_SafeValidator):
    """Parse a JSON string, optionally validating the decoded value.

    With an inner ``schema``, the decoded value is validated against it and the
    validated result is returned; without one, the decoded value is returned
    as-is. A value that is not a JSON string, or not valid JSON, raises
    ``JsonInvalid``. ``JSONString`` is the validate-only sibling that checks the
    same and returns the original string.
    """

    def __init__(self, schema: typing.Any = None, msg: str | None = None) -> None:
        """Compile the optional inner schema and store a message."""
        self._validate = None if schema is None else compile_schema(schema)
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the decoded (and validated) value, else raise JsonInvalid."""
        if not isinstance(value, str | bytes | bytearray):
            raise JsonInvalid(self.msg, translation_key="expected_json_string")

        try:
            decoded = json.loads(value)
        except ValueError as exc:
            raise JsonInvalid(self.msg, translation_key="invalid_json") from exc

        return self._validate(decoded) if self._validate is not None else decoded


class JSONString(_SafeValidator):
    """Validate a JSON string, returning it unchanged.

    Checks the value is valid JSON, and with an inner ``schema`` that the decoded value
    matches it; the original string is returned either way. Use ``FromJSONString`` when
    you want the decoded value instead.
    """

    def __init__(self, schema: typing.Any = None, msg: str | None = None) -> None:
        """Build the decoding sibling used to validate, and store a message."""
        self._decode = FromJSONString(schema, msg=msg)
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is valid JSON, else raise JsonInvalid."""
        self._decode(value)
        return value
