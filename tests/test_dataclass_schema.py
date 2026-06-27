"""Building a Schema from a dataclass (voluptuous PR #533, with a richer mapping).

Covers the type-annotation mapping (primitives, containers with element types,
unions, literals, nested dataclasses), default/default_factory handling,
additional constraints, instance construction, and the error paths.
"""

from __future__ import annotations

import typing
from collections.abc import (  # noqa: TC003 - resolved at runtime by get_type_hints
    Iterable,
    Mapping,
    MutableSet,
    Sequence,
)
from dataclasses import InitVar, dataclass, field
from typing import Annotated, Any, Literal, NewType, TypeVar

import pytest

from probatio import (
    ALLOW_EXTRA,
    DataclassSchema,
    Length,
    MultipleInvalid,
    Range,
    SchemaError,
    create_dataclass_schema,
    is_dataclass,
)
from probatio.dataclass_schema import _build_discriminant, _literal_tags

_TypeVarT = TypeVar("_TypeVarT")


@dataclass
class Node:
    """A self-referential dataclass, to prove recursive validation."""

    value: int
    nxt: Node | None = None


@dataclass
class Tree:
    """A node with any number of child nodes of the same type."""

    name: str
    children: list[Tree] = field(default_factory=list)


@dataclass
class Ping:
    """One half of a mutually recursive pair; holds an optional Pong."""

    pong: Pong | None = None


@dataclass
class Pong:
    """The other half; holds an optional Ping."""

    ping: Ping | None = None


@dataclass
class Address:
    """A nested dataclass, to prove recursion into field types."""

    street: str
    number: int = 0


@dataclass
class User:
    """A dataclass exercising the common annotation shapes."""

    name: str
    age: int = 18
    tags: list[str] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)
    nick: str | None = None
    address: Address | None = None
    coords: tuple[int, int] = (0, 0)
    rest: tuple[int, ...] = ()


def test_is_dataclass() -> None:
    """is_dataclass mirrors the standard library for types and non-dataclasses."""
    assert is_dataclass(User) is True
    assert is_dataclass(5) is False


def test_required_and_optional_from_defaults() -> None:
    """A field without a default is required; one with a default is optional."""
    schema = DataclassSchema(User)
    result = schema({"name": "ada"})
    assert result == User(name="ada")
    with pytest.raises(MultipleInvalid) as caught:
        schema({})
    assert caught.value.errors[0].path == ["name"]


def test_default_factory_is_applied() -> None:
    """A default_factory field fills in a fresh value when the key is absent."""
    result = DataclassSchema(User)({"name": "ada"})
    assert result.tags == []
    assert result.scores == {}


def test_constructs_a_dataclass_instance() -> None:
    """A passing mapping is turned into an instance of the dataclass."""
    result = DataclassSchema(User)({"name": "ada", "age": 30})
    assert isinstance(result, User)
    assert result.age == 30


def test_list_element_type_is_validated() -> None:
    """list[str] keeps its element type, so a wrong element is rejected."""
    schema = DataclassSchema(User)
    assert schema({"name": "a", "tags": ["x", "y"]}).tags == ["x", "y"]
    with pytest.raises(MultipleInvalid) as caught:
        schema({"name": "a", "tags": [1]})
    assert caught.value.errors[0].path == ["tags", 0]


def test_dict_key_and_value_types_are_validated() -> None:
    """dict[str, int] validates both the key and the value types."""
    schema = DataclassSchema(User)
    assert schema({"name": "a", "scores": {"k": 1}}).scores == {"k": 1}
    with pytest.raises(MultipleInvalid):
        schema({"name": "a", "scores": {"k": "no"}})


def test_optional_union_becomes_maybe() -> None:
    """X | None accepts None or X, and rejects a wrong type."""
    schema = DataclassSchema(User)
    assert schema({"name": "a", "nick": None}).nick is None
    assert schema({"name": "a", "nick": "n"}).nick == "n"
    with pytest.raises(MultipleInvalid):
        schema({"name": "a", "nick": 5})


def test_nested_dataclass_recurses() -> None:
    """A nested dataclass field validates and constructs the nested instance."""
    result = DataclassSchema(User)(
        {"name": "a", "address": {"street": "Main", "number": 5}},
    )
    assert result.address == Address(street="Main", number=5)


def test_nested_dataclass_reports_nested_path() -> None:
    """A failure inside a nested dataclass reports the full path."""
    with pytest.raises(MultipleInvalid) as caught:
        DataclassSchema(User)({"name": "a", "address": {"number": "no"}})
    paths = {tuple(error.path) for error in caught.value.errors}
    assert ("address", "number") in paths


def test_fixed_tuple_validates_positionally() -> None:
    """tuple[int, int] checks arity and per-position types, accepting a list."""
    schema = DataclassSchema(User)
    assert schema({"name": "a", "coords": [1, 2]}).coords == [1, 2]
    with pytest.raises(MultipleInvalid):
        schema({"name": "a", "coords": [1, 2, 3]})


def test_variadic_tuple_accepts_list_or_tuple() -> None:
    """tuple[int, ...] validates each element and takes a list or a tuple."""
    schema = DataclassSchema(User)
    assert schema({"name": "a", "rest": [1, 2, 3]}).rest == [1, 2, 3]
    assert schema({"name": "a", "rest": (1, 2)}).rest == (1, 2)
    with pytest.raises(MultipleInvalid):
        schema({"name": "a", "rest": [1, "x"]})


def test_additional_constraints_layer_onto_a_field() -> None:
    """A constraint runs after the type check, via All."""
    schema = DataclassSchema(User, {"name": Length(min=2), "age": Range(min=0)})
    assert schema({"name": "ab", "age": 1}).name == "ab"
    with pytest.raises(MultipleInvalid):
        schema({"name": "a"})


def test_create_dataclass_schema_matches_the_class() -> None:
    """The functional API builds the same validator as the class."""
    schema = create_dataclass_schema(User)
    assert schema({"name": "ada"}) == User(name="ada")


def test_create_dataclass_schema_rejects_a_non_dataclass() -> None:
    """A non-dataclass type is a schema definition error."""
    with pytest.raises(SchemaError):
        create_dataclass_schema(int)


def test_constructor_step_reads_with_the_target_type() -> None:
    """The construction step renders with the dataclass name in the schema repr."""
    assert "<construct User>" in repr(create_dataclass_schema(User).schema)


def test_recursive_dataclass_validates_and_constructs() -> None:
    """A self-referential dataclass validates and constructs all the way down."""
    result = DataclassSchema(Node)(
        {"value": 1, "nxt": {"value": 2, "nxt": {"value": 3}}},
    )
    assert result == Node(value=1, nxt=Node(value=2, nxt=Node(value=3)))
    assert isinstance(result.nxt.nxt, Node)


def test_recursive_dataclass_reports_a_nested_path() -> None:
    """An error deep in a recursive structure reports its full path."""
    with pytest.raises(MultipleInvalid) as caught:
        DataclassSchema(Node)({"value": 1, "nxt": {"value": "bad"}})
    assert caught.value.errors[0].path == ["nxt", "value"]


def test_recursive_dataclass_as_a_list_of_self() -> None:
    """A dataclass whose field is a list of itself validates a tree."""
    result = DataclassSchema(Tree)(
        {"name": "root", "children": [{"name": "a"}, {"name": "b"}]},
    )
    assert result == Tree(name="root", children=[Tree(name="a"), Tree(name="b")])


def test_mutually_recursive_dataclasses() -> None:
    """Two dataclasses that reference each other build and validate."""
    result = DataclassSchema(Ping)({"pong": {"ping": {"pong": None}}})
    assert result == Ping(pong=Pong(ping=Ping(pong=None)))


def test_recursive_dataclass_rejects_pathological_depth() -> None:
    """Very deeply nested data raises a clean Invalid, never a RecursionError."""
    data: dict = {"value": 0}
    current = data
    for index in range(1, 5000):
        current["nxt"] = {"value": index}
        current = current["nxt"]
    with pytest.raises(MultipleInvalid, match="nested too deeply"):
        DataclassSchema(Node)(data)


def test_recursive_dataclass_rejects_cyclic_data() -> None:
    """Self-referential data is rejected cleanly, not as a RecursionError."""
    cyclic: dict = {"value": 1}
    cyclic["nxt"] = cyclic
    with pytest.raises(MultipleInvalid, match="nested too deeply"):
        DataclassSchema(Node)(cyclic)


@dataclass
class Circle:
    """A tagged variant: the literal kind names it."""

    kind: Literal["circle"]
    radius: int


@dataclass
class Square:
    """The other tagged variant."""

    kind: Literal["square"]
    side: int


@dataclass
class Shape:
    """Holds a discriminated union of tagged variants."""

    shape: Circle | Square


@dataclass
class A:
    """An untagged variant, to prove a plain union stays Any."""

    a: int


@dataclass
class B:
    """The other untagged variant."""

    b: int


def test_discriminated_union_dispatches_on_the_tag() -> None:
    """A union of tagged dataclasses validates and constructs the tagged branch."""
    schema = DataclassSchema(Shape)
    assert schema({"shape": {"kind": "circle", "radius": 5}}) == Shape(
        shape=Circle(kind="circle", radius=5),
    )
    assert schema({"shape": {"kind": "square", "side": 3}}) == Shape(
        shape=Square(kind="square", side=3),
    )


def test_discriminated_union_reports_the_selected_branch_error() -> None:
    """The tag selects one branch, so the error points at it, not at every member."""
    with pytest.raises(MultipleInvalid) as caught:
        DataclassSchema(Shape)({"shape": {"kind": "circle", "radius": "no"}})
    assert caught.value.errors[0].path == ["shape", "radius"]


def test_discriminated_union_unknown_tag_falls_back() -> None:
    """An unknown tag value tries every member rather than crashing."""
    with pytest.raises(MultipleInvalid):
        DataclassSchema(Shape)({"shape": {"kind": "triangle", "radius": 1}})


def test_untagged_union_of_dataclasses_stays_any() -> None:
    """Without a shared literal tag, a union still tries each member (Any)."""

    @dataclass
    class Holder:
        """A union with no discriminating tag field."""

        x: A | B

    schema = DataclassSchema(Holder)
    assert schema({"x": {"a": 1}}) == Holder(x=A(a=1))
    assert schema({"x": {"b": 2}}) == Holder(x=B(b=2))


def test_union_with_a_non_dataclass_member_stays_any() -> None:
    """A union mixing a dataclass and a plain type is not discriminated."""

    @dataclass
    class Mixed:
        """A union of a tagged dataclass and a bare int."""

        x: Circle | int

    schema = DataclassSchema(Mixed)
    assert schema({"x": {"kind": "circle", "radius": 1}}).x == Circle("circle", 1)
    assert schema({"x": 42}).x == 42


def test_union_with_a_shared_tag_value_stays_any() -> None:
    """When members share a tag value it cannot discriminate, so it stays Any."""

    @dataclass
    class Dup1:
        """Shares the tag value with Dup2, so it is not distinct."""

        kind: Literal["same"]
        a: int

    @dataclass
    class Dup2:
        """The clashing second variant."""

        kind: Literal["same"]
        b: int

    assert _build_discriminant([Dup1, Dup2], ["one", "two"]) is None


def test_literal_tags_ignores_multi_value_literals() -> None:
    """Only a single-value Literal is a tag; a multi-value one is not."""

    @dataclass
    class Multi:
        """A single-value tag and a multi-value Literal that is not a tag."""

        kind: Literal["a"]
        mode: Literal["x", "y"]

    assert _literal_tags(Multi) == {"kind": "a"}


def test_discriminated_union_non_mapping_value_falls_back() -> None:
    """A non-mapping value cannot be discriminated, so every member is tried."""
    with pytest.raises(MultipleInvalid):
        DataclassSchema(Shape)({"shape": 42})


def test_discriminated_union_unhashable_tag_falls_back() -> None:
    """An unhashable tag value cannot index the map, so it falls back, not crashes."""
    with pytest.raises(MultipleInvalid):
        DataclassSchema(Shape)({"shape": {"kind": ["x"], "radius": 1}})


UserId = NewType("UserId", int)


@dataclass
class AnnotatedFields:
    """A dataclass whose fields carry inline validators through Annotated."""

    count: Annotated[int, Range(min=0)]
    name: Annotated[str, Length(min=2), Length(max=4)] = "ab"
    note: Annotated[str, "doc only, not a validator"] = "x"
    items: list[Annotated[int, Range(min=1)]] = field(default_factory=list)
    uid: UserId = UserId(0)


def test_annotated_applies_an_inline_validator() -> None:
    """A callable in Annotated metadata runs after the base type check."""
    schema = DataclassSchema(AnnotatedFields)
    assert schema({"count": 3}).count == 3
    with pytest.raises(MultipleInvalid) as caught:
        schema({"count": -1})
    assert caught.value.errors[0].path == ["count"]


def test_annotated_applies_every_validator_in_order() -> None:
    """Multiple callables in Annotated metadata all apply, through All."""
    schema = DataclassSchema(AnnotatedFields)
    assert schema({"count": 0, "name": "abc"}).name == "abc"
    with pytest.raises(MultipleInvalid):
        schema({"count": 0, "name": "a"})  # too short
    with pytest.raises(MultipleInvalid):
        schema({"count": 0, "name": "abcde"})  # too long


def test_annotated_ignores_non_callable_metadata() -> None:
    """Non-callable Annotated metadata is left for other tools, not applied."""
    assert DataclassSchema(AnnotatedFields)({"count": 0, "note": "anything"}).note == (
        "anything"
    )


def test_annotated_inside_a_container() -> None:
    """An Annotated element type validates each item of a container."""
    schema = DataclassSchema(AnnotatedFields)
    assert schema({"count": 0, "items": [1, 2]}).items == [1, 2]
    with pytest.raises(MultipleInvalid):
        schema({"count": 0, "items": [0]})  # below the element minimum


def test_newtype_is_followed_to_its_supertype() -> None:
    """A NewType field validates against the type it wraps."""
    schema = DataclassSchema(AnnotatedFields)
    assert schema({"count": 0, "uid": 7}).uid == 7
    with pytest.raises(MultipleInvalid):
        schema({"count": 0, "uid": "nope"})


def test_init_false_field_is_skipped() -> None:
    """A field with init=False is not part of the generated schema."""

    @dataclass
    class WithComputed:
        name: str
        token: str = field(default="x", init=False)

    result = DataclassSchema(WithComputed)({"name": "a"})
    assert result.name == "a"


def test_extra_keys_are_dropped_on_construction() -> None:
    """With ALLOW_EXTRA, unknown keys validate but are not passed to the constructor."""
    schema = DataclassSchema(User, extra=ALLOW_EXTRA)
    result = schema({"name": "a", "unknown": 1})
    assert isinstance(result, User)
    assert not hasattr(result, "unknown")


def test_any_annotation_accepts_anything() -> None:
    """A field annotated Any accepts any value."""

    @dataclass
    class Box:
        payload: Any

    assert DataclassSchema(Box)({"payload": object}).payload is object


def test_none_annotation_requires_none() -> None:
    """A field annotated None only accepts None."""

    @dataclass
    class Empty:
        nothing: None = None

    assert DataclassSchema(Empty)({"nothing": None}).nothing is None
    with pytest.raises(MultipleInvalid):
        DataclassSchema(Empty)({"nothing": 1})


def test_literal_becomes_membership() -> None:
    """A Literal annotation maps to a membership check."""

    @dataclass
    class Mode:
        kind: Literal["on", "off"] = "on"

    assert DataclassSchema(Mode)({"kind": "off"}).kind == "off"
    with pytest.raises(MultipleInvalid):
        DataclassSchema(Mode)({"kind": "maybe"})


def test_wider_union_becomes_any() -> None:
    """A union without None maps to Any of its members."""

    @dataclass
    class Mixed:
        value: int | str

    schema = DataclassSchema(Mixed)
    assert schema({"value": 1}).value == 1
    assert schema({"value": "x"}).value == "x"
    with pytest.raises(MultipleInvalid):
        schema({"value": 1.5})


def test_set_and_frozenset_element_types() -> None:
    """set[int] and frozenset[int] validate their element types."""

    @dataclass
    class Sets:
        a: set[int] = field(default_factory=set)
        b: frozenset[int] = field(default_factory=frozenset)

    schema = DataclassSchema(Sets)
    result = schema({"a": {1, 2}, "b": frozenset({3})})
    assert result.a == {1, 2}
    assert result.b == frozenset({3})


def test_typevar_field_accepts_anything() -> None:
    """A bare TypeVar annotation has no concrete type, so it accepts any value."""

    @dataclass
    class Generic:
        value: _TypeVarT  # type: ignore[valid-type]

    assert DataclassSchema(Generic)({"value": 42}).value == 42


def test_bare_generic_alias_checks_the_container() -> None:
    """A bare typing.List/typing.Dict validates the container type only."""

    @dataclass
    class Bare:
        items: typing.List = field(default_factory=list)  # noqa: UP006
        table: typing.Dict = field(default_factory=dict)  # noqa: UP006

    schema = DataclassSchema(Bare)
    assert schema({"items": [1, "x"], "table": {"k": object}}).items == [1, "x"]
    with pytest.raises(MultipleInvalid):
        schema({"items": "not-a-list"})


def test_abstract_sequence_validates_element_wise() -> None:
    """``Sequence[int]`` validates like a list of ints; a str is not one."""

    @dataclass
    class Holder:
        seq: Sequence[int] = ()

    assert DataclassSchema(Holder)({"seq": [1, 2]}).seq == [1, 2]
    with pytest.raises(MultipleInvalid):
        DataclassSchema(Holder)({"seq": ["x"]})  # wrong element type
    with pytest.raises(MultipleInvalid):
        DataclassSchema(Holder)({"seq": "anything"})  # a str is not a Sequence[int]


def test_abstract_mapping_validates_keys_and_values() -> None:
    """``Mapping[str, int]`` validates like a ``{str: int}`` dict schema."""

    @dataclass
    class Holder:
        mp: Mapping[str, int] = field(default_factory=dict)

    assert DataclassSchema(Holder)({"mp": {"a": 1}}).mp == {"a": 1}
    with pytest.raises(MultipleInvalid):
        DataclassSchema(Holder)({"mp": {"a": "x"}})  # wrong value type


def test_abstract_set_validates_element_wise() -> None:
    """``MutableSet[int]`` validates like a ``{int}`` set schema."""

    @dataclass
    class Holder:
        items: MutableSet[int] = field(default_factory=set)

    assert DataclassSchema(Holder)({"items": {1, 2}}).items == {1, 2}
    with pytest.raises(MultipleInvalid):
        DataclassSchema(Holder)({"items": {"x"}})  # wrong element type


def test_other_parameterized_generic_validates_the_container_type() -> None:
    """An exotic generic validates its container type, not "accept anything"."""

    @dataclass
    class Holder:
        it: Iterable[int] = ()

    assert DataclassSchema(Holder)({"it": [1, 2]}).it == [1, 2]
    with pytest.raises(MultipleInvalid):
        DataclassSchema(Holder)({"it": 5})  # an int is not Iterable


def test_three_element_fixed_tuple() -> None:
    """A fixed tuple longer than two positions validates each position."""

    @dataclass
    class Triple:
        value: tuple[int, str, bool] = (0, "", False)

    assert DataclassSchema(Triple)({"value": [1, "x", True]}).value == [1, "x", True]
    with pytest.raises(MultipleInvalid):
        DataclassSchema(Triple)({"value": [1, "x"]})


def test_unresolvable_forward_ref_is_a_clean_schema_error() -> None:
    """A field annotated with an unresolvable forward reference raises SchemaError."""

    @dataclass
    class BadRef:
        value: DoesNotExist  # type: ignore[name-defined]  # noqa: F821

    with pytest.raises(SchemaError, match="cannot resolve type hints"):
        create_dataclass_schema(BadRef)


def test_callable_default_is_kept_not_called() -> None:
    """A callable used as a field default comes back as itself, like a dataclass."""

    @dataclass
    class WithCallable:
        handler: object = print

    result = DataclassSchema(WithCallable)({})
    assert result.handler is print


def test_initvar_is_validated_and_passed_to_post_init() -> None:
    """An InitVar is a constructor argument: validated, then handed to __post_init__."""

    @dataclass
    class Seeded:
        base: int
        seed: InitVar[int]
        offset: InitVar[int] = 10

        def __post_init__(self, seed: int, offset: int) -> None:
            self.base += seed + offset

    schema = DataclassSchema(Seeded)
    assert schema({"base": 1, "seed": 5}).base == 16  # 1 + 5 + 10 (default offset)
    assert schema({"base": 1, "seed": 5, "offset": 0}).base == 6


def test_initvar_required_when_it_has_no_default() -> None:
    """A defaultless InitVar is Required, missing it raises Invalid, not a TypeError."""

    @dataclass
    class Seeded:
        base: int
        seed: InitVar[int]

        def __post_init__(self, seed: int) -> None:
            self.base += seed

    with pytest.raises(MultipleInvalid, match="required key not provided"):
        DataclassSchema(Seeded)({"base": 1})


def test_initvar_type_is_enforced() -> None:
    """An InitVar's annotation is enforced, so a wrong type is a clean Invalid."""

    @dataclass
    class Seeded:
        base: int
        seed: InitVar[int]

        def __post_init__(self, seed: int) -> None:
            self.base += seed

    with pytest.raises(MultipleInvalid):
        DataclassSchema(Seeded)({"base": 1, "seed": "not-an-int"})
