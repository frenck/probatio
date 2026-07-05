"""Tests for the format validators (CreditCard, IBAN, DataURI, E164)."""

from __future__ import annotations

import pytest

from probatio import (
    E164,
    IBAN,
    CreditCard,
    DataURI,
    Schema,
    to_field_list,
    to_json_schema,
)
from probatio.error import MultipleInvalid


def test_credit_card_accepts_a_luhn_valid_number() -> None:
    """A Luhn-valid number passes; grouping separators are stripped by default."""
    schema = Schema(CreditCard())
    assert schema("4242424242424242") == "4242424242424242"
    assert schema("4242 4242 4242 4242") == "4242424242424242"
    assert schema("5555-5555-5555-4444") == "5555555555554444"


@pytest.mark.parametrize(
    "value",
    [
        "4242424242424241",  # fails Luhn
        "1234",  # too short
        "4242424242424242424242",  # too long
        "notacard",  # non-digit
        4242424242424242,  # not a string
    ],
)
def test_credit_card_rejects_invalid(value: object) -> None:
    """A non-Luhn, wrong-length, non-digit, or non-string value is rejected."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(CreditCard())(value)
    assert caught.value.errors[0].code == "credit_card"


def test_iban_accepts_a_checksum_valid_value() -> None:
    """A mod-97-valid IBAN passes; spaces are stripped and it is upper-cased."""
    schema = Schema(IBAN())
    assert schema("DE89370400440532013000") == "DE89370400440532013000"
    assert schema("GB82 WEST 1234 5698 7654 32") == "GB82WEST12345698765432"
    assert schema("gb82 west 1234 5698 7654 32") == "GB82WEST12345698765432"


@pytest.mark.parametrize(
    "value",
    [
        "DE89370400440532013001",  # fails the checksum
        "DE0",  # too short
        "1234567890123456",  # no country letters at the front
        "DE89370400440532013!00",  # a non-alphanumeric character
        1234,  # not a string
    ],
)
def test_iban_rejects_invalid(value: object) -> None:
    """A bad checksum, length, structure, character, or type is rejected."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(IBAN())(value)
    assert caught.value.errors[0].code == "iban"


def test_data_uri_accepts_well_formed_uris() -> None:
    """The data: scheme with or without base64 and a media type validates.

    A valid value is returned unchanged, so this asserts equality, not truthiness.
    """
    schema = Schema(DataURI())
    for uri in (
        "data:text/plain;base64,SGVsbG8=",
        "data:,hello",  # no media type, no base64
        "data:text/html,%3Ch1%3E",
        "data:;base64,QQ==",  # empty media type, base64
    ):
        assert schema(uri) == uri


@pytest.mark.parametrize(
    "value",
    [
        "data:text/plain;base64,not!base64",  # invalid base64 payload
        "http://example.com",  # not the data: scheme
        "data:nomediatype",  # no comma
        "data:nomime;base64,QQ==",  # a media type without a slash
        42,  # not a string
    ],
)
def test_data_uri_rejects_invalid(value: object) -> None:
    """A bad payload, scheme, structure, media type, or type is rejected."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(DataURI())(value)
    assert caught.value.errors[0].code == "data_uri"


def test_e164_accepts_valid_numbers() -> None:
    """A leading + and 2 to 15 digits validates; grouping is stripped by default."""
    schema = Schema(E164())
    assert schema("+14155552671") == "+14155552671"
    assert schema("+442071838750") == "+442071838750"
    assert schema("+1 (415) 555-2671") == "+14155552671"
    assert schema("+12") == "+12"  # the two-digit minimum (one more than "+1")


@pytest.mark.parametrize(
    "value",
    [
        "+0123456789",  # leading zero after the plus
        "14155552671",  # no leading plus
        "+1",  # too short
        "+1415555267100000",  # too long (16 digits)
        "+1a2",  # a non-digit
        42,  # not a string
    ],
)
def test_e164_rejects_invalid(value: object) -> None:
    """A leading zero, missing plus, wrong length, non-digit, or type is rejected."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(E164())(value)
    assert caught.value.errors[0].code == "e164"


def test_normalize_false_returns_input_unchanged() -> None:
    """normalize=False validates but returns the original string verbatim."""
    assert (
        Schema(CreditCard(normalize=False))("4242 4242 4242 4242")
        == "4242 4242 4242 4242"
    )
    assert (
        Schema(IBAN(normalize=False))("gb82 west 1234 5698 7654 32")
        == "gb82 west 1234 5698 7654 32"
    )
    assert Schema(E164(normalize=False))("+14155552671") == "+14155552671"


def test_e164_normalize_false_rejects_grouped_input() -> None:
    """normalize=False keeps E164 strict: grouping characters are rejected."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(E164(normalize=False))("+1 (415) 555-2671")
    assert caught.value.errors[0].code == "e164"


def test_format_validators_serialize_as_strings() -> None:
    """The codecs render the format validators as a plain string field."""
    for validator in (CreditCard(), IBAN(), DataURI(), E164()):
        assert to_field_list(Schema(validator)) == {"type": "string"}
        assert to_json_schema(Schema(validator)) == {"type": "string"}


def test_custom_message_overrides_the_default() -> None:
    """A custom message replaces the validator's default."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(IBAN(msg="bad account"))("nope")
    assert caught.value.errors[0].error_message == "bad account"
