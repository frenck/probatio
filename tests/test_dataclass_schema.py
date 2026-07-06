"""Building a Schema from a dataclass (voluptuous PR #533, with a richer mapping).

Covers the type-annotation mapping (primitives, containers with element types,
unions, literals, nested dataclasses), default/default_factory handling,
additional constraints, instance construction, and the error paths.
"""

from __future__ import annotations

import datetime
import enum
import typing
from collections.abc import (  # noqa: TC003 - resolved at runtime by get_type_hints
    Iterable,
    Mapping,
    MutableSet,
    Sequence,
)
from dataclasses import InitVar, dataclass, field
from typing import Annotated, Any, Literal, NewType, TypedDict, TypeVar

import pytest

from probatio import (
    ALLOW_EXTRA,
    PREVENT_EXTRA,
    REMOVE_EXTRA,
    AsDatetime,
    Coerce,
    DataclassSchema,
    In,
    Invalid,
    Key,
    Length,
    MultipleInvalid,
    Range,
    SchemaError,
    Self,
    create_dataclass_schema,
    is_dataclass,
)
from probatio import Any as AnyOf
from probatio.dataclass_schema import _build_discriminant, _literal_tags
from probatio.humanize import humanize_error

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
    """A callable in Annotated metadata is applied, and the type checks the result."""
    schema = DataclassSchema(AnnotatedFields)
    assert schema({"count": 3}).count == 3

    with pytest.raises(MultipleInvalid) as caught:
        schema({"count": -1})
    assert caught.value.errors[0].path == ["count"]


def test_annotated_metadata_coerces_before_a_plain_type_check() -> None:
    """A coercer runs first and the plain-type base confirms the result, honestly typed."""

    @dataclass
    class Coerced:
        """Fields whose declared type is the result, reached through a coercer."""

        n: Annotated[int, Coerce(int)]
        when: Annotated[datetime.datetime, AsDatetime()]

    result = DataclassSchema(Coerced)({"n": "5", "when": "2020-01-01T12:00"})
    assert result.n == 5
    assert result.when == datetime.datetime(2020, 1, 1, 12, 0)


def test_annotated_plain_type_is_enforced_on_the_result() -> None:
    """A validator that yields the wrong type fails; the base type is the last word."""

    @dataclass
    class Mismatch:
        """A field whose validator (Coerce(str)) contradicts its declared int type."""

        n: Annotated[int, Coerce(str)]

    with pytest.raises(MultipleInvalid) as caught:
        DataclassSchema(Mismatch)({"n": 5})
    assert caught.value.errors[0].path == ["n"]


class _AnnColor(enum.Enum):
    """A small enum whose class coerces a string to a member (Annotated base test)."""

    RED = "red"
    BLUE = "blue"


class _AnnSlug:
    """A type that validates and normalizes itself, for the Annotated self-validate test."""

    def __init__(self, value: str) -> None:
        """Store the normalized value."""
        self.value = value

    def __eq__(self, other: object) -> bool:
        """Compare by the stored value."""
        return isinstance(other, _AnnSlug) and self.value == other.value

    __hash__ = None  # type: ignore[assignment]

    @classmethod
    def __probatio_validate__(cls, value: Any) -> _AnnSlug:
        """Accept a value, storing it lower-cased."""
        return cls(str(value).lower())


def _require_slug(value: Any) -> _AnnSlug:
    """Use-site check that only passes a produced ``_AnnSlug``, not the raw string."""
    if not isinstance(value, _AnnSlug):
        # ValueError (not TypeError) is the validator convention probatio turns into
        # an Invalid; the check proves the base coerced to a Slug before this ran.
        message = "expected a produced _AnnSlug"
        raise ValueError(message)  # noqa: TRY004
    return value


@dataclass
class _EnumShirt:
    """An enum-base Annotated field: the enum coerces before the In check runs."""

    color: Annotated[_AnnColor, In([_AnnColor.RED, _AnnColor.BLUE])]


@dataclass
class _SelfValidatingDoc:
    """A __probatio_validate__ base Annotated field: it coerces before the metadata."""

    slug: Annotated[_AnnSlug, _require_slug]


def test_annotated_enum_base_coerces_first_then_the_constraint_runs() -> None:
    """An Enum base coerces the raw value first, so a use-site constraint sees the member."""
    assert DataclassSchema(_EnumShirt)({"color": "red"}).color is _AnnColor.RED


def test_annotated_self_validating_base_coerces_first() -> None:
    """A __probatio_validate__ base (ADR-007) coerces first, so the metadata sees the result."""
    assert DataclassSchema(_SelfValidatingDoc)({"slug": "HELLO"}).slug == _AnnSlug(
        "hello"
    )


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


# --- construct(): the opt-in trusted fast path (no validation) ---


@dataclass
class _Loc:
    x: int
    y: int


@dataclass
class _Rec:
    name: str
    age: int
    tags: list[str]
    loc: _Loc
    note: str = "none"
    extra: list[int] = field(default_factory=list)


def test_construct_matches_validation_for_trusted_input() -> None:
    """construct() builds the same instance validation would, without checking."""
    schema = DataclassSchema(_Rec)
    data = {"name": "ada", "age": 30, "tags": ["a"], "loc": {"x": 1, "y": 2}}

    built = schema.construct(dict(data))

    assert built == schema(dict(data))
    assert built.note == "none"  # default filled
    assert built.extra == []  # factory default filled
    assert type(built.loc) is _Loc  # nested built as a real instance, not a dict


def test_construct_builds_a_list_of_nested_dataclasses() -> None:
    """A list of dataclasses is built per item."""

    @dataclass
    class Bag:
        items: list[_Loc]

    schema = DataclassSchema(Bag)
    built = schema.construct({"items": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]})
    assert built.items == [_Loc(1, 2), _Loc(3, 4)]
    assert type(built.items[0]) is _Loc


def test_construct_trusts_the_input_and_skips_validation() -> None:
    """A wrong type passes straight through construct(); validation would reject it."""
    schema = DataclassSchema(_Loc)
    built = schema.construct({"x": "not-an-int", "y": 2})
    assert built == _Loc(x="not-an-int", y=2)  # unchecked, trusted
    with pytest.raises(MultipleInvalid):
        schema({"x": "not-an-int", "y": 2})


def test_construct_caches_the_constructor() -> None:
    """The constructor is built once and reused across calls."""
    schema = DataclassSchema(_Loc)
    schema.construct({"x": 1, "y": 2})
    first = schema._construct_fn
    schema.construct({"x": 3, "y": 4})
    assert schema._construct_fn is first


def test_construct_falls_back_for_a_recursive_dataclass() -> None:
    """A self-referential dataclass is not fast-built; construct() validates instead."""
    schema = DataclassSchema(Node)  # nxt: Node | None
    assert schema._fast_constructor() is None

    data = {"value": 1, "nxt": {"value": 2}}
    assert schema.construct(dict(data)) == schema(dict(data))


def test_construct_falls_back_for_a_recursive_list_dataclass() -> None:
    """A list-of-self dataclass falls back to validation too."""
    schema = DataclassSchema(Tree)  # children: list[Tree]
    assert schema._fast_constructor() is None

    data = {"name": "root", "children": [{"name": "leaf", "children": []}]}
    assert schema.construct(dict(data)) == schema(dict(data))


def test_construct_falls_back_for_a_nested_unbuildable_dataclass() -> None:
    """A field whose nested dataclass cannot be fast-built falls the whole thing back."""

    @dataclass
    class HasNode:
        n: Node

    schema = DataclassSchema(HasNode)
    assert schema._fast_constructor() is None

    data = {"n": {"value": 1}}
    assert schema.construct(dict(data)) == schema(dict(data))


def test_construct_falls_back_for_a_dataclass_behind_a_container() -> None:
    """A dataclass behind a tuple (not a plain list) is left to validation."""

    @dataclass
    class Pair:
        points: tuple[_Loc, _Loc]

    schema = DataclassSchema(Pair)
    assert schema._fast_constructor() is None


def test_construct_builds_optional_and_union_fields() -> None:
    """construct() fast-builds Optional, list-of-Optional, and single-dataclass Union."""

    @dataclass
    class Has:
        loc: _Loc | None
        items: list[_Loc | None]
        tagged: _Loc | str
        count: int | None = None  # Optional scalar passes straight through

    schema = DataclassSchema(Has)
    assert schema._fast_constructor() is not None

    built = schema.construct(
        {
            "loc": {"x": 1, "y": 2},
            "items": [{"x": 3, "y": 4}, None],
            "tagged": {"x": 5, "y": 6},
            "count": 7,
        }
    )

    assert built.loc == _Loc(1, 2)
    assert built.items == [_Loc(3, 4), None]
    assert type(built.items[0]) is _Loc
    assert built.tagged == _Loc(5, 6)
    assert built.count == 7
    # A None Optional, and the str branch of the union (not a dict).
    other = schema.construct({"loc": None, "items": [], "tagged": "label"})
    assert other.loc is None
    assert other.tagged == "label"
    assert other.count is None


def test_construct_falls_back_for_optional_unbuildable() -> None:
    """An Optional wrapping a shape the fast path cannot build falls back."""

    @dataclass
    class Has:
        pair: tuple[_Loc, _Loc] | None

    assert DataclassSchema(Has)._fast_constructor() is None


def test_construct_falls_back_for_a_union_of_two_dataclasses() -> None:
    """A Union of two dataclasses cannot be told apart at runtime, so it falls back."""

    @dataclass
    class A:
        v: int

    @dataclass
    class B:
        w: int

    @dataclass
    class Amb:
        thing: A | B

    assert DataclassSchema(Amb)._fast_constructor() is None


def test_construct_falls_back_for_a_union_with_a_dict_alternative() -> None:
    """A dataclass-or-dict union is ambiguous (both are dicts), so it falls back."""

    @dataclass
    class Has:
        thing: _Loc | dict[str, int]

    assert DataclassSchema(Has)._fast_constructor() is None


def test_construct_falls_back_for_a_union_with_a_mapping_alternative() -> None:
    """A Mapping alternative is dict-shaped at runtime, so the union falls back.

    ``Mapping[...]`` resolves to ``collections.abc.Mapping``, not ``dict``, but a dict
    still satisfies it, so it is ambiguous with the dataclass branch the same way a
    plain ``dict`` is. Without falling back, a mapping value would be fed to the
    dataclass constructor.
    """

    @dataclass
    class Has:
        thing: _Loc | Mapping[str, int]

    schema = DataclassSchema(Has)
    assert schema._fast_constructor() is None
    # And it still builds the right thing through the validating fallback.
    assert schema.construct({"thing": {"k": 1}}) == schema({"thing": {"k": 1}})


class _Movie(TypedDict):
    """A module-level TypedDict, so get_type_hints can resolve it in an annotation."""

    title: str


@dataclass
class _HasMovie:
    thing: _Loc | _Movie


def test_construct_falls_back_for_a_union_with_a_typeddict_alternative() -> None:
    """A TypedDict alternative is a plain dict at runtime, so the union falls back."""
    assert DataclassSchema(_HasMovie)._fast_constructor() is None


def test_construct_falls_back_for_a_union_with_a_recursive_dataclass() -> None:
    """A union member that cannot itself be fast-built falls the whole thing back."""

    @dataclass
    class Has:
        thing: Node | str

    assert DataclassSchema(Has)._fast_constructor() is None


def test_construct_passes_through_an_already_built_nested_instance() -> None:
    """A nested field already holding an instance is used as-is, not subscripted.

    construct() builds a nested dataclass from a dict; handed the built instance
    instead (a partially constructed input), it passes it through rather than calling
    the child constructor on a non-dict, which would crash.
    """

    @dataclass
    class Has:
        loc: _Loc

    schema = DataclassSchema(Has)
    built = schema.construct({"loc": _Loc(1, 2)})
    assert built.loc == _Loc(1, 2)
    assert type(built.loc) is _Loc


def test_construct_aliases_a_trusted_plain_list() -> None:
    """A plain-list field is passed through, not copied, where validation rebuilds it.

    construct() trusts the input, so it aliases a ``list[int]`` it does not need to
    rebuild; the validating call returns a fresh list. Both hold equal values.
    """

    @dataclass
    class Tagged:
        tags: list[int]

    schema = DataclassSchema(Tagged)
    source = [1, 2, 3]
    assert schema.construct({"tags": source}).tags is source  # aliased, trusted

    validated = schema({"tags": source})
    assert validated.tags is not source  # validation rebuilds a fresh list
    assert validated.tags == source


# --- Key field metadata (ADR-013) ----------------------------------------------


def test_key_secret_redacts_the_value() -> None:
    """Key(secret=True) redacts the field's value in errors."""

    @dataclass
    class Login:
        user: str
        password: Annotated[str, Key(secret=True)]

    data = {"user": "bob", "password": 123}
    with pytest.raises(MultipleInvalid) as caught:
        DataclassSchema(Login)(data)
    assert "<redacted>" in humanize_error(data, caught.value)


def test_key_secret_composes_with_a_value_validator() -> None:
    """A Key facet and a value validator coexist in one annotation."""

    @dataclass
    class Login:
        password: Annotated[str, Key(secret=True), Length(min=8)]

    data = {"password": "short"}
    with pytest.raises(MultipleInvalid) as caught:
        DataclassSchema(Login)(data)
    assert "<redacted>" in humanize_error(data, caught.value)


def test_key_alias_accepts_multiple_names() -> None:
    """Key(alias=[...]) accepts several input names, emitting the field name."""

    @dataclass
    class Cfg:
        user_name: Annotated[str, Key(alias=["user-name", "userName"])] = "x"

    schema = create_dataclass_schema(Cfg)
    assert schema({"user-name": "ada"}).user_name == "ada"
    assert schema({"userName": "eve"}).user_name == "eve"
    assert schema({}).user_name == "x"


def test_key_alias_single_string() -> None:
    """Key(alias="one") accepts a bare string as a single alias."""

    @dataclass
    class Cfg:
        user_name: Annotated[str, Key(alias="user-name")] = "x"

    assert create_dataclass_schema(Cfg)({"user-name": "ada"}).user_name == "ada"


def test_key_alias_default_is_validated() -> None:
    """The field default is validated through the value schema, like the plain path."""

    @dataclass
    class Bad:
        x: Annotated[int, Key(alias=["y"])] = "not-an-int"  # noqa: RUF100

    with pytest.raises(MultipleInvalid):
        create_dataclass_schema(Bad)({})


def test_key_forbidden_rejects_a_supplied_value() -> None:
    """Key(forbidden=True) rejects a caller-supplied field, else uses the default."""

    @dataclass
    class Account:
        name: str
        is_admin: Annotated[bool, Key(forbidden=True)] = False

    schema = create_dataclass_schema(Account)
    assert schema({"name": "bob"}).is_admin is False
    with pytest.raises(MultipleInvalid):
        schema({"name": "bob", "is_admin": True})


def test_key_forbidden_without_default_is_a_schema_error() -> None:
    """A Forbidden dataclass field is never supplied, so it must have a default."""

    @dataclass
    class Bad:
        is_admin: Annotated[bool, Key(forbidden=True)]

    with pytest.raises(SchemaError, match="needs a default"):
        create_dataclass_schema(Bad)


def test_key_remove_drops_a_validated_value() -> None:
    """Key(remove=True) validates its value, then drops it so the default is used."""

    @dataclass
    class Cfg:
        legacy: Annotated[int, Key(remove=True)] = 0

    assert create_dataclass_schema(Cfg)({"legacy": 5}).legacy == 0


def test_key_exclusive_group() -> None:
    """Key(exclusive=group) allows at most one of the group's fields."""

    @dataclass
    class Auth:
        token: Annotated[str, Key(exclusive="auth")] = ""
        secret: Annotated[str, Key(exclusive="auth")] = ""

    schema = create_dataclass_schema(Auth)
    assert schema({"token": "t"}).token == "t"  # noqa: S105
    with pytest.raises(MultipleInvalid):
        schema({"token": "t", "secret": "s"})


def test_key_inclusive_group() -> None:
    """Key(inclusive=group) requires the group's fields together, or none."""

    @dataclass
    class Point:
        x: Annotated[int, Key(inclusive="xy")] = 0
        y: Annotated[int, Key(inclusive="xy")] = 0

    schema = create_dataclass_schema(Point)
    assert schema({"x": 1, "y": 2}).x == 1
    with pytest.raises(MultipleInvalid):
        schema({"x": 1})


def test_key_required_overrides_a_default() -> None:
    """Key(required=True) forces presence even when the field has a default."""

    @dataclass
    class Cfg:
        mode: Annotated[str, Key(required=True)] = "auto"

    schema = create_dataclass_schema(Cfg)
    assert schema({"mode": "manual"}).mode == "manual"
    with pytest.raises(MultipleInvalid):
        schema({})


def test_key_optional_without_default_is_a_schema_error() -> None:
    """An optional field that can be absent needs a default to construct from."""

    @dataclass
    class Cfg:
        mode: Annotated[str, Key(required=False)]

    with pytest.raises(SchemaError, match="needs a default"):
        create_dataclass_schema(Cfg)


def test_key_conflicting_facets_is_a_schema_error() -> None:
    """Two role-defining facets on one Key are a schema error."""

    @dataclass
    class Bad:
        x: Annotated[str, Key(forbidden=True, alias=["y"])] = "z"

    with pytest.raises(SchemaError, match="conflicting facets"):
        create_dataclass_schema(Bad)


def test_two_key_specs_on_a_field_is_a_schema_error() -> None:
    """A field may carry at most one Key spec."""

    @dataclass
    class Bad:
        x: Annotated[str, Key(secret=True), Key(alias=["y"])] = "z"

    with pytest.raises(SchemaError, match="more than one Key"):
        create_dataclass_schema(Bad)


def test_key_forbidden_default_is_the_dataclass_default_untouched() -> None:
    """A Forbidden field reaches the constructor as the raw, uncoerced dataclass default."""

    @dataclass
    class Cfg:
        x: Annotated[int, Key(forbidden=True)] = "as-is"  # noqa: RUF100

    assert create_dataclass_schema(Cfg)({}).x == "as-is"


def test_key_alias_is_honored_by_construct() -> None:
    """construct() falls back to validation so a Key alias still resolves."""

    @dataclass
    class Cfg:
        user_name: Annotated[str, Key(alias=["user-name"])] = "x"

    schema = DataclassSchema(Cfg)
    assert schema.construct({"user-name": "ada"}).user_name == "ada"


def test_key_exclusive_custom_message() -> None:
    """A Key(msg=...) on a group reaches the group's error."""

    @dataclass
    class Auth:
        a: Annotated[int, Key(exclusive="g", msg="pick exactly one")] = 0
        b: Annotated[int, Key(exclusive="g", msg="pick exactly one")] = 0

    with pytest.raises(MultipleInvalid) as caught:
        create_dataclass_schema(Auth)({"a": 1, "b": 2})
    assert caught.value.errors[0].error_message == "pick exactly one"


def test_key_inclusive_with_required_is_a_schema_error() -> None:
    """required does not apply to an inclusive (all-or-none) group."""

    @dataclass
    class Bad:
        a: Annotated[int, Key(inclusive="g", required=True)] = 0

    with pytest.raises(SchemaError, match="required does not apply"):
        create_dataclass_schema(Bad)


def test_key_forbidden_with_required_is_a_schema_error() -> None:
    """required does not apply to a Forbidden field (never taken from the input)."""

    @dataclass
    class Bad:
        a: Annotated[int, Key(forbidden=True, required=True)] = 0

    with pytest.raises(SchemaError, match="required does not apply to Forbidden"):
        create_dataclass_schema(Bad)


def test_key_remove_with_required_is_a_schema_error() -> None:
    """required does not apply to a Remove field (dropped after validation)."""

    @dataclass
    class Bad:
        a: Annotated[int, Key(remove=True, required=True)] = 0

    with pytest.raises(SchemaError, match="required does not apply to Remove"):
        create_dataclass_schema(Bad)


def test_key_forbidden_default_is_not_coerced() -> None:
    """A Forbidden field's default is used as-is, not run through a coercing schema."""

    @dataclass
    class Cfg:
        x: Annotated[int, Key(forbidden=True), Coerce(int)] = "1"

    # The plain path would coerce an absent default to ``1``; a forbidden field keeps
    # the dataclass's own ``"1"`` (its value is never schema-managed input).
    assert create_dataclass_schema(Cfg)({}).x == "1"


def test_key_remove_invalid_value_does_not_reach_the_constructor() -> None:
    """A Remove field always takes its default, even a value ALLOW_EXTRA kept."""

    @dataclass
    class Cfg:
        legacy: Annotated[int, Key(remove=True)] = 0

    # Under ALLOW_EXTRA the failed value is kept in the dict, but the Remove field is
    # dropped at construction, so it never lands in the instance.
    assert DataclassSchema(Cfg, extra=ALLOW_EXTRA)({"legacy": "bad"}).legacy == 0
    assert DataclassSchema(Cfg)({"legacy": 5}).legacy == 0


def test_key_required_exclusive_group_is_enforced_with_defaults() -> None:
    """Key(exclusive, required=True) requires a member even when fields have defaults."""

    @dataclass
    class Auth:
        token: Annotated[str, Key(exclusive="auth", required=True)] = ""
        secret: Annotated[str, Key(exclusive="auth", required=True)] = ""

    schema = create_dataclass_schema(Auth)
    with pytest.raises(MultipleInvalid):
        schema({})  # required group: a default must not satisfy it
    assert schema({"token": "t"}).token == "t"  # noqa: S105
    with pytest.raises(MultipleInvalid):
        schema({"token": "t", "secret": "s"})


@dataclass
class _GuardedWeight:
    """A dataclass whose __post_init__ enforces its own invariant with ValueError."""

    weight: float

    def __post_init__(self) -> None:
        if self.weight < 0:
            message = "weight must not be negative"
            raise ValueError(message)


@pytest.mark.parametrize("extra", [None, ALLOW_EXTRA])
def test_post_init_valueerror_becomes_value_invalid(extra: int | None) -> None:
    """A ValueError from __post_init__ is reported as 'not a valid value: <reason>'.

    Parametrized over the default and ALLOW_EXTRA schemas, which run the two
    fused engine variants (direct splat and constructor filter); both must
    normalize identically, chain included: the ValueInvalid's cause is the
    original ValueError.
    """
    kwargs = {} if extra is None else {"extra": extra}
    schema = DataclassSchema(_GuardedWeight, **kwargs)

    with pytest.raises(MultipleInvalid) as caught:
        schema({"weight": -1.0})

    (error,) = caught.value.errors
    assert error.msg == "not a valid value: weight must not be negative"
    assert isinstance(error.__cause__, ValueError)
    assert schema({"weight": 1.0}).weight == 1.0


@dataclass
class _SilentGuard:
    """A dataclass whose __post_init__ raises a bare, message-less ValueError."""

    weight: float

    def __post_init__(self) -> None:
        if self.weight < 0:
            raise ValueError


def test_post_init_bare_valueerror_reports_generic_message() -> None:
    """A message-less ValueError from __post_init__ reads 'not a valid value'."""
    schema = DataclassSchema(_SilentGuard)

    with pytest.raises(MultipleInvalid) as caught:
        schema({"weight": -1.0})

    (error,) = caught.value.errors
    assert error.msg == "not a valid value"
    assert error.translation_key == "not_a_valid_value"


@pytest.mark.parametrize("extra", [None, ALLOW_EXTRA])
def test_post_init_invalid_is_wrapped_not_normalized(extra: int | None) -> None:
    """An Invalid raised by __post_init__ surfaces as itself, wrapped once."""

    @dataclass
    class Guarded:
        value: int

        def __post_init__(self) -> None:
            if self.value == 13:
                message = "thirteen is right out"
                raise Invalid(message)

    kwargs = {} if extra is None else {"extra": extra}
    schema = DataclassSchema(Guarded, **kwargs)

    with pytest.raises(MultipleInvalid) as caught:
        schema({"value": 13})

    (error,) = caught.value.errors
    assert error.msg == "thirteen is right out"


@pytest.mark.parametrize("extra", [None, ALLOW_EXTRA])
def test_post_init_multiple_invalid_passes_through(extra: int | None) -> None:
    """A MultipleInvalid raised by __post_init__ is not wrapped a second time."""

    @dataclass
    class Guarded:
        value: int

        def __post_init__(self) -> None:
            if self.value == 13:
                raise MultipleInvalid([Invalid("a"), Invalid("b")])

    kwargs = {} if extra is None else {"extra": extra}
    schema = DataclassSchema(Guarded, **kwargs)

    with pytest.raises(MultipleInvalid) as caught:
        schema({"value": 13})

    assert [error.msg for error in caught.value.errors] == ["a", "b"]


def test_self_constraint_keeps_the_tower_and_still_validates() -> None:
    """A Self-using constraint skips the fused engine and validates recursively.

    ``Self`` resolution rides the inner ``Schema.__call__``'s active-root
    bookkeeping, which the fused engine bypasses, so such a schema keeps the
    ``All`` tower. This pins that the guard triggers and the behavior matches
    the pre-fuse engine: recursion works and a deep error carries its full path.
    """

    @dataclass
    class Tree:
        name: str
        child: object = None

    schema = DataclassSchema(Tree, {"child": AnyOf(Self, None)}, compile=False)

    built = schema({"name": "a", "child": {"name": "b", "child": None}})
    assert built.name == "a"
    assert built.child == {"name": "b", "child": None}

    with pytest.raises(MultipleInvalid) as caught:
        schema({"name": "a", "child": {"name": 1, "child": None}})
    (error,) = caught.value.errors
    assert error.path == ["child", "name"]


# --- extra propagates into nested schemas (handoff: nested extra recursion) ---


@dataclass
class _XInner:
    a: int = 0


@dataclass
class _XOuter:
    inner: _XInner = field(default_factory=_XInner)
    x: int = 0


@dataclass
class _XItem:
    id: int = 0


@dataclass
class _XColl:
    items: list[_XItem] = field(default_factory=list)


@dataclass
class _XEco:
    enabled: bool = False


@dataclass
class _XCtrl:
    eco: _XEco | None = None


@dataclass
class _XL3:
    v: int = 0


@dataclass
class _XL2:
    three: _XL3 = field(default_factory=_XL3)


@dataclass
class _XL1:
    two: _XL2 = field(default_factory=_XL2)


@dataclass
class _XNode:
    name: str = ""
    child: _XNode | None = None


@dataclass
class _XStrict:
    b: int = 0


@dataclass
class _XMixed:
    loose: _XInner = field(default_factory=_XInner)
    strict: Annotated[_XStrict, Key(extra=PREVENT_EXTRA)] = field(
        default_factory=_XStrict
    )


@dataclass
class _XLoosenedOuter:
    loose: Annotated[_XInner, Key(extra=REMOVE_EXTRA)] = field(default_factory=_XInner)


@pytest.mark.parametrize("extra", [REMOVE_EXTRA, ALLOW_EXTRA])
def test_extra_recurses_into_a_nested_dataclass(extra: int) -> None:
    """REMOVE_EXTRA and ALLOW_EXTRA drop an unknown key one level down too."""
    data = {"x": 1, "junk": 9, "inner": {"a": 2, "innerjunk": 3}}
    assert DataclassSchema(_XOuter, extra=extra)(data) == _XOuter(_XInner(a=2), x=1)


def test_nested_extra_default_still_rejects() -> None:
    """The default (PREVENT_EXTRA) still raises on a nested unknown key."""
    with pytest.raises(MultipleInvalid) as caught:
        DataclassSchema(_XOuter)({"inner": {"a": 2, "innerjunk": 3}})
    (error,) = caught.value.errors
    assert error.path == ["inner", "innerjunk"]


def test_extra_recurses_under_compilation() -> None:
    """The compiled engine inherits the propagated nested policy (issue parity)."""
    data = {"x": 1, "junk": 9, "inner": {"a": 2, "innerjunk": 3}}
    interpreted = DataclassSchema(_XOuter, extra=REMOVE_EXTRA)
    compiled = DataclassSchema(_XOuter, extra=REMOVE_EXTRA, compile=True).compile()
    assert interpreted(dict(data)) == compiled(dict(data)) == _XOuter(_XInner(2), 1)


def test_extra_recurses_into_a_list_of_dataclasses() -> None:
    """A junk key inside a list element is dropped under REMOVE_EXTRA."""
    result = DataclassSchema(_XColl, extra=REMOVE_EXTRA)({"items": [{"id": 1, "j": 2}]})
    assert result == _XColl(items=[_XItem(id=1)])


def test_extra_recurses_into_an_optional_nested_dataclass() -> None:
    """A junk key inside an ``X | None`` nested dataclass is dropped."""
    result = DataclassSchema(_XCtrl, extra=REMOVE_EXTRA)(
        {"eco": {"enabled": True, "j": 1}}
    )
    assert result == _XCtrl(eco=_XEco(enabled=True))


def test_extra_recurses_all_the_way_down() -> None:
    """The policy holds three levels deep."""
    data = {"two": {"three": {"v": 1, "junk": 2}}}
    assert DataclassSchema(_XL1, extra=REMOVE_EXTRA)(data) == _XL1(_XL2(_XL3(1)))


def test_extra_recurses_across_a_recursive_edge() -> None:
    """A self-referential tree keeps the policy at depth two and beyond."""
    data = {"name": "a", "junk": 1, "child": {"name": "b", "junk": 2, "child": None}}
    result = DataclassSchema(_XNode, extra=REMOVE_EXTRA)(data)
    assert result == _XNode(name="a", child=_XNode(name="b", child=None))


def test_key_extra_pins_a_strict_subtree_inside_a_loose_schema() -> None:
    """Key(extra=PREVENT_EXTRA) keeps one field strict while the rest is loose."""
    data = {"loose": {"a": 1, "j": 2}, "strict": {"b": 1, "j": 3}}
    with pytest.raises(MultipleInvalid) as caught:
        DataclassSchema(_XMixed, extra=REMOVE_EXTRA)(data)
    (error,) = caught.value.errors
    assert error.path == ["strict", "j"]


def test_key_extra_pins_a_loose_subtree_inside_a_strict_schema() -> None:
    """Key(extra=REMOVE_EXTRA) loosens one field while the schema stays strict."""
    result = DataclassSchema(_XLoosenedOuter)({"loose": {"a": 5, "junk": 9}})
    assert result == _XLoosenedOuter(loose=_XInner(a=5))
