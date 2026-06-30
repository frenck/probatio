"""Tests for human-readable error rendering."""

from __future__ import annotations

import pytest

from probatio import Error, Required, Schema, Secret
from probatio.humanize import (
    MAX_VALIDATION_ERROR_ITEM_LENGTH,
    humanize_error,
    validate_with_humanized_errors,
)


def test_validate_with_humanized_errors_passes_valid_data() -> None:
    """A valid value is returned unchanged."""
    assert validate_with_humanized_errors({"port": 80}, Schema({"port": int})) == {
        "port": 80,
    }


def test_validate_with_humanized_errors_raises_error() -> None:
    """An invalid value raises Error carrying the humanized message."""
    with pytest.raises(Error) as caught:
        validate_with_humanized_errors({"port": "nope"}, Schema({"port": int}))
    assert "Got 'nope'" in str(caught.value)


def test_humanize_single_error_shows_path_and_value() -> None:
    """A single error renders with its message, path, and the offending value."""
    schema = Schema({"port": int})
    with pytest.raises(Exception) as caught:  # noqa: PT011
        schema({"port": "nope"})
    message = humanize_error({"port": "nope"}, caught.value)
    assert "expected int" in message
    assert "data['port']" in message
    assert "Got 'nope'" in message


def test_humanize_multiple_errors_joined() -> None:
    """Multiple errors render one per line, sorted."""
    schema = Schema({"a": int, "b": int})
    with pytest.raises(Exception) as caught:  # noqa: PT011
        schema({"a": "x", "b": "y"})
    message = humanize_error({"a": "x", "b": "y"}, caught.value)
    assert len(message.splitlines()) == 2


def test_humanize_redacts_a_failed_secret_value() -> None:
    """A Secret that fails validation is redacted, never echoed into the message.

    The raw value is still the unwrapped secret in the data on a failure (the mask
    only wraps a successful result), so rendering it would leak the credential.
    """
    schema = Schema({Required("password"): Secret(int), Required("user"): str})
    data = {"password": "hunter2-secret", "user": 123}
    with pytest.raises(Exception) as caught:  # noqa: PT011
        schema(data)
    message = humanize_error(data, caught.value)
    assert "hunter2-secret" not in message
    assert "<redacted>" in message
    # A non-secret field's value is still shown, redaction is targeted.
    assert "Got 123" in message


def test_humanize_truncates_long_values() -> None:
    """A very long offending value is truncated to the configured length."""
    schema = Schema({"v": int})
    big = "x" * (MAX_VALIDATION_ERROR_ITEM_LENGTH + 100)
    with pytest.raises(Exception) as caught:  # noqa: PT011
        schema({"v": big})
    message = humanize_error({"v": big}, caught.value)
    assert message.endswith("...")


def test_humanize_missing_key_renders_none() -> None:
    """A path that does not exist in the data renders the value as None."""
    schema = Schema({Required("name"): str})
    with pytest.raises(Exception) as caught:  # noqa: PT011
        schema({})
    message = humanize_error({}, caught.value)
    assert "required key not provided" in message
    assert "Got None" in message


def test_max_length_constant_is_exposed() -> None:
    """The truncation constant is part of the public surface."""
    assert isinstance(MAX_VALIDATION_ERROR_ITEM_LENGTH, int)


def test_humanize_error_appends_locations_from_a_locator() -> None:
    """A locator enriches each error line with the source location it points at."""
    from probatio import Location, MultipleInvalid  # noqa: PLC0415

    schema = Schema({Required("port"): int})

    def locator(path: object) -> Location | None:
        return Location(line=2, column=7, file="config.yaml") if path else None

    try:
        schema({"port": "nope"})
    except MultipleInvalid as err:
        rendered = humanize_error({"port": "nope"}, err, locator=locator)
    assert "(at config.yaml:2:7)" in rendered


def test_humanize_error_without_a_locator_is_unchanged() -> None:
    """Omitting the locator leaves the message exactly as before (no location)."""
    from probatio import MultipleInvalid  # noqa: PLC0415

    schema = Schema({Required("port"): int})
    try:
        schema({"port": "nope"})
    except MultipleInvalid as err:
        rendered = humanize_error({"port": "nope"}, err)
    assert "at " not in rendered


def test_humanize_error_locator_returning_none_adds_no_location() -> None:
    """When the locator cannot place an error, the line is left without a location."""
    from probatio import MultipleInvalid  # noqa: PLC0415

    schema = Schema({Required("port"): int})
    try:
        schema({"port": "nope"})
    except MultipleInvalid as err:
        rendered = humanize_error({"port": "nope"}, err, locator=lambda _path: None)
    assert "(at" not in rendered
