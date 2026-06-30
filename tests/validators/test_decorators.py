"""Tests for the validate decorator and the raises guard."""

from __future__ import annotations

import pytest

from probatio import (
    Invalid,
    MultipleInvalid,
    Schema,
    SchemaError,
    message,
    raises,
    truth,
    validate,
)


def test_validate_checks_named_arguments() -> None:
    """validate coerces nothing but rejects arguments that fail their schema."""

    @validate(arg1=int, arg2=int)
    def multiply(arg1: int, arg2: int) -> int:
        return arg1 * arg2

    assert multiply(3, 4) == 12


def test_validate_rejects_a_bad_argument() -> None:
    """A bad argument raises through the input schema."""

    @validate(arg1=int)
    def echo(arg1: int) -> int:
        return arg1

    with pytest.raises(MultipleInvalid):
        echo("not an int")


def test_validate_preserves_positional_only_parameters() -> None:
    """A parameter before the ``/`` is passed positionally, not as a keyword.

    Calling the wrapped function with every argument as a keyword would raise a
    TypeError for a positional-only parameter, so they have to go back positionally.
    """

    @validate(arg1=int, arg2=int)
    def multiply(arg1: int, /, arg2: int) -> int:
        return arg1 * arg2

    assert multiply(3, 4) == 12
    assert multiply(3, arg2=4) == 12
    with pytest.raises(MultipleInvalid):
        multiply("x", 4)


def test_validate_checks_the_return_value() -> None:
    """A __return__ schema validates the function's result."""

    @validate(arg=int, __return__=str)
    def to_text(arg: int) -> str:
        return str(arg)

    assert to_text(5) == "5"


def test_validate_rejects_a_bad_return_value() -> None:
    """A return value that fails __return__ raises."""

    @validate(arg=int, __return__=str)
    def wrong(arg: int) -> int:
        return arg

    with pytest.raises(MultipleInvalid):
        wrong(5)


def test_validate_without_argument_schemas() -> None:
    """With only a return schema, arguments pass through untouched."""

    @validate(__return__=int)
    def add(a: int, b: int) -> int:
        return a + b

    assert add(1, 2) == 3


def test_raises_accepts_a_matching_exception() -> None:
    """raises swallows the expected exception."""
    with raises(MultipleInvalid):
        raise MultipleInvalid([])


def test_raises_checks_the_message() -> None:
    """raises asserts the exact message when one is given."""
    boom = "boom"
    with raises(ValueError, msg="boom"):
        raise ValueError(boom)


def test_raises_checks_a_regex() -> None:
    """raises asserts the message matches a regex when one is given."""
    boom = "boom"
    with raises(ValueError, regex="^bo"):
        raise ValueError(boom)


def test_raises_fails_when_nothing_is_raised() -> None:
    """raises itself raises AssertionError when the block does not."""
    with pytest.raises(AssertionError), raises(ValueError):
        pass


def test_message_builds_a_validator_with_a_default_message() -> None:
    """A message factory turns a ValueError into an Invalid carrying the default."""

    @message("not an integer")
    def isint(value: object) -> int:
        return int(value)  # type: ignore[call-overload]

    with pytest.raises(MultipleInvalid) as caught:
        Schema(isint())("nope")
    assert str(caught.value.errors[0]) == "not an integer"


def test_message_allows_per_use_overrides() -> None:
    """The message and the error class can be overridden when the factory is called."""

    class IntegerInvalid(Invalid):
        """A custom error for the test."""

    @message("not an integer")
    def isint(value: object) -> int:
        return int(value)  # type: ignore[call-overload]

    with pytest.raises(MultipleInvalid) as caught:
        Schema(isint("bad value", IntegerInvalid))("nope")
    assert isinstance(caught.value.errors[0], IntegerInvalid)
    assert str(caught.value.errors[0]) == "bad value"


def test_message_rejects_a_non_invalid_class() -> None:
    """A custom class that is not an Invalid subclass is a SchemaError."""
    with pytest.raises(SchemaError):

        @message("nope", cls=ValueError)  # type: ignore[type-var]
        def _isint(value: object) -> int:
            return int(value)  # type: ignore[call-overload]


def test_truth_returns_the_value_when_the_predicate_is_truthy() -> None:
    """A truthy predicate returns the value unchanged."""

    @truth
    def is_positive(value: int) -> bool:
        return value > 0

    assert Schema(is_positive)(3) == 3


def test_truth_rejects_when_the_predicate_is_falsy() -> None:
    """A falsy predicate raises through the engine."""

    @truth
    def is_positive(value: int) -> bool:
        return value > 0

    with pytest.raises(MultipleInvalid):
        Schema(is_positive)(-1)
