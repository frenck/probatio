"""Tests for the Object schema: validating attributes instead of dict keys."""

from __future__ import annotations

from collections import namedtuple
from typing import Any

import pytest

from probatio import MultipleInvalid, Object, Schema
from probatio.error import ObjectInvalid


class Point:
    """A small attribute-bearing class rebuilt from validated attributes."""

    def __init__(self, x: Any = None, y: Any = None) -> None:
        """Store the two coordinates."""
        self.x = x
        self.y = y

    def __eq__(self, other: object) -> bool:
        """Compare by coordinates."""
        return isinstance(other, Point) and (self.x, self.y) == (other.x, other.y)

    def __hash__(self) -> int:
        """Hash by coordinates."""
        return hash((self.x, self.y))


def test_object_validates_attributes() -> None:
    """Object validates an object's attributes and rebuilds it."""
    result = Schema(Object({"x": int, "y": int}))(Point(1, 2))
    assert result == Point(1, 2)
    assert isinstance(result, Point)


def test_object_reports_a_bad_attribute_as_object_value() -> None:
    """A failing attribute is tagged 'object value', not 'dictionary value'."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Object({"x": int, "y": int}))(Point(1, "nope"))
    error = caught.value.errors[0]
    assert error.path == ["y"]
    assert error.error_type == "object value"


def test_object_enforces_the_class() -> None:
    """With cls set, a value of the wrong type is rejected."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Object({"x": int}, cls=Point))({"x": 1})
    assert isinstance(caught.value.errors[0], ObjectInvalid)


def test_object_accepts_the_right_class() -> None:
    """With cls set, an instance of that class validates."""
    assert Schema(Object({"x": int, "y": int}, cls=Point))(Point(1, 2)) == Point(1, 2)


def test_object_skips_none_attributes() -> None:
    """An attribute that is None is skipped, not validated against its schema."""
    # y is None, so the int schema for it is not applied.
    assert Schema(Object({"x": int, "y": int}))(Point(1, None)) == Point(1, None)


def test_object_validates_namedtuple_attributes() -> None:
    """A namedtuple is validated through its _asdict mapping."""
    pair = namedtuple("pair", ["x", "y"])  # noqa: PYI024
    result = Schema(Object({"x": int, "y": int}))(pair(1, 2))
    assert result == pair(1, 2)


def test_object_reads_slots() -> None:
    """An object using __slots__ exposes its attributes for validation."""

    class Slotted:
        # "__dict__" in __slots__ gives the object a dict too; the attribute
        # iterator must skip that slot name rather than treat it as a field.
        __slots__ = ("__dict__", "x")

        def __init__(self, x: Any = None) -> None:
            self.x = x

        def __eq__(self, other: object) -> bool:
            return isinstance(other, Slotted) and self.x == other.x

        def __hash__(self) -> int:
            return hash(self.x)

    assert Schema(Object({"x": int}))(Slotted(5)) == Slotted(5)
