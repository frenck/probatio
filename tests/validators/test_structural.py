"""Tests for ExactSequence, Unique, Maybe, and Msg."""

from __future__ import annotations

from collections import namedtuple
from typing import Self

import pytest

from probatio import (
    EnsureList,
    ExactSequence,
    Maybe,
    Msg,
    MultipleInvalid,
    Schema,
    Set,
    Sorted,
    Unique,
    Unordered,
)
from probatio.error import ExactSequenceInvalid, Invalid, TypeInvalid, ValueInvalid


def test_exact_sequence_matches_positionally() -> None:
    """ExactSequence validates each position against its own schema."""
    assert Schema(ExactSequence([int, str]))([1, "a"]) == [1, "a"]


def test_exact_sequence_rejects_wrong_length() -> None:
    """A sequence of the wrong length is rejected."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(ExactSequence([int, str]))([1])
    assert isinstance(caught.value.errors[0], ExactSequenceInvalid)


def test_exact_sequence_keeps_the_type() -> None:
    """A tuple in yields a tuple out."""
    result = Schema(ExactSequence([int, int]))((1, 2))
    assert result == (1, 2)
    assert isinstance(result, tuple)


def test_exact_sequence_rebuilds_a_namedtuple() -> None:
    """A namedtuple is rebuilt with positional fields, not leaked as a TypeError.

    ``Point(result)`` would pass the list as a single field; a namedtuple needs its
    fields spread positionally.
    """
    point = namedtuple("Point", "x y")  # noqa: PYI024 - a runtime namedtuple fixture

    result = Schema(ExactSequence([int, int]))(point(1, 2))

    assert result == point(1, 2)
    assert isinstance(result, point)


def test_exact_sequence_falls_back_when_a_subclass_cannot_rebuild() -> None:
    """A list/tuple subclass whose constructor is not (iterable) does not leak.

    ``type(value)(result)`` would raise a raw ``TypeError`` for a subclass with a
    custom constructor; the rebuild falls back to the plain base type instead.
    """

    class TaggedList(list):
        def __init__(self, items: object, tag: object) -> None:
            super().__init__(items)  # type: ignore[arg-type]
            self.tag = tag

    class Pair(tuple):
        __slots__ = ()

        def __new__(cls, a: object, b: object) -> Self:
            return super().__new__(cls, (a, b))

    from_list = Schema(ExactSequence([int]))(TaggedList([1], "x"))
    assert from_list == [1]
    assert type(from_list) is list

    from_tuple = Schema(ExactSequence([int, int]))(Pair(1, 2))
    assert from_tuple == (1, 2)
    assert type(from_tuple) is tuple


def test_exact_sequence_item_error_has_index() -> None:
    """A bad item reports its index in the path."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(ExactSequence([int, str]))([1, 2])
    assert caught.value.errors[0].path == [1]


def test_unique_accepts_distinct_items() -> None:
    """Unique passes a list with no duplicates."""
    assert Schema(Unique())([1, 2, 3]) == [1, 2, 3]


def test_unique_rejects_duplicates() -> None:
    """Unique rejects a list containing a duplicate."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Unique())([1, 2, 1])
    assert isinstance(caught.value.errors[0], Invalid)


def test_unique_lists_the_duplicates() -> None:
    """The duplicate-items message names the offending value."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Unique())([1, 1, 2])
    assert caught.value.errors[0].error_message == "contains duplicate items: [1]"


def test_unique_reports_unhashable_as_type_error() -> None:
    """An unhashable element is a TypeInvalid, not a leaked TypeError."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Unique())([{1, 2}, {3, 4}])
    assert isinstance(caught.value.errors[0], TypeInvalid)


def test_set_converts_a_list() -> None:
    """Set turns an iterable into a set, dropping duplicates."""
    assert Schema(Set())([1, 2, 2]) == {1, 2}


def test_set_rejects_unhashable_items() -> None:
    """A list of unhashable items cannot become a set."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Set())([{1, 2}])
    assert isinstance(caught.value.errors[0], TypeInvalid)


def test_unordered_matches_in_any_order() -> None:
    """Unordered accepts the items in any order against the validators."""
    assert Schema(Unordered([str, int]))([1, "a"]) == [1, "a"]
    assert Schema(Unordered([str, int]))(["a", 1]) == ["a", 1]


def test_unordered_rejects_a_non_sequence() -> None:
    """A value that is not a list or tuple is rejected."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Unordered([str, int]))("ab")
    assert caught.value.errors[0].error_message == "expected a sequence"


def test_unordered_rejects_a_length_mismatch() -> None:
    """The sequence length must equal the validator count."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Unordered([str, int]))([1])
    assert caught.value.errors[0].error_message == "expected a sequence of 2 items"


def test_unordered_reports_one_unmatched_element() -> None:
    """A single unmatched element names its index in the message."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Unordered([str, int]))([1, 2])
    assert (
        "item 1 (2) does not match any validator"
        in caught.value.errors[0].error_message
    )


def test_unordered_reports_several_unmatched_elements() -> None:
    """Several unmatched elements each get their own error."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Unordered([str, str]))([1, 2])
    assert len(caught.value.errors) == 2


def test_maybe_allows_none() -> None:
    """Maybe lets None through and otherwise validates."""
    assert Schema(Maybe(int))(None) is None
    assert Schema(Maybe(int))(5) == 5


def test_maybe_rejects_a_bad_non_none_value() -> None:
    """A non-None value still has to satisfy the wrapped validator."""
    with pytest.raises(MultipleInvalid):
        Schema(Maybe(int))("x")


def test_maybe_custom_message() -> None:
    """A msg on Maybe replaces the failure message for non-None values."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Maybe(int, msg="optional whole number"))("x")
    assert caught.value.errors[0].error_message == "optional whole number"


def test_msg_replaces_the_error_message() -> None:
    """Msg overrides the failure message of its validator."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Msg(int, "must be a whole number"))("x")
    assert caught.value.errors[0].error_message == "must be a whole number"


def test_unique_fails_cleanly_on_non_iterable() -> None:
    """Unique reports Invalid, not a raw TypeError, on a non-iterable value."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Unique())(5)
    assert isinstance(caught.value.errors[0], Invalid)


def test_unique_handles_a_generator_without_leaking() -> None:
    """Unique on an unsized iterable (a generator) does not leak a TypeError."""

    def gen_dupe() -> object:
        yield 1
        yield 1

    with pytest.raises(MultipleInvalid) as caught:
        Schema(Unique())(gen_dupe())
    assert isinstance(caught.value.errors[0], Invalid)

    def gen_ok() -> object:
        yield 1
        yield 2

    # A unique generator passes (materialized to a list so the result is usable).
    assert Schema(Unique())(gen_ok()) == [1, 2]


def test_ensure_list_wraps_a_scalar() -> None:
    """EnsureList wraps a scalar into a single-item list."""
    assert Schema(EnsureList())("x") == ["x"]


def test_ensure_list_passes_a_list_through() -> None:
    """An existing list is returned unchanged."""
    assert Schema(EnsureList())([1, 2]) == [1, 2]


def test_ensure_list_turns_none_into_empty() -> None:
    """None becomes an empty list."""
    assert Schema(EnsureList())(None) == []


def test_sorted_accepts_ordered_and_rejects_unordered() -> None:
    """Sorted accepts an ascending sequence and rejects an unordered one."""
    assert Schema(Sorted())([1, 2, 3]) == [1, 2, 3]

    with pytest.raises(MultipleInvalid) as caught:
        Schema(Sorted())([3, 1, 2])
    assert isinstance(caught.value.errors[0], ValueInvalid)


def test_sorted_rejects_an_unsortable_value() -> None:
    """A non-iterable or incomparable value raises ValueInvalid, not a TypeError."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Sorted())(5)
    assert isinstance(caught.value.errors[0], ValueInvalid)
