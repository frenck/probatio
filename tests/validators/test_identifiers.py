"""Tests for the identifier validators (UUID, MAC address)."""

from __future__ import annotations

import uuid as uuid_module

import pytest

from probatio import ULID, UUID, MacAddress, MultipleInvalid, Schema
from probatio.error import MacAddressInvalid, UuidInvalid, ValueInvalid

_SAMPLE = "12345678-1234-5678-1234-567812345678"


def test_uuid_coerces_a_string() -> None:
    """UUID returns a uuid.UUID parsed from the string."""
    result = Schema(UUID())(_SAMPLE)
    assert result == uuid_module.UUID(_SAMPLE)
    assert isinstance(result, uuid_module.UUID)


def test_uuid_accepts_an_existing_uuid() -> None:
    """An existing uuid.UUID passes through unchanged."""
    value = uuid_module.uuid4()
    assert Schema(UUID())(value) is value


def test_uuid_rejects_a_bad_value() -> None:
    """A non-UUID value raises UuidInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(UUID())("not-a-uuid")
    assert isinstance(caught.value.errors[0], UuidInvalid)


def test_uuid_version_pin() -> None:
    """A version-pinned UUID accepts the right version and rejects others."""
    v4 = str(uuid_module.uuid4())
    assert Schema(UUID(version=4))(v4) == uuid_module.UUID(v4)
    with pytest.raises(MultipleInvalid) as caught:
        Schema(UUID(version=4))(_SAMPLE)  # this sample is version 1-shaped
    assert isinstance(caught.value.errors[0], UuidInvalid)


@pytest.mark.parametrize(
    "value",
    ["AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "aabb.ccdd.eeff", "AABBCCDDEEFF"],
)
def test_mac_address_normalizes(value: str) -> None:
    """MacAddress accepts common forms and normalizes to lowercase colon form."""
    assert Schema(MacAddress())(value) == "aa:bb:cc:dd:ee:ff"


@pytest.mark.parametrize("value", [123, "xx", "AA:BB:CC", "AA:BB:CC:DD:EE:GG"])
def test_mac_address_rejects_invalid(value: object) -> None:
    """A non-string or malformed MAC raises MacAddressInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(MacAddress())(value)
    assert isinstance(caught.value.errors[0], MacAddressInvalid)


def test_mac_address_upper_and_separator() -> None:
    """upper and separator control the normalized output."""
    assert Schema(MacAddress(upper=True))("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"
    assert Schema(MacAddress(separator="-"))("aabbccddeeff") == "aa-bb-cc-dd-ee-ff"
    assert Schema(MacAddress(separator=""))("AA:BB:CC:DD:EE:FF") == "aabbccddeeff"
    assert (
        Schema(MacAddress(upper=True, separator="-"))("aabbccddeeff")
        == "AA-BB-CC-DD-EE-FF"
    )


def test_mac_address_normalize_false_returns_input_unchanged() -> None:
    """normalize=False validates but returns the original string verbatim."""
    assert (
        Schema(MacAddress(normalize=False))("AA-bb-CC-dd-EE-ff") == "AA-bb-CC-dd-EE-ff"
    )


def test_mac_address_normalize_false_still_validates() -> None:
    """normalize=False still rejects a malformed MAC."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(MacAddress(normalize=False))("nope")
    assert isinstance(caught.value.errors[0], MacAddressInvalid)


def test_custom_messages() -> None:
    """A custom message replaces the default on failure."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(UUID(msg="bad uuid"))("x")
    assert caught.value.errors[0].error_message == "bad uuid"


def test_ulid_normalizes_to_upper_case() -> None:
    """ULID accepts a 26-char Crockford base32 string, normalized to upper case."""
    assert Schema(ULID())("01arz3ndektsv4rrffq69g5fav") == "01ARZ3NDEKTSV4RRFFQ69G5FAV"


@pytest.mark.parametrize("value", ["short", "01arz3ndektsv4rrffq69g5fai", 5])
def test_ulid_rejects_invalid(value: object) -> None:
    """A wrong length, a bad character (I/L/O/U), or a non-string raises ValueInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(ULID())(value)
    assert isinstance(caught.value.errors[0], ValueInvalid)
