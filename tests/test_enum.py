"""Enum members as scalar schemas and mapping keys.

voluptuous 0.16.0 rejects an enum member in a schema with ``SchemaError``;
voluptuous PR #537 adds support for it, driven by Home Assistant's use of
``StrEnum``/``IntEnum`` for service and attribute names. probatio already
accepts enum members: a member is neither a type nor callable, so it compiles to
an equality check (a scalar) and matches as a literal key. These tests pin that
behavior so it cannot regress.
"""

from __future__ import annotations

import enum

import pytest

from probatio import In, Optional, Required, Schema
from probatio.error import EnumInvalid, MultipleInvalid


class Svc(enum.StrEnum):
    """A string enum, as Home Assistant uses for service names."""

    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"


class Prio(enum.IntEnum):
    """An integer enum, to cover the IntEnum case as well."""

    LOW = 1
    HIGH = 2


def test_enum_member_is_a_scalar_schema() -> None:
    """An enum member validates by equality, like any literal."""
    assert Schema(Svc.TURN_ON)(Svc.TURN_ON) == Svc.TURN_ON


def test_enum_member_mismatch_is_invalid() -> None:
    """A different member fails the equality check."""
    with pytest.raises(MultipleInvalid):
        Schema(Svc.TURN_ON)(Svc.TURN_OFF)


def test_str_enum_member_matches_its_string_value() -> None:
    """A StrEnum member equals its string value, so the plain string matches."""
    assert Schema(Svc.TURN_ON)("turn_on") == "turn_on"


def test_enum_member_as_a_bare_key() -> None:
    """An enum member is a literal mapping key."""
    assert Schema({Svc.TURN_ON: int})({Svc.TURN_ON: 5}) == {Svc.TURN_ON: 5}


def test_int_enum_member_as_a_key() -> None:
    """An IntEnum member works as a key too."""
    assert Schema({Prio.LOW: str})({Prio.LOW: "x"}) == {Prio.LOW: "x"}


def test_enum_member_as_a_required_key() -> None:
    """Required wraps an enum key; a missing one reports the member in the path."""
    schema = Schema({Required(Svc.TURN_ON): int})
    assert schema({Svc.TURN_ON: 5}) == {Svc.TURN_ON: 5}
    with pytest.raises(MultipleInvalid) as caught:
        schema({})
    assert caught.value.errors[0].path == [Svc.TURN_ON]


def test_enum_member_as_an_optional_key_default() -> None:
    """An Optional enum key fills its default when absent."""
    schema = Schema({Optional(Svc.TURN_ON, default=0): int})
    assert schema({}) == {Svc.TURN_ON: 0}


def test_enum_member_as_a_value() -> None:
    """An enum member is a valid value schema, matched by equality."""
    assert Schema({"svc": Svc.TURN_ON})({"svc": Svc.TURN_ON}) == {"svc": Svc.TURN_ON}


def test_enum_keys_mix_with_string_keys() -> None:
    """Enum and string keys coexist in one mapping schema."""
    schema = Schema({Svc.TURN_ON: int, "name": str})
    assert schema({Svc.TURN_ON: 1, "name": "x"}) == {Svc.TURN_ON: 1, "name": "x"}


def test_enum_key_value_error_reports_the_member_path() -> None:
    """A bad value under an enum key reports the member in the path."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema({Svc.TURN_ON: int})({Svc.TURN_ON: "bad"})
    assert caught.value.errors[0].path == [Svc.TURN_ON]


def test_in_accepts_an_enum_class() -> None:
    """In(EnumClass) checks membership against the enum's members."""
    schema = Schema(In(Svc))
    assert schema(Svc.TURN_ON) == Svc.TURN_ON
    with pytest.raises(MultipleInvalid):
        schema("nope")


class Color(enum.Enum):
    """A plain Enum, to cover the value-coercion path of the class-as-schema."""

    RED = "red"
    BLUE = "blue"


class Perm(enum.IntFlag):
    """An IntFlag, to prove combined values are accepted through the Enum call."""

    R = 1
    W = 2


def test_enum_class_coerces_a_member_value() -> None:
    """An Enum class as a schema accepts a member's value, returning the member."""
    assert Schema(Color)("red") is Color.RED


def test_enum_class_accepts_a_member_unchanged() -> None:
    """An Enum class as a schema accepts an existing member as-is."""
    assert Schema(Color)(Color.BLUE) is Color.BLUE


def test_str_enum_class_coerces_its_string_value() -> None:
    """A StrEnum class accepts the plain string value of a member."""
    assert Schema(Svc)("turn_on") is Svc.TURN_ON


def test_int_enum_class_coerces_its_int_value() -> None:
    """An IntEnum class accepts the integer value of a member."""
    assert Schema(Prio)(1) is Prio.LOW


def test_int_flag_class_accepts_a_combined_value() -> None:
    """An IntFlag class accepts a combined value, since the Enum call builds it."""
    assert Schema(Perm)(3) == Perm.R | Perm.W


def test_enum_class_rejects_an_unknown_value() -> None:
    """A value that maps to no member raises EnumInvalid listing the values."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Color)("green")
    error = caught.value.errors[0]
    assert isinstance(error, EnumInvalid)
    assert error.code == "enum"
    assert "'red'" in str(error)
    # The structured context carries the valid values, not just the enum name.
    assert error.context == {"expected": "Color", "values": ["red", "blue"]}


def test_enum_class_rejects_an_unhashable_value() -> None:
    """An unhashable value cannot map to a member, so it is rejected, not leaked."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Color)(["red"])
    assert isinstance(caught.value.errors[0], EnumInvalid)


def test_enum_class_as_a_value_reports_the_path() -> None:
    """A bad enum value under a key reports the key in the error path."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema({Required("c"): Color})({"c": "nope"})
    assert caught.value.errors[0].path == ["c"]
