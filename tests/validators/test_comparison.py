"""Tests for the range, length, and membership validators."""

from __future__ import annotations

from decimal import Decimal

import pytest

from probatio import (
    Abs,
    Byte,
    Clamp,
    Contains,
    Divide,
    Equal,
    FromPercentage,
    In,
    Latitude,
    Length,
    Literal,
    Longitude,
    Modulo,
    MultipleInvalid,
    MultipleOf,
    Multiply,
    Negative,
    NonEmpty,
    NonNegative,
    NotIn,
    Offset,
    Percentage,
    Positive,
    Range,
    Remap,
    Round,
    RoundDown,
    RoundUp,
    Scale,
    Schema,
    SchemaError,
    SmallFloat,
    Snap,
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
    ValueInvalid,
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


@pytest.mark.parametrize("bound", ["x", Decimal("NaN")])
def test_length_with_a_bad_bound_is_invalid_not_a_leak(bound: object) -> None:
    """A bad bound (a str TypeError, a Decimal NaN ArithmeticError) is clean, not a leak."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Length(min=bound))("abc")
    assert isinstance(caught.value.errors[0], LengthInvalid)


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


@pytest.mark.parametrize("factor", [0, "x", 0.1, 2.5, float("nan"), float("inf")])
def test_multiple_of_rejects_a_bad_factor_at_build_time(factor: object) -> None:
    """A zero, fractional, or non-numeric factor is a schema definition error.

    A fractional factor has no meaning for an integer-multiple check, and its float
    ``%`` would mis-reject exact multiples through representation error, so it is
    refused at build time rather than silently accepted.
    """
    with pytest.raises(SchemaError):
        MultipleOf(factor)


def test_multiple_of_normalizes_an_integer_valued_float_factor() -> None:
    """An integer-valued float factor (2.0) is accepted and stored as an int."""
    validator = MultipleOf(2.0)
    assert validator.factor == 2
    assert isinstance(validator.factor, int)
    assert Schema(validator)(4) == 4


def test_multiple_of_contains_a_hostile_int_subclass_mod() -> None:
    """An int subclass whose __mod__ raises yields Invalid, not a leaked exception."""

    class _BadInt(int):
        def __mod__(self, _other: object) -> int:
            message = "hostile mod"
            raise RuntimeError(message)

    with pytest.raises(MultipleInvalid) as caught:
        Schema(MultipleOf(3))(_BadInt(9))
    assert isinstance(caught.value.errors[0], MultipleOfInvalid)


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


def test_scale_divides_and_yields_a_float() -> None:
    """A divisor rescales the value, producing a float (5000 milliunits to 5.0)."""
    assert Schema(Scale(divisor=1000))(5000) == 5.0


def test_scale_integer_multiply_keeps_an_int() -> None:
    """A pure integer factor on an int keeps Python's int result."""
    result = Schema(Scale(10))(5)
    assert result == 50
    assert type(result) is int


def test_scale_byte_to_percentage_with_rounding() -> None:
    """A 0..255 byte scales to a rounded percentage (128 to 50.2)."""
    assert Schema(Scale(100, divisor=255, round=1))(128) == 50.2


def test_scale_applies_an_offset() -> None:
    """An offset shifts the value (Kelvin 300 to 26.85 Celsius, rounded)."""
    assert Schema(Scale(offset=-273.15, round=2))(300) == 26.85


@pytest.mark.parametrize("value", [True, False, "5", None])
def test_scale_rejects_a_non_number(value: object) -> None:
    """A bool, a string, or None is not a number to rescale, so it is rejected."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Scale(divisor=10))(value)
    assert isinstance(caught.value.errors[0], ValueInvalid)


def test_scale_contains_an_overflow() -> None:
    """A huge int that overflows the float division is reported cleanly, not leaked."""
    with pytest.raises(MultipleInvalid):
        Schema(Scale(divisor=1000))(10**400)


def test_scale_rejects_a_bad_configuration_at_build_time() -> None:
    """A zero divisor or a non-integer round is a schema error, raised when built."""
    with pytest.raises(SchemaError):
        Scale(divisor=0)
    with pytest.raises(SchemaError):
        Scale(round=1.5)


def test_scale_repr() -> None:
    """Scale renders as a constructor call showing the transform."""
    assert repr(Scale(100, divisor=255, round=1)) == (
        "Scale(factor=100, divisor=255, offset=0, round=1)"
    )


def test_multiply_scales_a_number() -> None:
    """Multiply applies a factor; an integer factor on an int keeps an int."""
    assert Schema(Multiply(0.1))(50) == 5.0
    kept = Schema(Multiply(3))(4)
    assert kept == 12
    assert type(kept) is int


def test_divide_yields_a_float_and_rejects_zero_divisor() -> None:
    """Divide converts milliunits to units; a zero divisor is a build-time error."""
    assert Schema(Divide(1000))(5000) == 5.0
    with pytest.raises(SchemaError):
        Divide(0)


def test_offset_shifts_a_number() -> None:
    """Offset adds an amount (negative to subtract), keeping an int when it can."""
    assert Schema(Offset(-273.15))(300) == pytest.approx(26.85)
    kept = Schema(Offset(5))(10)
    assert kept == 15
    assert type(kept) is int


def test_round_to_decimals_and_to_integer() -> None:
    """Round keeps decimals with ndigits, or rounds to the nearest int by default."""
    assert Schema(Round(2))(5.126) == 5.13
    assert Schema(Round())(5.6) == 6
    with pytest.raises(SchemaError):
        Round(1.5)


def test_arithmetic_mutator_reprs() -> None:
    """Each mutator renders as a constructor call for introspection."""
    assert repr(Multiply(0.1)) == "Multiply(0.1)"
    assert repr(Divide(1000)) == "Divide(1000)"
    assert repr(Offset(-273.15)) == "Offset(-273.15)"
    assert repr(Round(2)) == "Round(2)"
    assert repr(Remap(0, 1023, 0, 100)) == (
        "Remap(in_low=0, in_high=1023, out_low=0, out_high=100)"
    )


def test_remap_maps_between_ranges() -> None:
    """Remap linearly maps a value from an input range onto an output range."""
    assert Schema(Remap(0, 1023, 0, 100))(1023) == 100.0
    assert Schema(Remap(0, 10, 0, 100))(5) == 50.0


def test_remap_rejects_a_zero_width_input_range() -> None:
    """A zero-width input range would divide by zero, so it is a build-time error."""
    with pytest.raises(SchemaError):
        Remap(5, 5, 0, 100)


@pytest.mark.parametrize(
    "mutator", [Multiply(2), Divide(2), Offset(2), Round(), Remap(0, 1, 0, 1)]
)
def test_arithmetic_mutators_reject_a_non_number(mutator: object) -> None:
    """Every arithmetic mutator rejects a string rather than mishandling it."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(mutator)("x")
    assert isinstance(caught.value.errors[0], ValueInvalid)


@pytest.mark.parametrize(
    ("mutator", "value"),
    [
        (Multiply(1.0), 10**400),
        (Divide(2), 10**400),
        (Offset(1.0), 10**400),
        (Round(), float("inf")),
        (Remap(0, 1, 0, 1), 10**400),
    ],
)
def test_arithmetic_mutators_contain_an_overflow(
    mutator: object, value: object
) -> None:
    """A value that overflows the float arithmetic is reported cleanly, not leaked."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(mutator)(value)
    assert isinstance(caught.value.errors[0], ValueInvalid)


def test_snap_rounds_to_the_nearest_step() -> None:
    """Snap quantizes to the nearest multiple of the step, keeping int for an int step."""
    assert Schema(Snap(0.5))(1.2) == 1.0
    kept = Schema(Snap(5))(23)
    assert kept == 25
    assert type(kept) is int
    with pytest.raises(SchemaError):
        Snap(0)


def test_round_up_and_down_go_to_the_whole_integer() -> None:
    """RoundUp takes the ceiling, RoundDown the floor, both returning an int."""
    assert Schema(RoundUp())(4.1) == 5
    assert Schema(RoundUp())(-4.9) == -4
    assert Schema(RoundDown())(4.9) == 4
    assert Schema(RoundDown())(-4.1) == -5


def test_abs_returns_the_magnitude() -> None:
    """Abs returns the absolute value, keeping the type."""
    result = Schema(Abs())(-3)
    assert result == 3
    assert type(result) is int


def test_modulo_wraps_around() -> None:
    """Modulo reduces value % n, following the divisor's sign for wrap-around."""
    assert Schema(Modulo(360))(370) == 10
    assert Schema(Modulo(360))(-10) == 350
    with pytest.raises(SchemaError):
        Modulo(0)


@pytest.mark.parametrize(
    "mutator", [Snap(0.5), RoundUp(), RoundDown(), Abs(), Modulo(5)]
)
def test_numeric_finishers_reject_a_non_number(mutator: object) -> None:
    """Every numeric finisher rejects a string rather than mishandling it."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(mutator)("x")
    assert isinstance(caught.value.errors[0], ValueInvalid)


@pytest.mark.parametrize(
    ("mutator", "value"),
    [
        (Snap(0.5), 10**400),
        (RoundUp(), float("inf")),
        (RoundDown(), float("inf")),
        (Modulo(1.5), 10**400),
    ],
)
def test_numeric_finishers_contain_a_bad_value(mutator: object, value: object) -> None:
    """An overflow or an unrepresentable infinity is reported cleanly, not leaked."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(mutator)(value)
    assert isinstance(caught.value.errors[0], ValueInvalid)


def test_numeric_finisher_reprs() -> None:
    """Each numeric finisher renders as a constructor call for introspection."""
    assert repr(Snap(0.5)) == "Snap(0.5)"
    assert repr(RoundUp()) == "RoundUp()"
    assert repr(RoundDown()) == "RoundDown()"
    assert repr(Abs()) == "Abs()"
    assert repr(Modulo(360)) == "Modulo(360)"


def test_membership_and_equality_reject_signaling_nan() -> None:
    """A signaling Decimal('sNaN') raises on every comparison; report it cleanly."""
    snan = Decimal("sNaN")

    for validator in (Equal(5), Literal(5), In([1, 2]), NotIn([1, 2])):
        with pytest.raises(Invalid):
            validator(snan)
    with pytest.raises(Invalid):
        Contains(snan)([1, 2])
