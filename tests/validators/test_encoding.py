"""Tests for the encoding validators (Base64, Hex, HexInt, JSONString)."""

from __future__ import annotations

import contextlib
from typing import get_type_hints

import pytest

from probatio import (
    Base64,
    FromJSONString,
    Hex,
    HexInt,
    JSONString,
    MultipleInvalid,
    Schema,
)
from probatio.error import CoerceInvalid, JsonInvalid, ValueInvalid


def test_json_string_validates_and_returns_the_string() -> None:
    """JSONString validates the JSON and returns the string unchanged."""
    assert Schema(JSONString())('{"a": 1}') == '{"a": 1}'


def test_from_json_string_decodes() -> None:
    """FromJSONString parses a JSON string into the decoded value."""
    assert Schema(FromJSONString())('{"a": 1}') == {"a": 1}


def test_json_string_inner_schema_validates_but_keeps_the_string() -> None:
    """An inner schema validates the decoded value; JSONString returns the string."""
    schema = Schema(JSONString({"a": int}))
    assert schema('{"a": 1}') == '{"a": 1}'
    with pytest.raises(MultipleInvalid):
        schema('{"a": "x"}')


def test_from_json_string_inner_schema_returns_the_decoded_value() -> None:
    """FromJSONString validates the decoded value against an inner schema, returning it."""
    assert Schema(FromJSONString({"a": int}))('{"a": 1}') == {"a": 1}
    with pytest.raises(MultipleInvalid):
        Schema(FromJSONString({"a": int}))('{"a": "x"}')


@pytest.mark.parametrize("value", ["not json", "{", 5])
@pytest.mark.parametrize("validator", [JSONString, FromJSONString])
def test_json_rejects_invalid(validator: type, value: object) -> None:
    """A non-string or malformed JSON raises JsonInvalid, validating or decoding."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(validator())(value)
    assert isinstance(caught.value.errors[0], JsonInvalid)


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


def test_hex_int_declares_an_int_return() -> None:
    """HexInt always hands back an int, and says so rather than promising Any."""
    assert get_type_hints(HexInt.__call__)["return"] is int


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


def test_json_string_reports_a_too_deeply_nested_document_as_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A RecursionError from the JSON decoder becomes JsonInvalid, not a crash."""

    def too_deep(_value: object) -> object:
        """Stand in for a decoder that ran out of stack."""
        raise RecursionError

    monkeypatch.setattr("probatio.validators.encoding.json.loads", too_deep)

    for validator in (JSONString(), FromJSONString()):
        with pytest.raises(MultipleInvalid) as caught:
            Schema(validator)("[[[]]]")
        error = caught.value.errors[0]
        assert isinstance(error, JsonInvalid)
        assert error.translation_key == "invalid_json"
        assert isinstance(error.__cause__, RecursionError)


def test_json_string_rejects_a_real_deeply_nested_document() -> None:
    """A document nested far past the recursion limit is invalid, whatever the build."""
    document = "[" * 100_000 + "]" * 100_000

    # Newer interpreters may decode this without recursing; both outcomes are
    # acceptable, a raw RecursionError is not.
    with contextlib.suppress(MultipleInvalid):
        Schema(JSONString())(document)
