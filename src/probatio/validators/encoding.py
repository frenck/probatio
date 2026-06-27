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

from probatio.error import JsonInvalid, SchemaError, ValueInvalid, YamlInvalid
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
