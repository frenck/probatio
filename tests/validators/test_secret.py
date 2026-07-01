"""Tests for the Secret key marker and its error redaction."""

from __future__ import annotations

import pytest

from probatio import (
    MultipleInvalid,
    Optional,
    Required,
    Schema,
    SchemaError,
    Secret,
)
from probatio.humanize import humanize_error


def test_secret_passes_the_value_through_unchanged() -> None:
    """A Secret key does not transform its value; it validates and returns as-is."""
    schema = Schema({Required(Secret("password")): str})
    assert schema({"password": "hunter2"}) == {"password": "hunter2"}


def test_secret_redacts_a_failed_value() -> None:
    """A value under a Secret key is redacted from the humanized error."""
    schema = Schema({Required(Secret("password")): int})
    data = {"password": "hunter2-secret"}
    with pytest.raises(MultipleInvalid) as caught:
        schema(data)

    error = caught.value.errors[0]
    assert error.secret is True
    message = humanize_error(data, error)
    assert "hunter2-secret" not in message
    assert "<redacted>" in message


def test_secret_only_redacts_its_own_key() -> None:
    """A non-secret sibling's value is still shown; redaction is targeted."""
    schema = Schema({Required(Secret("password")): int, Required("user"): str})
    data = {"password": "s3cr3t", "user": 123}
    with pytest.raises(MultipleInvalid) as caught:
        schema(data)

    message = humanize_error(data, caught.value)
    assert "s3cr3t" not in message
    assert "Got 123" in message


def test_secret_redacts_a_nested_value() -> None:
    """A failure deep inside a Secret key's value is redacted, not just the leaf."""
    schema = Schema({Secret("creds"): {"token": int}})
    data = {"creds": {"token": "leak-me"}}
    with pytest.raises(MultipleInvalid) as caught:
        schema(data)

    message = humanize_error(data, caught.value)
    assert "leak-me" not in message
    assert "<redacted>" in message


def test_secret_composes_with_optional_either_way() -> None:
    """Optional(Secret(key)) and Secret(Optional(key)) are the same optional secret."""
    outer = Schema({Optional(Secret("password"), default="x"): str})
    inner = Schema({Secret(Optional("password", default="x")): str})
    assert outer({}) == {"password": "x"}
    assert inner({}) == {"password": "x"}


def test_secret_is_optional_when_wrapping_optional() -> None:
    """An absent Optional(Secret(key)) is not a required-key failure."""
    schema = Schema({Optional(Secret("password")): str})
    assert schema({}) == {}


def test_secret_around_a_type_key_is_rejected() -> None:
    """Secret must name a concrete key, not a type or callable key schema."""
    with pytest.raises(SchemaError):
        Schema({Secret(str): int})


def test_secret_custom_message_is_kept() -> None:
    """A message carried on the Secret marker still surfaces for a missing key."""
    schema = Schema({Required(Secret("password"), msg="password is required"): int})
    with pytest.raises(MultipleInvalid) as caught:
        schema({})
    assert caught.value.errors[0].error_message == "password is required"


def test_secret_survives_compiled_schema() -> None:
    """The compiled path bails to the interpreter on failure, which still redacts."""
    schema = Schema({Required(Secret("password")): int}, compile=True)
    data = {"password": "leak"}
    with pytest.raises(MultipleInvalid) as caught:
        schema(data)
    assert "leak" not in humanize_error(data, caught.value)
