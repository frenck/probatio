"""Tests for the Exclusive and Inclusive dict-group markers."""

from __future__ import annotations

import pytest

from probatio import (
    Any,
    Coerce,
    Exclusive,
    Inclusive,
    MultipleInvalid,
    Required,
    Schema,
)
from probatio.error import ExclusiveInvalid, InclusiveInvalid, RequiredFieldInvalid


def test_exclusive_allows_at_most_one() -> None:
    """Exclusive lets one key from the group through, or none."""
    schema = Schema(
        {
            Exclusive("a", "ab"): int,
            Exclusive("b", "ab"): int,
        },
    )
    assert schema({"a": 1}) == {"a": 1}
    assert schema({}) == {}


def test_exclusive_rejects_more_than_one() -> None:
    """Providing two keys from the same exclusive group fails."""
    schema = Schema(
        {
            Exclusive("a", "ab"): int,
            Exclusive("b", "ab"): int,
        },
    )
    with pytest.raises(MultipleInvalid) as caught:
        schema({"a": 1, "b": 2})
    assert isinstance(caught.value.errors[0], ExclusiveInvalid)


def test_inclusive_requires_all_or_none() -> None:
    """Inclusive accepts all the group keys together, or none of them."""
    schema = Schema(
        {
            Inclusive("a", "ab"): int,
            Inclusive("b", "ab"): int,
        },
    )
    assert schema({"a": 1, "b": 2}) == {"a": 1, "b": 2}
    assert schema({}) == {}


def test_inclusive_rejects_partial_group() -> None:
    """Providing only some keys of an inclusive group fails."""
    schema = Schema(
        {
            Inclusive("a", "ab"): int,
            Inclusive("b", "ab"): int,
        },
    )
    with pytest.raises(MultipleInvalid) as caught:
        schema({"a": 1})
    assert isinstance(caught.value.errors[0], InclusiveInvalid)


def test_exclusive_uses_a_custom_message() -> None:
    """An Exclusive marker's msg replaces the default group error message."""
    schema = Schema(
        {
            Exclusive("a", "ab", msg="pick one"): int,
            Exclusive("b", "ab", msg="pick one"): int,
        },
    )
    with pytest.raises(MultipleInvalid) as caught:
        schema({"a": 1, "b": 2})
    assert caught.value.errors[0].error_message == "pick one"


def test_inclusive_uses_a_custom_message() -> None:
    """An Inclusive marker's msg replaces the default group error message."""
    schema = Schema(
        {
            Inclusive("a", "ab", msg="all or none"): int,
            Inclusive("b", "ab", msg="all or none"): int,
        },
    )
    with pytest.raises(MultipleInvalid) as caught:
        schema({"a": 1})
    assert caught.value.errors[0].error_message == "all or none"


def test_exclusive_required_demands_exactly_one() -> None:
    """Exclusive(required=True) makes an empty group an error (issue #115)."""
    schema = Schema(
        {
            Exclusive("project_id", "p", required=True): int,
            Exclusive("project_name", "p", required=True): str,
        },
    )
    assert schema({"project_id": 1}) == {"project_id": 1}
    assert schema({"project_name": "x"}) == {"project_name": "x"}
    with pytest.raises(MultipleInvalid) as caught:
        schema({})
    error = caught.value.errors[0]
    assert isinstance(error, RequiredFieldInvalid)
    assert (
        error.error_message
        == "exactly one of ['project_id', 'project_name'] is required"
    )


def test_exclusive_required_still_rejects_more_than_one() -> None:
    """A required exclusive group still forbids two keys at once."""
    schema = Schema(
        {
            Exclusive("a", "ab", required=True): int,
            Exclusive("b", "ab", required=True): int,
        },
    )
    with pytest.raises(MultipleInvalid) as caught:
        schema({"a": 1, "b": 2})
    assert isinstance(caught.value.errors[0], ExclusiveInvalid)


def test_exclusive_default_fills_an_empty_group() -> None:
    """Exclusive(default=...) fills its member when the group is empty (issue #245)."""
    schema = Schema(
        {
            Exclusive("foo", "g", default=42): int,
            Exclusive("bar", "g"): int,
        },
    )
    assert schema({}) == {"foo": 42}
    assert schema({"foo": 23}) == {"foo": 23}
    assert schema({"bar": 23}) == {"bar": 23}


def test_exclusive_default_is_validated_through_the_value_schema() -> None:
    """A group default is coerced/validated like any default."""
    schema = Schema(
        {
            Exclusive("foo", "g", default="7"): Coerce(int),
            Exclusive("bar", "g"): int,
        },
    )
    assert schema({}) == {"foo": 7}


def test_exclusive_default_beats_required() -> None:
    """A default satisfies the group, so a required member raises no error."""
    schema = Schema(
        {
            Exclusive("foo", "g", required=True, default=9): int,
            Exclusive("bar", "g", required=True): int,
        },
    )
    assert schema({}) == {"foo": 9}


def test_exclusive_default_does_not_fire_when_another_member_present() -> None:
    """The group default only applies when the whole group is empty."""
    schema = Schema(
        {
            Exclusive("foo", "g", default=42): int,
            Exclusive("bar", "g"): int,
        },
    )
    # 'bar' is present, so the group is satisfied and 'foo' is not defaulted in.
    assert schema({"bar": 5}) == {"bar": 5}


def test_at_least_one_of_a_group_via_required_any() -> None:
    """Required(Any(...)) requires at least one of a group, allowing more (issue #126)."""
    schema = Schema({Required(Any("email", "phone")): str})
    assert schema({"email": "a@b.c"}) == {"email": "a@b.c"}
    # More than one is allowed (unlike Exclusive).
    assert schema({"email": "a@b.c", "phone": "123"}) == {
        "email": "a@b.c",
        "phone": "123",
    }
    with pytest.raises(MultipleInvalid) as caught:
        schema({})
    assert (
        caught.value.errors[0].error_message
        == "at least one of ['email', 'phone'] is required"
    )
