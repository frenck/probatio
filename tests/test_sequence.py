"""Tests for sequence and set schemas."""

from __future__ import annotations

import collections

import pytest

from probatio import Coerce, MultipleInvalid, Remove, Schema
from probatio.error import SequenceTypeInvalid


def test_list_of_one_type() -> None:
    """A single-element-schema list validates every item against it."""
    assert Schema([int])([1, 2, 3]) == [1, 2, 3]


def test_list_item_error_carries_the_index() -> None:
    """A bad item reports its index in the path with a precise message."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema([int])([1, "x", 3])
    error = caught.value.errors[0]
    assert error.path == [1]
    assert error.error_message == "expected int"


def test_list_accepts_any_listed_element_schema() -> None:
    """Each item may match any of the element schemas, tried in order."""
    assert Schema([int, str])([1, "a", 2]) == [1, "a", 2]


def test_list_item_matching_no_schema_is_reported() -> None:
    """An item matching none of several schemas is flagged at its index."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema([int, str])([1.5])
    assert caught.value.errors[0].path == [0]


def test_wrong_sequence_type_is_rejected() -> None:
    """A list schema rejects non-list data."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema([int])("not a list")
    assert isinstance(caught.value.errors[0], SequenceTypeInvalid)


def test_tuple_schema_keeps_the_tuple_type() -> None:
    """A tuple schema validates a tuple and returns a tuple."""
    result = Schema((int,))((1, 2, 3))
    assert result == (1, 2, 3)
    assert isinstance(result, tuple)


def test_remove_drops_matching_list_items_by_value() -> None:
    """A Remove element strips items equal to it, keeping the rest validated."""
    assert Schema([Remove(1), int])([1, 2, 3, 4, 1, 5, 6, 1, 1, 1]) == [2, 3, 4, 5, 6]


def test_remove_drops_matching_list_items_by_type() -> None:
    """A Remove element matching by type drops those items, order respected."""
    assert Schema([1.0, Remove(float), int])([1, 2, 1.0, 2.0, 3.0, 4]) == [1, 2, 1.0, 4]


def test_namedtuple_data_round_trips_through_a_tuple_schema() -> None:
    """A namedtuple validates against a tuple schema and rebuilds as itself."""
    point = collections.namedtuple("Point", ["x", "y"])  # noqa: PYI024
    result = Schema((int, int))(point(1, 2))
    assert result == (1, 2)
    assert isinstance(result, point)


def test_namedtuple_schema_accepts_a_plain_tuple() -> None:
    """A schema written as a namedtuple matches any tuple, like voluptuous."""
    point = collections.namedtuple("Point", ["x", "y"])  # noqa: PYI024
    assert Schema(point(int, int))((1, 2)) == (1, 2)
    rebuilt = Schema(point(int, int))(point(1, 2))
    assert isinstance(rebuilt, point)


def test_list_subclass_that_cannot_rebuild_falls_back_to_a_plain_list() -> None:
    """A list subclass with a non-(iterable) constructor rebuilds to a plain list, not a leak."""

    class TaggedList(list):
        def __init__(self, items: object, tag: object) -> None:
            super().__init__(items)  # type: ignore[arg-type]
            self.tag = tag

    result = Schema([int])(TaggedList([1, 2], "x"))
    assert result == [1, 2]
    assert type(result) is list


def test_set_schema_keeps_the_set_type() -> None:
    """A set schema validates a set and returns a set."""
    result = Schema({int})({1, 2, 3})
    assert result == {1, 2, 3}
    assert isinstance(result, set)


def test_set_schema_coerces_its_elements() -> None:
    """A transforming element schema runs on set items too (voluptuous issue #400).

    voluptuous returns set elements untransformed; probatio applies the element
    schema to a set the same way it does to a list, so a Coerce actually coerces.
    """
    result = Schema({Coerce(int)})({"1", "2", "3"})
    assert result == {1, 2, 3}
    assert all(isinstance(item, int) for item in result)


def test_empty_list_schema_accepts_only_empty_list() -> None:
    """An empty list schema allows no items."""
    assert Schema([])([]) == []
    with pytest.raises(MultipleInvalid) as caught:
        Schema([])([1])
    assert caught.value.errors[0].path == [0]


def test_nested_mapping_in_a_list_reports_full_path() -> None:
    """A failing nested mapping reports index and key together."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema([{"x": int}])([{"x": "bad"}])
    assert caught.value.errors[0].path == [0, "x"]


def test_every_failing_item_is_reported() -> None:
    """All failing items report, not just the first (voluptuous issue #171).

    voluptuous 0.16.0 stops at the first failing nested item; probatio collects an
    error for every item, so a list of bad mappings reports each index.
    """
    with pytest.raises(MultipleInvalid) as caught:
        Schema([{"name": str}])([{"name": 123}, {"name": 123}])
    paths = sorted(tuple(error.path) for error in caught.value.errors)
    assert paths == [(0, "name"), (1, "name")]


def test_item_failing_every_element_schema_flattens_the_last_error() -> None:
    """When an item matches no element schema, the last error flattens under its index.

    With more than one element schema, an item is tried against each in turn. Here the
    item (a dict) fails the ``int`` schema and then the ``{"a": int}`` schema, and the
    latter raises a ``MultipleInvalid`` (a wrong value type and an extra key). That last
    error is the one reported, its errors flattened under the item's index rather than
    nested. A single element schema takes a faster path, so two are needed to reach the
    per-item loop that does this.
    """
    with pytest.raises(MultipleInvalid) as caught:
        Schema([int, {"a": int}])([{"a": "x", "b": 2}])
    paths = sorted(tuple(error.path) for error in caught.value.errors)
    assert paths == [(0, "a"), (0, "b")]
