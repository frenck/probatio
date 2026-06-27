"""The self-validation protocol: a type that validates a raw value of itself.

A type used as a schema validates by ``isinstance`` by default. A type that
defines a ``__probatio_validate__`` classmethod overrides that: the engine calls
the method to validate (and possibly coerce) a raw value, so a domain type can be
a first-class schema citizen without an external ``Coerce`` wrapper (ADR-007).
"""

from __future__ import annotations

from typing import Any

import pytest

from probatio import Required, Schema
from probatio.error import Invalid, MultipleInvalid


class Slug:
    """A value object that knows how to validate and normalize its own input."""

    def __init__(self, value: str) -> None:
        """Store the normalized (lower-cased) slug."""
        self.value = value

    @classmethod
    def __probatio_validate__(cls, value: Any) -> Slug:
        """Accept a string, normalize it, or raise Invalid for anything else."""
        if not isinstance(value, str):
            message = "expected a string slug"
            raise Invalid(message)
        return cls(value.lower())

    def __eq__(self, other: object) -> bool:
        """Two slugs are equal when their normalized values match."""
        return isinstance(other, Slug) and other.value == self.value

    def __hash__(self) -> int:
        """Hash on the normalized value, consistent with __eq__."""
        return hash(self.value)

    def __repr__(self) -> str:
        """Render with the normalized value."""
        return f"Slug({self.value!r})"


def test_protocol_validates_and_coerces() -> None:
    """The protocol method runs in place of isinstance, returning its result."""
    assert Schema(Slug)("Hello") == Slug("hello")


def test_protocol_rejection_propagates() -> None:
    """An Invalid raised by the protocol surfaces like any validation error."""
    with pytest.raises(MultipleInvalid):
        Schema(Slug)(5)


def test_protocol_reports_the_path_in_a_mapping() -> None:
    """A protocol failure under a key reports that key in the path."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema({Required("name"): Slug})({"name": 5})
    assert caught.value.errors[0].path == ["name"]


def test_protocol_normalizes_a_value_error() -> None:
    """A ValueError from the protocol is normalized to a probatio Invalid."""

    class Parsed:
        """A type whose protocol raises a bare ValueError on bad input."""

        @classmethod
        def __probatio_validate__(cls, value: Any) -> int:
            """Parse an int, leaking ValueError the way int() would."""
            return int(value)

    assert Schema(Parsed)("42") == 42
    with pytest.raises(MultipleInvalid):
        Schema(Parsed)("not a number")
