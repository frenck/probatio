"""Tests for the coercion validators (Coerce, Boolean)."""

from __future__ import annotations

import enum
from decimal import Decimal

import pytest
import voluptuous

from probatio import (
    PASSTHROUGH,
    Boolean,
    Coerce,
    DefaultTo,
    EmptyToNone,
    Map,
    MultipleInvalid,
    Number,
    Schema,
    SchemaError,
    SetTo,
)
from probatio.error import BooleanInvalid, CoerceInvalid, Invalid


def test_number_precision_and_scale() -> None:
    """Number checks total digits (precision) and decimal places (scale)."""
    assert Schema(Number(precision=6, scale=2))("1234.01") == "1234.01"

    with pytest.raises(MultipleInvalid) as caught:
        Schema(Number(precision=6, scale=2))("1.0")
    assert isinstance(caught.value.errors[0], Invalid)


def test_number_yields_decimal() -> None:
    """With yield_decimal the parsed Decimal is returned."""
    assert Schema(Number(yield_decimal=True))("1234.01") == Decimal("1234.01")


def test_number_rejects_nan_cleanly() -> None:
    """NaN and infinity have no precision and are rejected, not crashed on."""
    for value in ["NaN", "Infinity"]:
        with pytest.raises(MultipleInvalid) as caught:
            Schema(Number())(value)
        assert isinstance(caught.value.errors[0], Invalid)


@pytest.mark.parametrize("value", [None, {}, set(), b"x", [], ()])
def test_number_rejects_non_numeric_types_cleanly(value: object) -> None:
    """A non-numeric type yields Invalid, not a leaked TypeError/ValueError.

    Mirrors voluptuous PR #539: ``Decimal(value)`` raises ``TypeError`` for
    None/dict/set/bytes and ``ValueError`` for empty sequences. probatio catches
    both, so every non-numeric input reports a clean Invalid.
    """
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Number(precision=6, scale=2))(value)
    assert isinstance(caught.value.errors[0], Invalid)


def test_number_rejects_a_decimal_tuple_spec_without_overflow() -> None:
    """A 3-element sequence is read by Decimal as (sign, digits, exponent).

    A huge exponent there overflows the C long (an OverflowError). Found by the
    fuzz harness; it must surface as a clean Invalid, not leak.
    """
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Number())([0, (1, 2), 10**400])
    assert isinstance(caught.value.errors[0], Invalid)


def test_number_matches_voluptuous() -> None:
    """Number agrees with voluptuous on accept/reject for precision/scale."""
    cases = ["1234.01", "1.0", "12", "abc", "12.345"]
    for spec in [{}, {"precision": 6, "scale": 2}, {"scale": 1}]:
        prob = Schema(Number(**spec))
        vol = voluptuous.Schema(voluptuous.Number(**spec))
        for value in cases:
            prob_ok = _accepts(prob, value)
            vol_ok = _accepts(vol, value)
            assert prob_ok == vol_ok, (spec, value, prob_ok, vol_ok)


def _accepts(schema: object, value: str) -> bool:
    """Return whether the schema accepts the value (any failure counts as no)."""
    try:
        schema(value)  # type: ignore[operator]
    except Exception:  # noqa: BLE001
        return False
    return True


def test_set_to_ignores_input() -> None:
    """SetTo returns its fixed value regardless of the input."""
    assert Schema(SetTo(42))("anything") == 42


def test_default_to_replaces_none() -> None:
    """DefaultTo replaces None and passes other values through."""
    assert Schema(DefaultTo("fallback"))(None) == "fallback"
    assert Schema(DefaultTo("fallback"))("given") == "given"


def test_coerce_converts_the_value() -> None:
    """Coerce returns the value converted to the target type."""
    assert Schema(Coerce(int))("42") == 42


def test_coerce_failure_is_reported() -> None:
    """A failed conversion raises CoerceInvalid, not a bare ValueError."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Coerce(int))("nope")
    assert isinstance(caught.value.errors[0], CoerceInvalid)


def test_coerce_passes_through_an_instance_the_constructor_rejects() -> None:
    """A value already of the target type is returned as-is, so Coerce is idempotent."""
    import uuid  # noqa: PLC0415

    value = uuid.uuid4()
    assert Schema(Coerce(uuid.UUID))(value) is value
    # A string still parses to the object, so the coercion itself is unaffected.
    assert Schema(Coerce(uuid.UUID))(str(value)) == value


def test_coerce_exposes_its_type() -> None:
    """Coerce keeps its target type for introspection."""
    assert Coerce(int).type is int


class _Color(enum.Enum):
    """A small enum for the Coerce-of-enum message tests."""

    RED = "red"
    GREEN = "green"
    BLUE = "blue"


def test_coerce_enum_message_lists_the_values() -> None:
    """Coercing to an enum names the valid values, matching voluptuous."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Coerce(_Color))("purple")
    with pytest.raises(voluptuous.MultipleInvalid) as oracle:
        voluptuous.Schema(voluptuous.Coerce(_Color))("purple")

    assert (
        str(caught.value.errors[0])
        == "expected _Color or one of 'red', 'green', 'blue'"
    )
    assert str(caught.value.errors[0]) == str(oracle.value.errors[0])


def test_coerce_enum_custom_message_does_not_append_values() -> None:
    """A custom message replaces the default; the values are not appended."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Coerce(_Color, msg="bad color"))("purple")
    assert str(caught.value.errors[0]) == "bad color"


def test_coerce_enum_suggests_a_close_value() -> None:
    """A near-miss against an enum's string values gets a 'did you mean ...?' hint."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Coerce(_Color))("gren")

    error = caught.value.errors[0]
    assert isinstance(error, CoerceInvalid)
    assert error.candidates == ["green"]
    assert "did you mean 'green'?" in error.error_message


def test_coerce_enum_no_suggestion_when_nothing_is_close() -> None:
    """A far-off value gets no hint and no candidates, matching the value listing."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Coerce(_Color))("purple")

    error = caught.value.errors[0]
    assert error.candidates == []
    assert "did you mean" not in error.error_message


def test_coerce_enum_custom_message_keeps_candidates() -> None:
    """A custom message wins the text, yet the close matches are still recorded."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Coerce(_Color, msg="bad color"))("gren")
    assert caught.value.errors[0].candidates == ["green"]


def test_coerce_int_enum_has_no_suggestions() -> None:
    """An IntEnum has non-string values, so difflib offers nothing."""

    class _Size(enum.IntEnum):
        SMALL = 1
        LARGE = 2

    with pytest.raises(MultipleInvalid) as caught:
        Schema(Coerce(_Size))("small")

    assert caught.value.errors[0].candidates == []


def test_coerce_non_enum_failure_has_no_candidates() -> None:
    """A plain coercion failure carries an empty candidates list."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Coerce(int))("abc")
    assert caught.value.errors[0].candidates == []


def test_boolean_truthy_and_falsy_strings() -> None:
    """Boolean reads common truthy and falsy strings."""
    assert Schema(Boolean())("yes") is True
    assert Schema(Boolean())("off") is False
    assert Schema(Boolean())(1) is True


def test_boolean_rejects_unknown_strings() -> None:
    """An unrecognized string raises BooleanInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Boolean())("maybe")
    assert isinstance(caught.value.errors[0], BooleanInvalid)


def test_boolean_message_can_be_overridden() -> None:
    """Boolean is a factory, so its message and class can be customized per use."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Boolean("not a flag"))("maybe")
    assert str(caught.value.errors[0]) == "not a flag"


def test_coerce_decimal_fails_cleanly_on_junk() -> None:
    """Coerce(Decimal) maps decimal.InvalidOperation to CoerceInvalid, not a leak."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Coerce(Decimal))("not-a-decimal")
    assert isinstance(caught.value.errors[0], CoerceInvalid)


def test_coerce_int_fails_cleanly_on_infinity() -> None:
    """Coerce(int) maps OverflowError (infinity) to CoerceInvalid, not a leak."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Coerce(int))(float("inf"))
    assert isinstance(caught.value.errors[0], CoerceInvalid)


def test_map_translates_a_known_value() -> None:
    """Map returns the mapped value for a key it knows."""
    status = Map({0: "off", 1: "on", 2: "auto"})
    assert Schema(status)(0) == "off"
    assert Schema(status)(2) == "auto"


def test_map_rejects_an_unknown_value() -> None:
    """A value not in the mapping is rejected when no default is set."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Map({0: "off", 1: "on"}))(9)
    assert isinstance(caught.value.errors[0], Invalid)


def test_map_uses_a_default_on_a_miss() -> None:
    """With a default, an unknown value returns the default instead of failing."""
    assert Schema(Map({0: "off"}, default="unknown"))(9) == "unknown"


def test_map_treats_an_unhashable_value_as_a_miss() -> None:
    """An unhashable value cannot be a mapping key, so it is a miss."""
    with pytest.raises(MultipleInvalid):
        Schema(Map({0: "off"}))([1, 2])
    assert Schema(Map({0: "off"}, default=None))([1, 2]) is None


def test_map_passthrough_returns_an_unmapped_value_unchanged() -> None:
    """With default=PASSTHROUGH, a miss returns the value as-is, a hit still maps."""
    remap = Map({"N.v.t.": None, "Niet geregistreerd": None}, default=PASSTHROUGH)
    assert Schema(remap)("N.v.t.") is None
    assert Schema(remap)("Personenauto") == "Personenauto"


def test_map_passthrough_returns_an_unhashable_value_unchanged() -> None:
    """PASSTHROUGH leaves even an unhashable miss alone rather than rejecting it."""
    assert Schema(Map({0: "off"}, default=PASSTHROUGH))([1, 2]) == [1, 2]


def test_passthrough_repr() -> None:
    """The PASSTHROUGH sentinel renders as its name."""
    assert repr(PASSTHROUGH) == "PASSTHROUGH"


def test_map_rejects_a_non_dict_mapping_at_build_time() -> None:
    """A mapping that is not a dict is a schema error, raised when the validator is built."""
    with pytest.raises(SchemaError):
        Map([1, 2, 3])  # type: ignore[arg-type]


def test_map_repr() -> None:
    """Map renders as a constructor call showing the mapping."""
    assert repr(Map({1: "a"})) == "Map({1: 'a'})"


def test_empty_to_none_replaces_empties() -> None:
    """An empty string or container becomes None; other values pass through."""
    assert Schema(EmptyToNone())("") is None
    assert Schema(EmptyToNone())([]) is None
    assert Schema(EmptyToNone())({}) is None
    assert Schema(EmptyToNone())("x") == "x"
    assert Schema(EmptyToNone())([1]) == [1]


def test_empty_to_none_leaves_a_falsy_scalar_alone() -> None:
    """0, False, and None are values, not empties, so they pass through unchanged."""
    assert Schema(EmptyToNone())(0) == 0
    assert Schema(EmptyToNone())(False) is False
    assert Schema(EmptyToNone())(None) is None


def test_empty_to_none_repr() -> None:
    """EmptyToNone renders as a constructor call."""
    assert repr(EmptyToNone()) == "EmptyToNone()"
