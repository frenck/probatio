"""Building a Schema from a TypedDict.

A TypedDict is a plain dict at runtime, so a TypedDictSchema validates a mapping
against the TypedDict's fields and returns the validated mapping unchanged (typed
as the TypedDict, with nothing constructed). The annotation mapping is shared with
the dataclass builder.
"""

from __future__ import annotations

from typing import Annotated, NotRequired, Required, TypedDict

import pytest

from probatio import (
    ALLOW_EXTRA,
    Range,
    TypedDictSchema,
    create_typeddict_schema,
)
from probatio.error import ExtraKeysInvalid, MultipleInvalid, SchemaError


class Config(TypedDict):
    """A closed TypedDict with two required fields."""

    port: int
    host: str


def test_validates_and_returns_a_plain_dict() -> None:
    """A valid mapping passes and comes back as an unchanged plain dict."""
    result = TypedDictSchema(Config)({"port": 8080, "host": "nas"})
    assert result == {"port": 8080, "host": "nas"}
    assert type(result) is dict


def test_field_type_is_validated() -> None:
    """A wrong-typed field is reported at its key."""
    with pytest.raises(MultipleInvalid) as caught:
        TypedDictSchema(Config)({"port": "no", "host": "x"})
    assert caught.value.errors[0].path == ["port"]


def test_missing_required_key_is_reported() -> None:
    """A required key absent from the data fails."""
    with pytest.raises(MultipleInvalid) as caught:
        TypedDictSchema(Config)({"port": 1})
    assert caught.value.errors[0].path == ["host"]


def test_unknown_key_is_rejected_by_default() -> None:
    """A TypedDict is closed, so an unknown key is rejected."""
    with pytest.raises(MultipleInvalid) as caught:
        TypedDictSchema(Config)({"port": 1, "host": "x", "extra": 1})
    assert isinstance(caught.value.errors[0], ExtraKeysInvalid)


def test_extra_keys_can_be_allowed() -> None:
    """An explicit extra policy passes through to the schema."""
    result = TypedDictSchema(Config, extra=ALLOW_EXTRA)(
        {"port": 1, "host": "x", "extra": 2},
    )
    assert result == {"port": 1, "host": "x", "extra": 2}


class Partial(TypedDict, total=False):
    """A total=False TypedDict, with one field forced required."""

    a: int
    b: Required[str]


def test_total_false_and_required_are_honored() -> None:
    """total=False makes keys optional; Required[...] forces one back to required."""
    schema = TypedDictSchema(Partial)
    assert schema({"b": "x"}) == {"b": "x"}  # a is optional
    assert schema({"a": 1, "b": "x"}) == {"a": 1, "b": "x"}
    with pytest.raises(MultipleInvalid) as caught:
        schema({"a": 1})  # b is required
    assert caught.value.errors[0].path == ["b"]


class Mixed(TypedDict):
    """A total TypedDict with one NotRequired field."""

    x: int
    y: NotRequired[str]


def test_not_required_makes_a_field_optional() -> None:
    """NotRequired[...] makes a field optional in an otherwise total TypedDict."""
    assert TypedDictSchema(Mixed)({"x": 1}) == {"x": 1}


class Inner(TypedDict):
    """A nested TypedDict."""

    n: int


class Outer(TypedDict):
    """A TypedDict with a nested TypedDict and a typed container."""

    inner: Inner
    tags: list[str]


def test_nested_typeddict_and_container_elements() -> None:
    """A nested TypedDict and a container element type both validate, with paths."""
    schema = TypedDictSchema(Outer)
    assert schema({"inner": {"n": 5}, "tags": ["a", "b"]}) == {
        "inner": {"n": 5},
        "tags": ["a", "b"],
    }
    with pytest.raises(MultipleInvalid) as caught:
        schema({"inner": {"n": "bad"}, "tags": []})
    assert caught.value.errors[0].path == ["inner", "n"]


class Node(TypedDict):
    """A recursive TypedDict (a tree node)."""

    value: int
    children: list[Node]


def test_recursive_typeddict() -> None:
    """A self-referential TypedDict validates all the way down."""
    result = TypedDictSchema(Node)(
        {"value": 1, "children": [{"value": 2, "children": []}]},
    )
    assert result == {"value": 1, "children": [{"value": 2, "children": []}]}


def test_additional_constraints_layer_onto_a_field() -> None:
    """A per-field constraint runs after the type check."""
    schema = TypedDictSchema(Config, {"port": Range(min=1, max=65535)})
    assert schema({"port": 80, "host": "x"}) == {"port": 80, "host": "x"}
    with pytest.raises(MultipleInvalid):
        schema({"port": 70000, "host": "x"})


def test_annotated_inline_validator_on_a_field() -> None:
    """An Annotated field carries its own validator, like the dataclass builder."""

    class Bounded(TypedDict):
        """A field with an inline Range."""

        count: Annotated[int, Range(min=0)]

    assert TypedDictSchema(Bounded)({"count": 3}) == {"count": 3}
    with pytest.raises(MultipleInvalid):
        TypedDictSchema(Bounded)({"count": -1})


def test_create_typeddict_schema_rejects_a_non_typeddict() -> None:
    """A type that is not a TypedDict is a schema definition error."""
    with pytest.raises(SchemaError, match="TypedDict"):
        create_typeddict_schema(dict)


def test_unresolvable_annotation_is_a_schema_error() -> None:
    """A TypedDict whose annotation cannot be resolved fails cleanly, not NameError."""

    class Broken(TypedDict):
        """A field referring to a name that does not exist."""

        x: DoesNotExist  # type: ignore[name-defined]  # noqa: F821

    with pytest.raises(SchemaError, match="cannot resolve type hints"):
        TypedDictSchema(Broken)


def test_functional_form_matches_the_class() -> None:
    """create_typeddict_schema builds the same validator as the class."""
    assert create_typeddict_schema(Config)({"port": 1, "host": "x"}) == {
        "port": 1,
        "host": "x",
    }


def test_construct_returns_trusted_data_unchanged() -> None:
    """construct() returns trusted input as the TypedDict, with no validation."""

    class Movie(TypedDict):
        title: str
        year: int

    schema = TypedDictSchema(Movie)
    data = {"title": "x", "year": "not-an-int"}  # wrong type, but trusted
    assert schema.construct(data) == {"title": "x", "year": "not-an-int"}
    with pytest.raises(MultipleInvalid):
        schema(data)  # validation would reject it
