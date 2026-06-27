"""Tests for the transition validators (Immutable, WriteOnce).

These compare new data against its previous value, supplied through the call-time
context (``schema(new, context=old)``).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from probatio import All, Immutable, Optional, Required, Schema, WriteOnce
from probatio.error import ImmutableInvalid, MultipleInvalid, SchemaError


def _immutable_schema() -> Schema:
    """A schema whose user_id may not change between versions."""
    return Schema(
        All(
            {Required("user_id"): int, Optional("name"): str},
            Immutable("user_id"),
        ),
    )


def test_immutable_passes_when_unchanged() -> None:
    """An immutable field with the same value across versions validates."""
    old = {"user_id": 1, "name": "ada"}
    assert _immutable_schema()({"user_id": 1, "name": "bob"}, context=old) == {
        "user_id": 1,
        "name": "bob",
    }


def test_immutable_rejects_a_change() -> None:
    """Changing an immutable field is rejected, reported at the field."""
    with pytest.raises(MultipleInvalid) as caught:
        _immutable_schema()({"user_id": 2}, context={"user_id": 1})
    error = caught.value.errors[0]
    assert isinstance(error, ImmutableInvalid)
    assert error.code == "immutable"
    assert error.path == ["user_id"]


def test_immutable_is_a_no_op_without_context() -> None:
    """With no previous value (a first validation), nothing is compared."""
    assert _immutable_schema()({"user_id": 9}) == {"user_id": 9}


def test_immutable_ignores_a_field_the_update_omits() -> None:
    """A field absent from the new data is not checked for a change."""
    assert _immutable_schema()({"user_id": 1}, context={"user_id": 1, "name": "a"}) == {
        "user_id": 1,
    }


def test_immutable_allows_a_first_set() -> None:
    """A field absent from the previous data may be set for the first time."""
    assert _immutable_schema()({"user_id": 5}, context={"name": "x"}) == {"user_id": 5}


def test_immutable_ignores_a_non_mapping_value_or_context() -> None:
    """A non-mapping value, or a non-mapping context, makes the rule a no-op."""
    assert Schema(Immutable("a"))("x") == "x"
    assert Schema(Immutable("a"))({"a": 1}, context=42) == {"a": 1}


def test_immutable_treats_an_uncomparable_value_as_changed() -> None:
    """A comparison that cannot run (a signaling Decimal) counts as a change."""
    schema = Schema(All({Optional("a"): object}, Immutable("a")))
    with pytest.raises(MultipleInvalid):
        schema({"a": Decimal("sNaN")}, context={"a": Decimal("sNaN")})


def test_immutable_across_several_fields_with_a_custom_message() -> None:
    """Several fields are checked, and a custom message replaces the default."""
    schema = Schema(
        All(
            {Optional("a"): int, Optional("b"): int},
            Immutable("a", "b", msg="frozen"),
        ),
    )
    with pytest.raises(MultipleInvalid) as caught:
        schema({"a": 1, "b": 9}, context={"a": 1, "b": 2})
    assert caught.value.errors[0].error_message == "frozen"
    assert caught.value.errors[0].path == ["b"]


def test_immutable_needs_at_least_one_field() -> None:
    """Immutable with no field name is a schema definition error."""
    with pytest.raises(SchemaError, match="at least one field"):
        Immutable()


def _write_once_schema() -> Schema:
    """A schema whose token may be set once, then not changed."""
    return Schema(All({Optional("token"): str}, WriteOnce("token")))


def test_write_once_allows_setting_from_absent_or_none() -> None:
    """A write-once field may be set when previously absent or None."""
    assert _write_once_schema()({"token": "t1"}, context={}) == {"token": "t1"}
    assert _write_once_schema()({"token": "t1"}, context={"token": None}) == {
        "token": "t1",
    }


def test_write_once_rejects_a_change_after_set() -> None:
    """Once a write-once field holds a value, a different value is rejected."""
    with pytest.raises(MultipleInvalid) as caught:
        _write_once_schema()({"token": "t2"}, context={"token": "t1"})
    assert caught.value.errors[0].path == ["token"]
    assert isinstance(caught.value.errors[0], ImmutableInvalid)


def test_write_once_allows_the_same_value() -> None:
    """Re-submitting the same value for a set write-once field is fine."""
    assert _write_once_schema()({"token": "t1"}, context={"token": "t1"}) == {
        "token": "t1",
    }


def test_write_once_is_a_no_op_without_context() -> None:
    """With no previous value, a write-once field may take any value."""
    assert _write_once_schema()({"token": "t1"}) == {"token": "t1"}


def test_write_once_needs_at_least_one_field() -> None:
    """WriteOnce with no field name is a schema definition error."""
    with pytest.raises(SchemaError, match="at least one field"):
        WriteOnce()
