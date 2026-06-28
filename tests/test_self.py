"""Tests for the Self recursive-schema reference."""

from __future__ import annotations

import pytest

from probatio import (
    ALLOW_EXTRA,
    All,
    Any,
    Maybe,
    MultipleInvalid,
    Optional,
    Required,
    Schema,
    SchemaError,
    Self,
)


def test_self_validates_a_recursive_structure() -> None:
    """Self lets a schema reference itself for nested, recursive data."""
    schema = Schema({Required("value"): int, Optional("next"): Self})
    data = {"value": 1, "next": {"value": 2, "next": {"value": 3}}}
    assert schema(data) == data


def test_self_reports_errors_deep_in_the_recursion() -> None:
    """A bad value several levels down is rejected with the right path."""
    schema = Schema({Required("value"): int, Optional("next"): Self})
    with pytest.raises(MultipleInvalid) as caught:
        schema({"value": 1, "next": {"value": "bad"}})
    assert caught.value.errors[0].path == ["next", "value"]


def test_self_in_a_list() -> None:
    """Self works as the element schema of a list, for tree-shaped data."""
    schema = Schema({Required("name"): str, Optional("children"): [Self]})
    data = {"name": "root", "children": [{"name": "leaf"}]}
    assert schema(data) == data


def test_self_recursion_handles_deep_nesting() -> None:
    """A Self reference validates an arbitrarily deep nested structure."""
    schema = Schema({Required("value"): int, Optional("next"): Self})
    data: dict[str, object] = {"value": 0}
    for depth in range(1, 25):
        data = {"value": depth, "next": data}
    assert schema(data) == data


def test_self_schema_wraps_a_single_top_level_error() -> None:
    """A recursive schema whose root fails with one error still wraps it cleanly."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema([Self])("not a list")
    assert caught.value.errors[0].error_message == "expected a list"


def test_self_has_a_readable_repr() -> None:
    """The Self sentinel renders as 'Self'."""
    assert repr(Self) == "Self"


def test_bare_self_is_a_schema_error() -> None:
    """A bare Self has no enclosing schema and is a definition error."""
    with pytest.raises(SchemaError):
        Schema(Self)


def test_self_inside_any_validates_a_recursive_alternative() -> None:
    """Self works inside Any, so a key can recurse or take an alternative."""
    schema = Schema({"number": int, "follow": Any(Self, "stop")})
    assert schema({"follow": {"follow": {"number": 1, "follow": "stop"}}}) == {
        "follow": {"follow": {"number": 1, "follow": "stop"}}
    }
    with pytest.raises(MultipleInvalid):
        schema({"follow": {"number": "1.5"}})


def test_self_inside_all_chains_recursion_with_another_schema() -> None:
    """Self works inside All, chaining the recursive check with a second schema."""
    schema = Schema(
        {"number": int, "follow": All(Self, Schema({"extra": int}, extra=ALLOW_EXTRA))},
        extra=ALLOW_EXTRA,
    )
    assert schema({"follow": {"number": 1, "extra": 2}}) == {
        "follow": {"number": 1, "extra": 2}
    }
    with pytest.raises(MultipleInvalid):
        schema({"follow": {"number": 1, "extra": "no"}})


def test_self_detection_short_circuits_for_a_trailing_callable() -> None:
    """Once Self is found, a callable value compiled afterwards skips the re-check.

    The Self in the first branch flips the recursive flag during compile, so a
    later callable value (``str.strip``) does not re-walk for Self.
    """
    schema = Schema({"next": Any(Self, None), "tag": str.strip})
    assert schema._uses_self is True
    assert schema({"next": {"next": None, "tag": " a "}, "tag": " b "}) == {
        "next": {"next": None, "tag": "a"},
        "tag": "b",
    }


def test_self_in_a_combinator_called_outside_a_schema_is_an_error() -> None:
    """A combinator holding Self, called on its own, has no schema to resolve to."""
    with pytest.raises(SchemaError):
        Any(Self, "stop")("x")


def test_self_wrapped_in_a_validator_is_a_schema_error() -> None:
    """Self wrapped in a plain validator (Maybe) still fails clearly at build time."""
    with pytest.raises(SchemaError):
        Maybe(Self)
