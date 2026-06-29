"""Tests for the Schema compile-and-call core."""

from __future__ import annotations

import pytest

from probatio import ALLOW_EXTRA, Invalid, MultipleInvalid, Required, Schema
from probatio.error import ScalarInvalid, TypeInvalid, ValueInvalid


def test_type_schema_accepts_matching_type() -> None:
    """A type schema returns the value unchanged when the type matches."""
    assert Schema(int)(3) == 3


def test_type_schema_rejects_wrong_type() -> None:
    """A type mismatch raises MultipleInvalid wrapping a TypeInvalid."""
    schema = Schema(int)
    with pytest.raises(MultipleInvalid) as caught:
        schema("nope")
    (error,) = caught.value.errors
    assert isinstance(error, TypeInvalid)
    assert error.msg == "expected int"
    assert error.path == []


def test_single_error_is_still_catchable_as_invalid() -> None:
    """MultipleInvalid is an Invalid, so a single except clause catches both."""
    with pytest.raises(Invalid):
        Schema(int)("nope")


def test_literal_schema_matches_by_equality() -> None:
    """A literal schema accepts only the equal value."""
    assert Schema("on")("on") == "on"
    assert Schema(42)(42) == 42


def test_literal_schema_rejects_other_values() -> None:
    """A non-equal value against a literal raises a ScalarInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema("on")("off")
    assert isinstance(caught.value.errors[0], ScalarInvalid)


def test_callable_validator_transforms_value() -> None:
    """A callable schema returns whatever the callable returns."""
    assert Schema(str.strip)("  hi  ") == "hi"


def test_callable_validator_value_error_becomes_invalid() -> None:
    """A callable raising ValueError is normalized to ValueInvalid."""

    def must_parse(value: str) -> int:
        return int(value)

    with pytest.raises(MultipleInvalid) as caught:
        Schema(must_parse)("not-a-number")
    assert isinstance(caught.value.errors[0], ValueInvalid)


def test_callable_value_error_message_is_preserved() -> None:
    """The ValueError reason is carried into the message (issue #417)."""

    def needs_timezone(_value: str) -> str:
        message = "datetime doesn't contain timezone info"
        raise ValueError(message)

    with pytest.raises(MultipleInvalid) as caught:
        Schema(needs_timezone)("2020-01-01")
    assert (
        caught.value.errors[0].error_message
        == "not a valid value: datetime doesn't contain timezone info"
    )


def test_callable_value_error_without_message_stays_generic() -> None:
    """A ValueError with no message keeps the bare 'not a valid value'."""

    def reject(_value: object) -> object:
        raise ValueError

    with pytest.raises(MultipleInvalid) as caught:
        Schema(reject)("x")
    assert caught.value.errors[0].error_message == "not a valid value"


def test_callable_validator_invalid_propagates() -> None:
    """An Invalid raised by a callable propagates with its own message."""

    def reject(_value: object) -> object:
        message = "always wrong"
        raise Invalid(message)

    with pytest.raises(MultipleInvalid) as caught:
        Schema(reject)("anything")
    assert caught.value.errors[0].msg == "always wrong"


def test_nested_schema_is_used_as_a_validator() -> None:
    """A Schema used inside a Schema validates through the same machinery."""
    assert Schema(Schema(int))(7) == 7


def test_schema_exposes_its_raw_definition() -> None:
    """Schema.schema keeps the raw definition for introspection."""
    assert Schema(int).schema is int


def test_schemas_compare_equal_by_definition() -> None:
    """Two schemas are equal when their definitions match, order aside."""
    assert Schema("foo") == Schema("foo")
    assert Schema({"foo": 1, "bar": 2}) == Schema({"bar": 2, "foo": 1})
    assert Schema(["a", "b"]) == Schema(["a", "b"])
    assert (Schema(["a"]) != Schema(["a"])) is False


def test_a_schema_is_not_equal_to_a_non_schema() -> None:
    """A Schema never compares equal to a bare value, and is unhashable."""
    assert (Schema("foo") == "foo") is False
    assert (Schema("foo") != "foo") is True
    with pytest.raises(TypeError):
        hash(Schema(int))


def test_infer_builds_a_schema_from_scalar_data() -> None:
    """Schema.infer maps a scalar (or empty container) to its type."""
    assert Schema.infer("foo") == Schema(str)
    assert Schema.infer(True) == Schema(bool)
    assert Schema.infer(42) == Schema(int)
    assert Schema.infer(3.14) == Schema(float)
    assert Schema.infer({}) == Schema(dict)
    assert Schema.infer([]) == Schema(list)


def test_infer_builds_a_schema_from_nested_data() -> None:
    """Schema.infer recurses into mappings and lists."""
    inferred = Schema.infer({"a": {"b": "c"}, "nums": [1, 2.0]})
    assert inferred == Schema(
        {Required("a"): {Required("b"): str}, Required("nums"): [int, float]}
    )


def test_infer_passes_keyword_arguments_through() -> None:
    """Schema.infer forwards required/extra to the built Schema."""
    schema = Schema.infer({"name": "x"}, required=False, extra=True)
    assert schema({"extra": 1}) == {"extra": 1}
    with pytest.raises(MultipleInvalid):
        schema({"name": 42})


def test_str_delegates_to_the_inner_schema() -> None:
    """str(Schema(x)) reads as str(x), matching voluptuous, not the object repr."""
    assert str(Schema({"a": int})) == "{'a': <class 'int'>}"
    assert str(Schema([int])) == "[<class 'int'>]"
    assert str(Schema(int)) == "<class 'int'>"


def test_str_lets_a_leading_brace_or_bracket_classify_the_schema() -> None:
    """The rendered string starts with { for a dict schema and [ for a list one.

    Home Assistant's config classifier reads exactly that to tell dict- from
    list-based config, so the delegation has to surface the wrapped container.
    """
    assert str(Schema({"a": int})).startswith("{")
    assert str(Schema([int])).startswith("[")


def test_repr_mirrors_voluptuous_with_extra_and_required() -> None:
    """repr(Schema) shows the inner schema, the extra policy name, and required."""
    rendered = repr(Schema({"a": int}, extra=ALLOW_EXTRA))
    assert rendered.startswith(
        "<Schema({'a': <class 'int'>}, extra=ALLOW_EXTRA, required=False) object at 0x"
    )
    assert rendered.endswith(">")
