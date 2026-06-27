"""Tests for the Secret validator and its masking SecretValue carrier."""

from __future__ import annotations

import pytest

from probatio import MultipleInvalid, Schema, Secret, SecretValue
from probatio.error import SecretInvalid


def test_secret_wraps_and_masks() -> None:
    """Secret returns a SecretValue that hides the value in repr and str."""
    result = Schema(Secret())("hunter2")
    assert isinstance(result, SecretValue)
    assert result.get_secret_value() == "hunter2"
    assert "hunter2" not in repr(result)
    assert "hunter2" not in str(result)


def test_secret_default_accepts_anything() -> None:
    """With no inner schema, Secret wraps any value."""
    assert Schema(Secret())(123).get_secret_value() == 123


def test_secret_inner_schema_validates() -> None:
    """An inner schema validates the raw value before wrapping."""
    assert Schema(Secret(str))("token").get_secret_value() == "token"


def test_secret_inner_failure_does_not_echo_the_value() -> None:
    """A failing inner schema raises SecretInvalid without echoing the secret."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Secret(str))(987654)
    error = caught.value.errors[0]
    assert isinstance(error, SecretInvalid)
    assert "987654" not in str(error)


def test_secret_custom_message() -> None:
    """A custom message replaces the default on failure."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Secret(str, msg="bad token"))(5)
    assert caught.value.errors[0].error_message == "bad token"


def test_secret_is_idempotent() -> None:
    """Re-validating a SecretValue unwraps and re-wraps it, keeping the value."""
    once = Schema(Secret(str))("s3cr3t")
    twice = Schema(Secret(str))(once)
    assert twice.get_secret_value() == "s3cr3t"


def test_secret_value_equality() -> None:
    """SecretValue compares by its wrapped value, only against another SecretValue."""
    assert SecretValue("a") == SecretValue("a")
    assert SecretValue("a") != SecretValue("b")
    assert SecretValue("a") != "a"


def test_secret_value_is_hashable() -> None:
    """A SecretValue can be used as a dict key (hashes by its value)."""
    mapping = {SecretValue("a"): 1}
    assert mapping[SecretValue("a")] == 1


def test_secret_stays_masked_inside_a_mapping() -> None:
    """A SecretValue in a validated mapping does not leak in the mapping's repr."""
    schema = Schema({"password": Secret(str), "user": str})
    result = schema({"password": "s3cr3t", "user": "bob"})
    assert "s3cr3t" not in repr(result)
    assert result["password"].get_secret_value() == "s3cr3t"
