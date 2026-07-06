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
    PREVENT_EXTRA,
    REMOVE_EXTRA,
    Key,
    Range,
    TypedDictSchema,
    create_typeddict_schema,
)
from probatio.error import ExtraKeysInvalid, MultipleInvalid, SchemaError
from probatio.humanize import humanize_error


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


class _TotalBase(TypedDict):
    """A total base: its field is required."""

    a: int


class InheritsIntoPartial(_TotalBase, total=False):
    """A total=False child of a total base: b is optional, a stays required."""

    b: str


def test_required_field_inherited_into_a_partial_child_stays_required() -> None:
    """A required base field keeps its presence under a total=False child."""
    schema = TypedDictSchema(InheritsIntoPartial)
    assert schema({"a": 1}) == {"a": 1}  # b is optional
    with pytest.raises(MultipleInvalid) as caught:
        schema({"b": "x"})  # a is inherited-required, not optional
    assert caught.value.errors[0].path == ["a"]


class _PartialBase(TypedDict, total=False):
    """A total=False base: its field is optional."""

    x: int


class InheritsIntoTotal(_PartialBase):
    """A total child of a total=False base: y is required, x stays optional."""

    y: int


def test_optional_field_inherited_into_a_total_child_stays_optional() -> None:
    """An optional base field keeps its presence under a total child."""
    schema = TypedDictSchema(InheritsIntoTotal)
    assert schema({"y": 1}) == {"y": 1}  # x is inherited-optional, not required
    with pytest.raises(MultipleInvalid) as caught:
        schema({"x": 1})  # y is required
    assert caught.value.errors[0].path == ["y"]


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


# --- Key field metadata (ADR-013) ----------------------------------------------


def test_key_secret_redacts_on_a_typeddict() -> None:
    """Key(secret=True) redacts the field's value in errors on a TypedDict."""

    class Login(TypedDict):
        user: str
        password: Annotated[str, Key(secret=True)]

    data = {"user": "bob", "password": 123}
    with pytest.raises(MultipleInvalid) as caught:
        TypedDictSchema(Login)(data)
    assert "<redacted>" in humanize_error(data, caught.value)


def test_key_alias_multiple_names_on_a_typeddict() -> None:
    """Key(alias=[...]) accepts several names, emitting the field name."""

    class Cfg(TypedDict):
        user_name: Annotated[str, Key(alias=["user-name", "userName"])]

    schema = create_typeddict_schema(Cfg)
    assert schema({"user-name": "ada"}) == {"user_name": "ada"}
    assert schema({"userName": "eve"}) == {"user_name": "eve"}


def test_key_forbidden_needs_no_default_on_a_typeddict() -> None:
    """A TypedDict constructs nothing, so a Forbidden field needs no default."""

    class Payload(TypedDict):
        name: str
        server_set: Annotated[str, Key(forbidden=True)]

    schema = create_typeddict_schema(Payload)
    assert schema({"name": "x"}) == {"name": "x"}
    with pytest.raises(MultipleInvalid):
        schema({"name": "x", "server_set": "nope"})


def test_key_exclusive_group_on_a_typeddict() -> None:
    """Key(exclusive=group) allows at most one group member on a TypedDict."""

    class Auth(TypedDict):
        token: NotRequired[Annotated[str, Key(exclusive="auth")]]
        secret: NotRequired[Annotated[str, Key(exclusive="auth")]]

    schema = create_typeddict_schema(Auth)
    assert schema({"token": "t"}) == {"token": "t"}
    with pytest.raises(MultipleInvalid):
        schema({"token": "t", "secret": "s"})


def test_required_qualifier_inside_annotated_is_honored() -> None:
    """Required/NotRequired work inside Annotated, not only as the outer wrapper."""

    class NotReq(TypedDict):
        x: Annotated[NotRequired[int], Key(secret=True)]

    schema = create_typeddict_schema(NotReq)
    assert schema({}) == {}  # NotRequired honored despite being inside Annotated
    with pytest.raises(MultipleInvalid):
        schema({"x": "bad"})  # value schema still validates the inner type

    class Req(TypedDict, total=False):
        x: Annotated[Required[int], Key(secret=True)]

    req = create_typeddict_schema(Req)
    with pytest.raises(MultipleInvalid):
        req({})  # Required honored inside Annotated, in a total=False TypedDict
    assert req({"x": 5}) == {"x": 5}


# --- extra propagates into nested schemas (handoff: nested extra recursion) ---


class _XTDInner(TypedDict):
    a: int


class _XTDOuter(TypedDict):
    inner: _XTDInner


class _XTDStrictInner(TypedDict):
    b: int


class _XTDMixed(TypedDict):
    loose: _XTDInner
    strict: Annotated[_XTDStrictInner, Key(extra=PREVENT_EXTRA)]


def test_extra_recurses_into_a_nested_typeddict() -> None:
    """REMOVE_EXTRA drops an unknown key inside a nested TypedDict."""
    result = TypedDictSchema(_XTDOuter, extra=REMOVE_EXTRA)({"inner": {"a": 1, "j": 2}})
    assert result == {"inner": {"a": 1}}


def test_nested_typeddict_extra_default_still_rejects() -> None:
    """The default (PREVENT_EXTRA) still raises on a nested unknown key."""
    with pytest.raises(MultipleInvalid) as caught:
        TypedDictSchema(_XTDOuter)({"inner": {"a": 1, "j": 2}})
    (error,) = caught.value.errors
    assert error.path == ["inner", "j"]


def test_key_extra_pins_a_strict_nested_typeddict() -> None:
    """Key(extra=PREVENT_EXTRA) keeps one nested TypedDict strict under a loose parent."""
    data = {"loose": {"a": 1, "j": 2}, "strict": {"b": 1, "j": 3}}
    with pytest.raises(MultipleInvalid) as caught:
        TypedDictSchema(_XTDMixed, extra=REMOVE_EXTRA)(data)
    (error,) = caught.value.errors
    assert error.path == ["strict", "j"]
