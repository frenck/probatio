"""Tests for the encoding validators (JSONString, YAMLString)."""

from __future__ import annotations

import pytest

from probatio import (
    Base64,
    Hex,
    HexInt,
    JSONString,
    MultipleInvalid,
    Schema,
    SchemaError,
    YAMLString,
)
from probatio.error import CoerceInvalid, JsonInvalid, ValueInvalid, YamlInvalid
from probatio.serde import _optional


def test_json_string_decodes() -> None:
    """JSONString parses a JSON string into the decoded value."""
    assert Schema(JSONString())('{"a": 1}') == {"a": 1}


def test_json_string_validates_inner_schema() -> None:
    """An inner schema validates the decoded value."""
    schema = Schema(JSONString({"a": int}))
    assert schema('{"a": 1}') == {"a": 1}
    with pytest.raises(MultipleInvalid):
        schema('{"a": "x"}')


@pytest.mark.parametrize("value", ["not json", "{", 5])
def test_json_string_rejects_invalid(value: object) -> None:
    """A non-string or malformed JSON raises JsonInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(JSONString())(value)
    assert isinstance(caught.value.errors[0], JsonInvalid)


def test_yaml_string_decodes() -> None:
    """YAMLString parses a YAML string into the decoded value."""
    assert Schema(YAMLString())("a: 1\nb: 2") == {"a": 1, "b": 2}


def test_yaml_string_validates_inner_schema() -> None:
    """An inner schema validates the decoded value."""
    assert Schema(YAMLString({"a": int}))("a: 1") == {"a": 1}


@pytest.mark.parametrize("value", ["{unbalanced", "a: b: c", 5])
def test_yaml_string_rejects_invalid(value: object) -> None:
    """A non-string or malformed YAML raises YamlInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(YAMLString())(value)
    assert isinstance(caught.value.errors[0], YamlInvalid)


def test_yaml_string_without_a_backend_is_a_schema_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Building a YAMLString with no YAML backend installed is a schema error."""
    monkeypatch.setattr(_optional, "yamlrocks", None)
    monkeypatch.setattr(_optional, "pyyaml", None)
    with pytest.raises(SchemaError):
        YAMLString()


def test_base64_accepts_and_rejects() -> None:
    """Base64 validates an encoding string, returning it unchanged."""
    assert Schema(Base64())("aGk=") == "aGk="
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Base64())("not base64!!")
    assert isinstance(caught.value.errors[0], ValueInvalid)
    with pytest.raises(MultipleInvalid):
        Schema(Base64())(5)


def test_hex_accepts_and_rejects() -> None:
    """Hex validates a hexadecimal string, returning it unchanged."""
    assert Schema(Hex())("deadbeef") == "deadbeef"
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Hex())("xyz")
    assert isinstance(caught.value.errors[0], ValueInvalid)
    with pytest.raises(MultipleInvalid):
        Schema(Hex())(5)


def test_hex_int_parses_strings_and_ints() -> None:
    """HexInt reads a hex string (with or without 0x) or an int, returning an int."""
    schema = Schema(HexInt())
    assert schema("0x1A") == 26
    assert schema("1a") == 26
    assert schema(26) == 26
    assert schema("-ff") == -255


@pytest.mark.parametrize("value", [True, "zz", "", 1.5, None])
def test_hex_int_rejects_non_hex_integers(value: object) -> None:
    """A bool, a non-hex string, or a non-integer value raises CoerceInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(HexInt())(value)
    assert isinstance(caught.value.errors[0], CoerceInvalid)


def test_hex_int_custom_message() -> None:
    """A custom message replaces the default on a parse failure."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(HexInt(msg="not a register"))("nope")
    assert caught.value.errors[0].error_message == "not a register"
