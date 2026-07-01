"""Tests for the identifier validators (UUID, MAC address)."""

from __future__ import annotations

import uuid as uuid_module

import pytest

from probatio import (
    ULID,
    UUID,
    MacAddress,
    MultipleInvalid,
    NormalizeMacAddress,
    Schema,
)
from probatio.error import MacAddressInvalid, UuidInvalid, ValueInvalid

_SAMPLE = "12345678-1234-5678-1234-567812345678"


def test_uuid_validates_a_string() -> None:
    """UUID validates a UUID string and returns it unchanged (Coerce for the object)."""
    assert Schema(UUID())(_SAMPLE) == _SAMPLE


def test_uuid_accepts_an_existing_uuid() -> None:
    """An existing uuid.UUID passes through unchanged."""
    value = uuid_module.uuid4()
    assert Schema(UUID())(value) is value


def test_uuid_object_via_coerce() -> None:
    """The parsed uuid.UUID object is opt-in through Coerce, not the validator."""
    from probatio import Coerce  # noqa: PLC0415

    result = Schema(Coerce(uuid_module.UUID))(_SAMPLE)
    assert result == uuid_module.UUID(_SAMPLE)
    assert isinstance(result, uuid_module.UUID)


def test_uuid_rejects_a_bad_value() -> None:
    """A non-UUID value raises UuidInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(UUID())("not-a-uuid")
    assert isinstance(caught.value.errors[0], UuidInvalid)


def test_uuid_version_pin() -> None:
    """A version-pinned UUID accepts the right version and rejects others."""
    v4 = str(uuid_module.uuid4())
    assert Schema(UUID(version=4))(v4) == v4

    with pytest.raises(MultipleInvalid) as caught:
        Schema(UUID(version=4))(_SAMPLE)  # this sample is version 1-shaped
    assert isinstance(caught.value.errors[0], UuidInvalid)


@pytest.mark.parametrize(
    "value",
    ["AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "aabb.ccdd.eeff", "AABBCCDDEEFF"],
)
def test_mac_address_validates_and_returns_unchanged(value: str) -> None:
    """MacAddress accepts common forms and returns the value unchanged."""
    assert Schema(MacAddress())(value) == value


@pytest.mark.parametrize("value", [123, "xx", "AA:BB:CC", "AA:BB:CC:DD:EE:GG"])
def test_mac_address_rejects_invalid(value: object) -> None:
    """A non-string or malformed MAC raises MacAddressInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(MacAddress())(value)
    assert isinstance(caught.value.errors[0], MacAddressInvalid)


@pytest.mark.parametrize(
    "value",
    ["AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "aabb.ccdd.eeff", "AABBCCDDEEFF"],
)
def test_normalize_mac_address_canonicalizes(value: str) -> None:
    """NormalizeMacAddress returns the lowercase colon form."""
    assert Schema(NormalizeMacAddress())(value) == "aa:bb:cc:dd:ee:ff"


def test_normalize_mac_address_upper_and_separator() -> None:
    """upper and separator control the canonical output."""
    got = Schema(NormalizeMacAddress(upper=True))("aa-bb-cc-dd-ee-ff")
    assert got == "AA:BB:CC:DD:EE:FF"
    assert (
        Schema(NormalizeMacAddress(separator="-"))("aabbccddeeff")
        == "aa-bb-cc-dd-ee-ff"
    )
    assert (
        Schema(NormalizeMacAddress(separator=""))("AA:BB:CC:DD:EE:FF") == "aabbccddeeff"
    )
    assert (
        Schema(NormalizeMacAddress(upper=True, separator="-"))("aabbccddeeff")
        == "AA-BB-CC-DD-EE-FF"
    )


def test_normalize_mac_address_rejects_invalid() -> None:
    """NormalizeMacAddress still rejects a malformed MAC."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(NormalizeMacAddress())("nope")
    assert isinstance(caught.value.errors[0], MacAddressInvalid)


def test_custom_messages() -> None:
    """A custom message replaces the default on failure."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(UUID(msg="bad uuid"))("x")
    assert caught.value.errors[0].error_message == "bad uuid"


def test_ulid_validates_and_returns_unchanged() -> None:
    """ULID accepts a 26-char Crockford base32 string of either case, unchanged."""
    assert Schema(ULID())("01arz3ndektsv4rrffq69g5fav") == "01arz3ndektsv4rrffq69g5fav"
    assert Schema(ULID())("01ARZ3NDEKTSV4RRFFQ69G5FAV") == "01ARZ3NDEKTSV4RRFFQ69G5FAV"


@pytest.mark.parametrize("value", ["short", "01arz3ndektsv4rrffq69g5fai", 5])
def test_ulid_rejects_invalid(value: object) -> None:
    """A wrong length, a bad character (I/L/O/U), or a non-string raises ValueInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(ULID())(value)
    assert isinstance(caught.value.errors[0], ValueInvalid)
