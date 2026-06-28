"""Validators that decode an encoded string and optionally validate the result.

``JSONString`` and ``YAMLString`` parse a string of JSON or YAML and return the
decoded value, optionally validating it against an inner schema. YAML is parsed
with the same safe loader as ``load_yaml`` (no arbitrary object construction), and
``YAMLString`` needs a YAML backend installed (``probatio[yaml]``), checked when
the schema is built.
"""

from __future__ import annotations

import base64
import binascii
import json
import typing

from probatio.error import (
    CoerceInvalid,
    JsonInvalid,
    SchemaError,
    ValueInvalid,
    YamlInvalid,
)
from probatio.schema import compile_schema
from probatio.serde import _optional, load_yaml
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
            raise ValueInvalid(self.msg or "expected a Base64 string", code="base64")
        try:
            base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            message = self.msg or "expected a Base64 string"
            raise ValueInvalid(message, code="base64") from exc
        return value


class Hex(_SafeValidator):
    """Require a valid hexadecimal string, returning it unchanged."""

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is valid hex, else raise ValueInvalid."""
        if not isinstance(value, str):
            raise ValueInvalid(self.msg or "expected a hex string", code="hex")
        try:
            bytes.fromhex(value)
        except ValueError as exc:
            raise ValueInvalid(self.msg or "expected a hex string", code="hex") from exc
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
            self.msg or "expected a hexadecimal integer", code="hex_int"
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


class JSONString(_SafeValidator):
    """Parse a JSON string, optionally validating the decoded value.

    With an inner ``schema``, the decoded value is validated against it and the
    validated result is returned; without one, the decoded value is returned
    as-is. A value that is not a JSON string, or not valid JSON, raises
    ``JsonInvalid``.
    """

    def __init__(self, schema: typing.Any = None, msg: str | None = None) -> None:
        """Compile the optional inner schema and store a message."""
        self._validate = None if schema is None else compile_schema(schema)
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the decoded (and validated) value, else raise JsonInvalid."""
        if not isinstance(value, str | bytes | bytearray):
            raise JsonInvalid(self.msg or "expected a JSON string")
        try:
            decoded = json.loads(value)
        except ValueError as exc:
            raise JsonInvalid(self.msg or "invalid JSON") from exc
        return self._validate(decoded) if self._validate is not None else decoded


class YAMLString(_SafeValidator):
    """Parse a YAML string (safely), optionally validating the decoded value.

    With an inner ``schema``, the decoded value is validated against it; without
    one, the decoded value is returned as-is. A value that is not a YAML string,
    or not valid YAML, raises ``YamlInvalid``. Building the validator raises
    ``SchemaError`` when no YAML backend is installed.
    """

    def __init__(self, schema: typing.Any = None, msg: str | None = None) -> None:
        """Compile the optional inner schema; require a YAML backend up front."""
        if _optional.yamlrocks is None and _optional.pyyaml is None:
            message = "YAMLString needs a YAML parser; install probatio[yaml]"
            raise SchemaError(message)
        self._validate = None if schema is None else compile_schema(schema)
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the decoded (and validated) value, else raise YamlInvalid."""
        if not isinstance(value, str | bytes):
            raise YamlInvalid(self.msg or "expected a YAML string")
        try:
            decoded = load_yaml(value)
        except Exception as exc:
            # A YAML backend raises its own parse-error type (YAMLRocks, PyYAML);
            # normalize any of them, plus deep-nesting recursion, to YamlInvalid.
            raise YamlInvalid(self.msg or "invalid YAML") from exc
        return self._validate(decoded) if self._validate is not None else decoded
