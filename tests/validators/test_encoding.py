"""Tests for the encoding validators (JSONString, YAMLString)."""

from __future__ import annotations

import pytest

from probatio import (
    Base64,
    Hex,
    JSONString,
    MultipleInvalid,
    Schema,
    SchemaError,
    YAMLString,
)
from probatio.error import JsonInvalid, ValueInvalid, YamlInvalid
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
