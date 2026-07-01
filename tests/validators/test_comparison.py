"""Tests for the range, length, and membership validators."""

from __future__ import annotations

from decimal import Decimal

import pytest

from probatio import (
    Byte,
    Clamp,
    Contains,
    Equal,
    FromPercentage,
    In,
    Latitude,
    Length,
    Literal,
    Longitude,
    MultipleInvalid,
    MultipleOf,
    Negative,
    NonEmpty,
    NonNegative,
    NotIn,
    Percentage,
    Positive,
    Range,
    Schema,
    SchemaError,
    SmallFloat,
)
from probatio.error import (
    ContainsInvalid,
    InInvalid,
    Invalid,
    LengthInvalid,
    LiteralInvalid,
    MultipleOfInvalid,
    NotInInvalid,
    RangeInvalid,
)


def test_literal_returns_the_literal() -> None:
    """Literal accepts a matching value and returns the literal."""
    assert Schema(Literal(5))(5) == 5


def test_literal_rejects_a_mismatch() -> None:
    """Literal rejects a value that does not match, with LiteralInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Literal(5))(6)
    assert isinstance(caught.value.errors[0], LiteralInvalid)


def test_literal_renders_like_its_value() -> None:
    """Literal's str and repr mirror the underlying literal."""
    assert str(Literal("on")) == "on"
    assert repr(Literal("on")) == "'on'"


def test_equal() -> None:
    """Equal accepts only a value equal to its target."""
    assert Schema(Equal(5))(5) == 5
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Equal(5))(6)
    assert isinstance(caught.value.errors[0], Invalid)


def test_contains() -> None:
    """Contains requires the collection to hold the item."""
    assert Schema(Contains(2))([1, 2, 3]) == [1, 2, 3]
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Contains(9))([1, 2, 3])
    assert isinstance(caught.value.errors[0], ContainsInvalid)


def test_contains_on_non_collection() -> None:
    """Contains fails cleanly when the value is not a collection."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Contains(1))(5)
    assert isinstance(caught.value.errors[0], ContainsInvalid)


def test_contains_when_membership_raises_attributeerror() -> None:
    """Contains stays clean when ``__contains__`` itself errors (ip_network)."""
    import ipaddress  # noqa: PLC0415

    with pytest.raises(MultipleInvalid) as caught:
        Schema(Contains(5))(ipaddress.ip_network("10.0.0.0/8"))
    assert isinstance(caught.value.errors[0], ContainsInvalid)


def test_range_accepts_and_rejects() -> None:
    """Range passes values in bounds and rejects values outside them."""
    assert Schema(Range(min=0, max=10))(5) == 5
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Range(min=0, max=10))(11)
    assert isinstance(caught.value.errors[0], RangeInvalid)


def test_range_below_minimum() -> None:
    """A value under the minimum is rejected."""
    with pytest.raises(MultipleInvalid):
        Schema(Range(min=1))(0)


def test_range_exclusive_bounds() -> None:
    """Exclusive bounds reject the endpoint itself."""
    with pytest.raises(MultipleInvalid):
        Schema(Range(min=0, min_included=False))(0)
    with pytest.raises(MultipleInvalid):
        Schema(Range(max=10, max_included=False))(10)


def test_range_with_only_one_bound() -> None:
    """A range with a single bound checks just that bound."""
    assert Schema(Range(min=0))(5) == 5
    assert Schema(Range(max=10))(5) == 5


def test_range_exposes_its_bounds() -> None:
    """Range keeps min, max, and inclusivity for introspection."""
    rng = Range(min=0, max=10, max_included=False)

    assert rng.min == 0
    assert rng.max == 10
    assert rng.min_included is True
    assert rng.max_included is False


def test_clamp_limits_the_value() -> None:
    """Clamp pins a value into the range instead of failing."""
    assert Schema(Clamp(min=0, max=10))(20) == 10
    assert Schema(Clamp(min=0, max=10))(-5) == 0
    assert Schema(Clamp(min=0, max=10))(5) == 5


def test_length_bounds() -> None:
    """Length checks the length of a sized value."""
    assert Schema(Length(min=1, max=3))("ab") == "ab"
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Length(min=2))("a")
    assert isinstance(caught.value.errors[0], LengthInvalid)
    with pytest.raises(MultipleInvalid):
        Schema(Length(max=2))("abc")


def test_length_without_bounds_never_measures() -> None:
    """With no bound set, Length passes any value, even one without a length."""
    assert Schema(Length())(0.0) == 0.0
    assert Schema(Length())("anything") == "anything"


def test_in_membership() -> None:
    """In requires the value to be a member of the container."""
    assert Schema(In([1, 2, 3]))(2) == 2
    with pytest.raises(MultipleInvalid) as caught:
        Schema(In([1, 2, 3]))(9)
    assert isinstance(caught.value.errors[0], InInvalid)


def test_in_exposes_its_container() -> None:
    """In keeps its container for introspection."""
    assert In([1, 2]).container == [1, 2]


def test_in_suggests_close_members_on_a_miss() -> None:
    """A missed string value suggests the closest members and carries candidates."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(In(["auto", "manual"]))("atuo")

    error = caught.value.errors[0]
    assert isinstance(error, InInvalid)
    assert error.candidates == ["auto"]
    assert "did you mean 'auto'?" in error.error_message


def test_in_suggestion_surfaces_in_msg_and_context() -> None:
    """The lazily matched suggestion also reaches .msg, .context, and as_dict()."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(In(["auto", "manual"]))("atuo")

    error = caught.value.errors[0]
    assert "did you mean 'auto'?" in error.msg
    assert error.context["candidates"] == ["auto"]
    assert error.as_dict()["context"]["candidates"] == ["auto"]


def test_in_offers_no_suggestion_when_nothing_is_close() -> None:
    """A miss with no close member has empty candidates and no hint."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(In(["auto", "manual"]))("zzzzz")

    error = caught.value.errors[0]
    assert error.candidates == []
    assert "did you mean" not in error.error_message
    assert "candidates" not in error.context


def test_in_has_no_suggestions_for_non_string_members() -> None:
    """A non-string container yields no suggestions (difflib is string-only)."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(In([1, 2, 3]))(9)
    assert caught.value.errors[0].candidates == []


def test_in_custom_message_wins_but_keeps_candidates() -> None:
    """A custom message replaces the text, yet the candidates are still recorded."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(In(["auto"], msg="bad mode"))("atuo")

    error = caught.value.errors[0]
    assert error.error_message == "bad mode"
    assert error.candidates == ["auto"]


def test_in_fold_case_matches_and_returns_the_normalized_value() -> None:
    """fold_case matches case-insensitively and returns the folded value."""
    schema = Schema(In(["Auto", "Manual"], fold_case=True))

    assert schema("auto") == "auto"
    assert schema("MANUAL") == "manual"
    with pytest.raises(MultipleInvalid):
        schema("nope")


def test_in_space_normalizes_whitespace_runs() -> None:
    """space collapses each whitespace run to the given character before matching."""
    assert Schema(In(["a b"], space=" "))("a   b") == "a b"
    assert Schema(In(["front_door"], space="_"))("front door") == "front_door"


def test_in_normalization_leaves_a_non_string_value_alone() -> None:
    """A non-string value is matched as-is even with normalization enabled."""
    assert Schema(In([1, 2, 3], fold_case=True, space="_"))(2) == 2


def test_not_in_membership() -> None:
    """NotIn rejects values that are in the container."""
    assert Schema(NotIn(["a"]))("b") == "b"
    with pytest.raises(MultipleInvalid) as caught:
        Schema(NotIn(["a"]))("a")
    assert isinstance(caught.value.errors[0], NotInInvalid)


def test_in_handles_unhashable_value() -> None:
    """An unhashable value against a set container fails cleanly, not crashes."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(In({1, 2}))([3])
    assert isinstance(caught.value.errors[0], InInvalid)


def test_not_in_handles_unhashable_value() -> None:
    """An unhashable value against a set container fails cleanly, not crashes."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(NotIn({1, 2}))([3])
    assert isinstance(caught.value.errors[0], NotInInvalid)


def test_range_fails_cleanly_on_incomparable_value() -> None:
    """Range reports RangeInvalid, not a raw TypeError, on an incomparable value."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Range(min=0))("not a number")
    assert isinstance(caught.value.errors[0], RangeInvalid)


def test_range_rejects_nan() -> None:
    """NaN is outside every range (all comparisons are False), so it is rejected."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Range(min=0, max=10))(float("nan"))
    assert isinstance(caught.value.errors[0], RangeInvalid)


def test_clamp_fails_cleanly_on_incomparable_value() -> None:
    """Clamp reports RangeInvalid, not a raw TypeError, on an incomparable value."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Clamp(min=0))("not a number")
    assert isinstance(caught.value.errors[0], RangeInvalid)


def test_length_fails_cleanly_on_unsized_value() -> None:
    """Length reports LengthInvalid, not a raw TypeError, on a value with no len."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Length(min=1))(5)
    assert isinstance(caught.value.errors[0], LengthInvalid)


def test_positive_requires_greater_than_zero() -> None:
    """Positive accepts a number above zero and rejects zero or below."""
    assert Schema(Positive())(5) == 5
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Positive())(0)
    assert isinstance(caught.value.errors[0], RangeInvalid)


def test_non_negative_allows_zero() -> None:
    """NonNegative accepts zero and above, rejects negatives."""
    assert Schema(NonNegative())(0) == 0
    with pytest.raises(MultipleInvalid):
        Schema(NonNegative())(-1)


def test_negative_requires_less_than_zero() -> None:
    """Negative accepts a number below zero and rejects zero or above."""
    assert Schema(Negative())(-3) == -3
    with pytest.raises(MultipleInvalid):
        Schema(Negative())(0)


def test_multiple_of_accepts_a_multiple() -> None:
    """MultipleOf accepts an exact multiple and rejects the rest."""
    assert Schema(MultipleOf(5))(10) == 10
    with pytest.raises(MultipleInvalid) as caught:
        Schema(MultipleOf(5))(7)
    assert isinstance(caught.value.errors[0], MultipleOfInvalid)


@pytest.mark.parametrize("value", ["x", b"%", True, None])
def test_multiple_of_rejects_a_non_number(value: object) -> None:
    """A non-number (including a str, bytes, or bool) raises MultipleOfInvalid.

    ``%`` on a str/bytes is string formatting, not modulo, so those must be
    rejected by type rather than reaching the operator.
    """
    with pytest.raises(MultipleInvalid) as caught:
        Schema(MultipleOf(5))(value)
    assert isinstance(caught.value.errors[0], MultipleOfInvalid)


@pytest.mark.parametrize("factor", [0, "x"])
def test_multiple_of_rejects_a_bad_factor_at_build_time(factor: object) -> None:
    """A zero or non-numeric factor is a schema definition error."""
    with pytest.raises(SchemaError):
        MultipleOf(factor)


def test_percentage_validates_and_returns_unchanged() -> None:
    """Percentage accepts a number or a percent string and returns the value as given."""
    assert Schema(Percentage())(50) == 50
    assert Schema(Percentage())("75%") == "75%"
    assert Schema(Percentage())("20") == "20"


def test_from_percentage_parses_to_a_float() -> None:
    """FromPercentage parses a number, a percent string, or a numeric string to a float."""
    assert Schema(FromPercentage())(50) == 50.0
    assert Schema(FromPercentage())("75%") == 75.0
    assert Schema(FromPercentage())("20") == 20.0


def test_percentage_preserves_a_deliberate_invalid_from_float() -> None:
    """An Invalid raised by the value's own __float__ is kept, not masked as RangeInvalid."""

    class _RaisesInvalid:
        def __float__(self) -> float:
            message = "from __float__"
            raise Invalid(message)

    with pytest.raises(MultipleInvalid) as caught:
        Schema(Percentage())(_RaisesInvalid())
    error = caught.value.errors[0]
    assert not isinstance(error, RangeInvalid)
    assert error.error_message == "from __float__"


@pytest.mark.parametrize("validator", [Percentage, FromPercentage])
@pytest.mark.parametrize("value", [150, -1, "abc", True, False])
def test_percentage_rejects_out_of_range_or_non_numeric(
    validator: type,
    value: object,
) -> None:
    """A percentage outside 0..100, a non-numeric, or a bool raises RangeInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(validator())(value)
    assert isinstance(caught.value.errors[0], RangeInvalid)


@pytest.mark.parametrize("value", ["x", [1], {"a": 1}])
def test_non_empty_accepts_non_empty(value: object) -> None:
    """NonEmpty returns a value that has a non-zero length."""
    assert Schema(NonEmpty())(value) == value


@pytest.mark.parametrize("value", ["", [], {}, 5])
def test_non_empty_rejects_empty_or_unsized(value: object) -> None:
    """An empty or unsized value raises LengthInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(NonEmpty())(value)
    assert isinstance(caught.value.errors[0], LengthInvalid)


def test_byte_bounds() -> None:
    """Byte accepts 0..255 and rejects values outside it."""
    assert Schema(Byte())(0) == 0
    assert Schema(Byte())(255) == 255
    with pytest.raises(MultipleInvalid):
        Schema(Byte())(256)


def test_small_float_bounds() -> None:
    """SmallFloat accepts 0..1 and rejects values outside it."""
    assert Schema(SmallFloat())(0.5) == 0.5
    with pytest.raises(MultipleInvalid):
        Schema(SmallFloat())(2)


def test_latitude_and_longitude_bounds() -> None:
    """Latitude is -90..90 and Longitude is -180..180."""
    assert Schema(Latitude())(45.0) == 45.0
    assert Schema(Longitude())(-120) == -120
    with pytest.raises(MultipleInvalid):
        Schema(Latitude())(100)
    with pytest.raises(MultipleInvalid):
        Schema(Longitude())(200)


def test_membership_and_equality_reject_signaling_nan() -> None:
    """A signaling Decimal('sNaN') raises on every comparison; report it cleanly."""
    snan = Decimal("sNaN")

    for validator in (Equal(5), Literal(5), In([1, 2]), NotIn([1, 2])):
        with pytest.raises(Invalid):
            validator(snan)
    with pytest.raises(Invalid):
        Contains(snan)([1, 2])
