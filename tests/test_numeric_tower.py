"""The PEP 484 numeric tower for a bare float: an int is accepted and normalized.

A ``float`` schema accepts an ``int`` and returns it as a ``float``, on every path
a bare type reaches (a scalar ``Schema``, a mapping value, a sequence element, a
dataclass field, a union base). ``bool`` is excluded and everything else is rejected
as before. This is a deliberate deviation from voluptuous (ADR-017).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from probatio import (
    Any,
    DataclassSchema,
    MultipleInvalid,
    Remove,
    Schema,
    to_json_schema,
)


def test_schema_float_accepts_an_int_and_normalizes_it() -> None:
    """Schema(float) takes an int and returns a float, not the int."""
    result = Schema(float)(5)
    assert result == 5.0
    assert type(result) is float


def test_schema_float_passes_a_float_through() -> None:
    """A float is returned unchanged."""
    assert Schema(float)(5.0) == 5.0


def test_schema_float_accepts_a_float_subclass_unchanged() -> None:
    """A float subclass is a float, so it passes through as-is (not re-boxed)."""

    class Weight(float):
        """A float subclass standing in for a numpy-style scalar."""

    value = Weight(2.5)
    assert Schema(float)(value) is value


@pytest.mark.parametrize("value", [True, False, "5", None, 5j])
def test_schema_float_rejects_non_numbers_and_bool(value: object) -> None:
    """bool, a string, None, and a complex are not floats and are rejected."""
    with pytest.raises(MultipleInvalid):
        Schema(float)(value)


def test_tower_applies_to_a_mapping_value() -> None:
    """{str: float} coerces an int value to a float."""
    assert Schema({str: float})({"a": 1}) == {"a": 1.0}


def test_tower_applies_to_a_sequence_element() -> None:
    """[float] coerces each int element to a float, order kept."""
    assert Schema([float])([1, 2.0, 3]) == [1.0, 2.0, 3.0]


def test_tower_applies_to_a_mapping_type_key() -> None:
    """A {float: ...} type key matches an int key and normalizes it to a float."""
    assert Schema({float: str})({5: "x"}) == {5.0: "x"}
    with pytest.raises(MultipleInvalid):
        Schema({float: str})({"k": "x"})


@dataclass
class Reading:
    """A dataclass with a bare float field and an optional float field."""

    value: float
    trim: float | None = None


def test_tower_applies_to_a_dataclass_field() -> None:
    """A float field accepts an int and stores a float."""
    result = DataclassSchema(Reading)({"value": 5})
    assert result == Reading(value=5.0)
    assert type(result.value) is float


def test_tower_applies_under_a_union_base() -> None:
    """A float | None field coerces an int and still accepts None."""
    assert DataclassSchema(Reading)({"value": 1, "trim": 2}) == Reading(1.0, 2.0)
    assert DataclassSchema(Reading)({"value": 1, "trim": None}) == Reading(1.0, None)


def test_a_dataclass_float_field_still_rejects_a_string() -> None:
    """The tower only reaches int; a string in a float field is still rejected."""
    with pytest.raises(MultipleInvalid) as caught:
        DataclassSchema(Reading)({"value": "5"})
    assert caught.value.errors[0].path == ["value"]


def test_runtime_agrees_with_the_emitted_json_schema() -> None:
    """to_json_schema emits {'type': 'number'}, which accepts an int, and now so does the validator."""
    assert to_json_schema(Schema(float)) == {"type": "number"}
    assert Schema(float)(5) == 5.0


def test_an_integer_too_large_for_a_float_is_rejected_cleanly() -> None:
    """A huge int (10**400 overflows float()) raises Invalid, not a raw OverflowError."""
    with pytest.raises(MultipleInvalid):
        Schema(float)(10**400)
    with pytest.raises(MultipleInvalid):
        Schema([float])([10**400])


def test_a_float_matcher_drops_matching_ints() -> None:
    """Remove(float) in a list drops ints too, since an int is now a valid float match."""
    assert Schema([Remove(float), str])([1, 2.0, "keep"]) == ["keep"]


def test_an_any_of_types_and_float_keeps_branch_order() -> None:
    """In an Any, the first matching branch wins, so int-before-float keeps the int."""
    assert Schema(Any(float, int))(5) == 5.0  # float first: coerced
    assert type(Schema(Any(float, int))(5)) is float
    assert Schema(Any(int, float))(5) == 5  # int first: unchanged
    assert type(Schema(Any(int, float))(5)) is int


def test_an_any_of_types_and_float_coerces_or_misses() -> None:
    """A float branch in an Any coerces an int, excludes bool, and misses cleanly."""
    assert Schema(Any(float, str))(5) == 5.0
    with pytest.raises(MultipleInvalid):
        Schema(Any(float, str))(True)
    with pytest.raises(MultipleInvalid):
        Schema(Any(int, float, str))(None)


def test_a_custom_msg_is_used_on_a_float_any_miss() -> None:
    """A custom msg on an Any with a float branch is raised on the fast miss path."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Any(int, float, str, msg="nope"))(None)
    assert caught.value.errors[0].error_message == "nope"


def test_complex_does_not_yet_honor_the_tower() -> None:
    """complex is a deferred tower step (ADR-017): a float is still rejected there."""
    with pytest.raises(MultipleInvalid):
        Schema(complex)(5.0)
