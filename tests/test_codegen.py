"""Tests for the compiled-variant code generator (the ``compile`` flag).

A compiled schema must be behaviorally identical to its interpreted twin; the
generator's whole safety argument is that any failure bails to the interpreted
validator. These tests pin both the parity and which shapes do (and do not)
generate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import TypedDict

import pytest

from probatio import (
    ALLOW_EXTRA,
    REMOVE_EXTRA,
    UNDEFINED,
    All,
    Any,
    Coerce,
    CompilePolicy,
    DataclassSchema,
    Exclusive,
    Forbidden,
    In,
    MultipleInvalid,
    Optional,
    Range,
    Remove,
    Required,
    Schema,
    Self,
    TypedDictSchema,
    from_json_schema,
    set_compile_policy,
)
from probatio._codegen import compile_mapping
from probatio._engine import _MappingValidator
from probatio.codecs.jsonschema import _DeferredRef
from probatio.schema import _AUTO_COMPILE_THRESHOLD


def _is_compiled(schema: Schema) -> bool:
    """Report whether the schema swapped in a generated validator."""
    return getattr(schema._compiled, "__name__", "") == "_validate"


def _outcome(schema: Schema, data: object) -> object:
    """Reduce a validation to a comparable result or a structured error."""
    try:
        result = schema(data)
    except MultipleInvalid as err:
        return (
            "err",
            str(err),
            tuple(tuple(e.path) for e in err.errors),
            tuple(e.code for e in err.errors),
        )
    return ("ok", result, type(result).__name__)


# Schema builders, each exercised interpreted and compiled. Keep them varied:
# types, defaults, a declining default, Coerce/Range/In, nested, and each extra
# policy.
_BUILDERS = {
    "types": lambda **k: Schema(
        {Required("n"): str, "p": int, "ok": bool, "f": float}, **k
    ),
    "defaults": lambda **k: Schema(
        {Required("n"): str, Optional("p", default=8080): int}, **k
    ),
    "factory_default": lambda **k: Schema({Optional("tags", default=list): [str]}, **k),
    "declining_default": lambda **k: Schema(
        {Optional("x", default=lambda: UNDEFINED): int}, **k
    ),
    "coerce_range": lambda **k: Schema(
        {Optional("port", default=80): All(Coerce(int), Range(min=1, max=65535))}, **k
    ),
    "membership": lambda **k: Schema({Optional("mode"): In(["a", "b", "c"])}, **k),
    # Keyed on "x" so the unhashable "x" inputs reach the frozenset membership: an
    # unhashable value must bail to the engine, not crash the generated code.
    "in_value": lambda **k: Schema({"x": In(["a", "b", "c"])}, **k),
    "nested": lambda **k: Schema(
        {Required("srv"): {Required("host"): str, "port": int}}, **k
    ),
    "any_value": lambda **k: Schema({"v": Any(int, str)}, **k),
    "allow_extra": lambda **k: Schema({"a": int}, extra=ALLOW_EXTRA, **k),
    "remove_extra": lambda **k: Schema({"a": int}, extra=REMOVE_EXTRA, **k),
    # Inlining variety: float coerce, a one-sided exclusive range with a bare type
    # in the All chain, non-numeric range bounds (closure), case-folding In
    # (closure), an unhashable In container (list fallback), an Enum (closure), and
    # an All whose second branch is a plain callable (closure).
    "coerce_float": lambda **k: Schema({"x": Coerce(float)}, **k),
    "range_excl": lambda **k: Schema(
        {"x": All(int, Range(min=0, max=10, min_included=False, max_included=False))},
        **k,
    ),
    "range_strings": lambda **k: Schema({"x": Range(min="a", max="z")}, **k),
    "in_fold": lambda **k: Schema({"x": In(["a", "b"], fold_case=True)}, **k),
    "in_unhashable": lambda **k: Schema({"x": In([[1], [2]])}, **k),
    "enum_value": lambda **k: Schema({"x": _Color}, **k),
    "all_callable": lambda **k: Schema({"x": All(int, lambda v: v)}, **k),
    "coerce_str": lambda **k: Schema({"x": Coerce(str)}, **k),
    "range_min_only": lambda **k: Schema({"x": All(int, Range(min=0))}, **k),
    "range_max_only": lambda **k: Schema({"x": All(int, Range(max=100))}, **k),
    # Any inlining: all-types with None (allow_none), and a mixed Any with a
    # non-type branch that falls back to the closure.
    "any_maybe": lambda **k: Schema({"x": Any(int, None)}, **k),
    "any_mixed": lambda **k: Schema({"x": Any(int, In(["a", "b"]))}, **k),
    # Maybe(X): one inlinable branch plus None inlines as a None guard around X; a
    # non-inlinable inner branch falls back to the closure. A two-non-None mixed Any
    # is left to the closure on purpose (a cascade could defer-then-mismatch).
    "maybe_validated": lambda **k: Schema(
        {"x": Any(All(Coerce(int), Range(min=0)), None)}, **k
    ),
    "maybe_noninline": lambda **k: Schema(
        {"x": Any(In(["a", "b"], fold_case=True), None)}, **k
    ),
    "any_unsound": lambda **k: Schema({"x": Any(Coerce(int), float)}, **k),
    # An all-literal Any is a membership test, inlined like In; a literal Any with
    # None mixed in still inlines (None is a member); a mixed type/literal does not.
    "any_literals": lambda **k: Schema({"x": Any("a", "b", "c")}, **k),
    "any_literals_none": lambda **k: Schema({"x": Any("on", "off", None)}, **k),
    # Sequence inlining: a single inlinable element (compiled to a loop), a
    # transforming element (Coerce per item), a multi-element list (an each-item
    # union, left to the closure), and a non-inlinable element (also a closure).
    "list_type": lambda **k: Schema({"x": [str]}, **k),
    "list_coerce": lambda **k: Schema({"x": [All(Coerce(int), Range(min=0))]}, **k),
    "list_multi": lambda **k: Schema({"x": [str, int]}, **k),
    "list_closure": lambda **k: Schema({"x": [In(["a", "b"], fold_case=True)]}, **k),
    # A nested mapping value, compiled recursively (the inner mapping generates too).
    "nested_map": lambda **k: Schema(
        {Required("srv"): {Required("host"): str, "port": int}}, **k
    ),
}


class _Color(Enum):
    RED = "red"
    BLUE = "blue"


class _Svc(StrEnum):
    """A string enum: its members are str instances, but repr is not source."""

    ON = "on"
    OFF = "off"


_INPUTS: list[object] = [
    {"n": "x", "p": 1, "ok": True, "f": 1.5},
    {"n": "x"},
    {},
    {"p": "443"},
    {"port": "80"},
    {"port": 99999},
    {"mode": "a"},
    {"mode": "z"},
    {"srv": {"host": "h", "port": 2}},
    {"srv": {"host": 5}},
    {"srv": "no"},
    {"a": 1, "b": 2},
    {"a": "no"},
    {"x": 3},
    {"v": 1},
    {"v": [1]},
    {"n": 1},
    {"tags": ["a", "b"]},
    {"tags": [1]},
    {"unexpected": 1},
    # Exercise the inlined value paths (float coerce, exclusive/string range,
    # case-folding and unhashable In, Enum, callable All).
    {"x": 1.5},
    {"x": 5},
    {"x": "5"},
    {"x": [1]},
    {"x": [9]},
    {"x": ["a", "b"]},
    {"x": ["5", "10"]},
    {"x": ["A"]},
    {"x": [1, "a"]},
    {"x": "a"},
    {"x": "off"},
    {"x": "m"},
    {"x": "A"},
    {"x": "red"},
    {"x": 0},
    {"x": []},
    {"x": -1},
    {"x": 200},
    {"x": "hi"},
    {"x": None},
]


@pytest.mark.parametrize("name", list(_BUILDERS))
def test_compiled_matches_interpreted(name: str) -> None:
    """A compiled schema returns and raises exactly what the interpreted one does."""
    interpreted = _BUILDERS[name](compile=False)
    compiled = _BUILDERS[name](compile=True)
    for data in _INPUTS:
        assert _outcome(interpreted, dict(data)) == _outcome(  # type: ignore[arg-type]
            compiled,
            dict(data),  # type: ignore[arg-type]
        )
    # The first call above resolved the lazy bootstrap; confirm it actually compiled.
    assert _is_compiled(compiled)


def test_same_shape_schemas_stay_isolated_through_the_code_cache() -> None:
    """Same-shape schemas reuse the cached code object but keep their own validators.

    ``{"x": int}`` and ``{"x": str}`` generate byte-identical source, so they share
    one cached code object; the difference lives in each schema's namespace. Each must
    still enforce its own type.
    """
    a = Schema({"x": int}, compile=True).compile()
    b = Schema({"x": str}, compile=True).compile()
    assert _is_compiled(a)
    assert _is_compiled(b)
    assert a({"x": 1}) == {"x": 1}
    assert b({"x": "hi"}) == {"x": "hi"}
    assert _outcome(a, {"x": "no"})[0] == "err"
    assert _outcome(b, {"x": 5})[0] == "err"


def test_dict_subclass_is_preserved_when_compiled() -> None:
    """The compiled fast path preserves a dict subclass, like the engine."""

    class Node(dict):
        pass

    compiled = Schema({"a": int}, compile=True)
    result = compiled(Node({"a": 1}))
    assert result == {"a": 1}
    assert type(result) is Node


def test_foreign_mapping_falls_back_to_interpreted() -> None:
    """A non-dict Mapping takes the interpreted path and still validates."""
    compiled = Schema({"a": int}, compile=True)
    assert compiled(MappingProxyType({"a": 1})) == {"a": 1}


def test_required_missing_bails_to_the_real_error() -> None:
    """A missing required key produces the interpreted error after bailing."""
    compiled = Schema({Required("a"): int}, compile=True)
    with pytest.raises(MultipleInvalid) as caught:
        compiled({})
    assert caught.value.errors[0].code == "required"


def test_compiled_membership_treats_arithmetic_error_like_interpreted() -> None:
    """A value whose comparison overflows is a miss in both engines, never a leak.

    Interpreted ``In`` catches ``(TypeError, ArithmeticError)`` and reports a miss, so
    the inlined membership must catch both too rather than letting the error escape
    the compiled function.
    """

    class _Boom:
        __hash__ = object.__hash__

        def __eq__(self, other: object) -> bool:
            raise ArithmeticError

    # An unhashable member forces the list-fallback membership, whose linear scan
    # compares each member to the value and so reaches the value's __eq__.
    interpreted = Schema({"x": In([[1], "a"])}, compile=False)
    compiled = Schema({"x": In([[1], "a"])}, compile=True)
    assert _outcome(interpreted, {"x": _Boom()}) == _outcome(compiled, {"x": _Boom()})
    assert _is_compiled(compiled)


def test_compiled_membership_reflects_a_mutated_container() -> None:
    """A compiled In binds the live container, so a later mutation is seen, as engine.

    The interpreted In tests against its live container; the compiled path binds the
    same object rather than a frozen snapshot, so emptying the container after the
    schema is built rejects a value both engines now reject.
    """
    choices = ["a", "b"]
    interpreted = Schema({"x": In(choices)}, compile=False)
    compiled = Schema({"x": In(choices)}, compile=True).compile()
    assert compiled({"x": "a"}) == {"x": "a"}  # compiles and accepts a member
    choices.clear()
    assert _outcome(interpreted, {"x": "a"}) == _outcome(compiled, {"x": "a"})


@pytest.mark.parametrize(
    "builder",
    [
        lambda: Schema({Exclusive("a", "g"): int, Exclusive("b", "g"): int}),
        lambda: Schema({Required(Any("a", "b")): int}),
        lambda: Schema({str: int}),
        lambda: Schema({Remove("a"): int}),
        lambda: Schema({Forbidden("a"): int}),
        lambda: Schema({1: int}),
    ],
)
def test_unsupported_shapes_stay_interpreted(builder: object) -> None:
    """A shape the generator does not handle keeps its interpreted validator."""
    schema = builder()  # type: ignore[operator]
    schema.compile()
    assert isinstance(schema._compiled, _MappingValidator)


def test_recursive_schema_is_not_compiled() -> None:
    """A Self-referential schema is left interpreted (compilation skips it)."""
    schema = Schema(
        {Required("v"): int, Optional("next"): Self}, compile=True
    ).compile()
    assert not _is_compiled(schema)


def test_compile_is_idempotent() -> None:
    """Calling compile() twice leaves a single generated validator in place."""
    schema = Schema({"a": int}).compile()
    first = schema._compiled
    schema.compile()
    assert schema._compiled is first


def test_invalid_extra_policy_stays_interpreted() -> None:
    """An out-of-range extra policy is not generated; the engine still handles it."""
    schema = Schema({"a": int}, extra=99).compile()
    assert not _is_compiled(schema)
    assert schema({"a": 1}) == {"a": 1}


def test_strenum_key_stays_interpreted() -> None:
    """A StrEnum key is a str, but its repr is not source to emit, so it bails."""
    schema = Schema({_Svc.ON: int}, compile=True).compile()
    assert not _is_compiled(schema)
    assert schema({_Svc.ON: 1}) == {_Svc.ON: 1}


def test_recursive_ref_mapping_is_not_generatable() -> None:
    """A mapping holding a recursive $ref is not compiled, so a deep failure cannot
    trigger an exponential bail-to-interpreted cascade. The node holding the
    back-reference stays interpreted, the way Self recursion does.
    """
    ref = _DeferredRef()
    ref.schema = Schema({"v": int})
    mapping = Schema({"next": ref})
    assert isinstance(mapping._compiled, _MappingValidator)
    assert compile_mapping(mapping._compiled) is None


def test_recursive_ref_inside_a_combinator_is_not_generatable() -> None:
    """A recursive $ref nested in an Any value is found by the combinator walk."""
    ref = _DeferredRef()
    ref.schema = Schema({"v": int})
    mapping = Schema({"next": Any(int, ref)})
    assert isinstance(mapping._compiled, _MappingValidator)
    assert compile_mapping(mapping._compiled) is None


def test_recursive_ref_inside_a_list_is_not_generatable() -> None:
    """A recursive $ref wrapped in a list value is found by the sequence walk.

    The list is inlined into this same mapping, so a back-reference in its element
    would compile and reintroduce the exponential bail cascade. The guard descends
    into the list the way it descends into a combinator.
    """
    ref = _DeferredRef()
    ref.schema = Schema({"v": int})
    mapping = Schema({"children": [ref]})
    assert isinstance(mapping._compiled, _MappingValidator)
    assert compile_mapping(mapping._compiled) is None


def test_recursive_ref_schema_validates_deep_data_cheaply() -> None:
    """End to end: a recursive $ref schema fails deep data cleanly, no cascade."""
    schema = from_json_schema(
        {
            "$ref": "#/$defs/node",
            "$defs": {
                "node": {
                    "type": "object",
                    "properties": {"next": {"$ref": "#/$defs/node"}},
                    "additionalProperties": True,
                },
            },
        },
    )
    set_compile_policy(CompilePolicy.ON)
    deep: dict = {}
    current = deep
    for _ in range(2000):
        current["next"] = {}
        current = current["next"]
    with pytest.raises(MultipleInvalid, match="nested too deeply"):
        schema(deep)


@dataclass
class _User:
    name: str
    age: int
    score: float = 0.0
    nickname: str = "anon"


@dataclass
class _Tree:
    value: int
    children: list[_Tree] = field(default_factory=list)


@dataclass
class _Open:
    a: int


@dataclass
class _Empty:
    pass


class _Movie(TypedDict):
    title: str
    year: int


_DC_INPUTS: list[dict[str, object]] = [
    {"name": "ada", "age": 30, "score": 9.5, "nickname": "c"},
    {"name": "ada", "age": 30},
    {"name": "ada"},
    {"name": "ada", "age": "x"},
    {"name": 1, "age": 2},
    {"name": "ada", "age": 2, "extra": 9},
    {},
]


@pytest.mark.parametrize("data", _DC_INPUTS)
def test_dataclass_compiled_matches_interpreted(data: dict[str, object]) -> None:
    """A compiled DataclassSchema constructs and errors exactly like interpreted."""
    interpreted = DataclassSchema(_User)
    compiled = DataclassSchema(_User, compile=True).compile()
    assert _is_compiled(compiled)
    assert _outcome(interpreted, dict(data)) == _outcome(compiled, dict(data))


def test_zero_field_dataclass_with_remove_extra_compiles() -> None:
    """An empty dataclass with REMOVE_EXTRA compiles instead of failing on an empty try.

    With no fields and no out-dict and nothing to copy, the generated try body would
    be empty, a syntax error; a bare ``pass`` keeps the block valid and still drops
    the unknown key.
    """
    compiled = DataclassSchema(_Empty, extra=REMOVE_EXTRA, compile=True).compile()
    assert _is_compiled(compiled)
    assert compiled({"dropped": 1}) == _Empty()


def test_recursive_dataclass_compiles_and_matches() -> None:
    """A self-referential dataclass compiles; nested recursion stays correct."""
    interpreted = DataclassSchema(_Tree)
    compiled = DataclassSchema(_Tree, compile=True).compile()
    assert _is_compiled(compiled)
    data = {"value": 1, "children": [{"value": 2, "children": []}]}
    assert interpreted(dict(data)) == compiled(dict(data))


def test_allow_extra_dataclass_stays_interpreted() -> None:
    """An ALLOW_EXTRA dataclass is not generated (the constructor rejects extras)."""
    compiled = DataclassSchema(_Open, extra=ALLOW_EXTRA, compile=True)
    assert not _is_compiled(compiled)
    assert compiled({"a": 1, "b": 2}) == _Open(a=1)


def test_typeddict_compiles_as_a_plain_mapping() -> None:
    """A TypedDictSchema compiles via the bare-mapping path and stays faithful."""
    interpreted = TypedDictSchema(_Movie)
    compiled = TypedDictSchema(_Movie, compile=True).compile()
    assert _is_compiled(compiled)
    for data in ({"title": "x", "year": 2020}, {"title": 1, "year": 2}, {"title": "x"}):
        assert _outcome(interpreted, dict(data)) == _outcome(compiled, dict(data))


def test_compiled_mapping_branch_in_combinator_survives_reuse() -> None:
    """An armed mapping branch a combinator captured works across repeated calls.

    Under the ON policy the inner ``{"a": int}`` mapping arms a bootstrap, and the
    ``Any`` captures it as a branch. The first call resolves it; a second call comes
    back through the combinator's captured reference, which must delegate to the
    resolved validator rather than re-run the bootstrap.
    """
    set_compile_policy(CompilePolicy.ON)
    try:
        schema = Schema(Any({"a": int}, str))
        assert schema({"a": 1}) == {"a": 1}
        assert schema({"a": 2}) == {"a": 2}
        assert schema("x") == "x"
    finally:
        set_compile_policy(CompilePolicy.OFF)


def test_auto_compiles_a_schema_once_it_is_hot() -> None:
    """Under AUTO a schema stays interpreted until the threshold, then compiles."""
    set_compile_policy(CompilePolicy.AUTO)
    try:
        schema = Schema({"a": int})
        for index in range(_AUTO_COMPILE_THRESHOLD - 1):
            assert schema({"a": index}) == {"a": index}
        assert not _is_compiled(schema)
        assert schema({"a": 0}) == {"a": 0}  # crosses the threshold
        assert _is_compiled(schema)
        assert schema({"a": 7}) == {"a": 7}  # now via the compiled validator
    finally:
        set_compile_policy(CompilePolicy.OFF)


def test_auto_leaves_a_one_shot_schema_interpreted() -> None:
    """A schema validated once under AUTO never reaches the threshold."""
    set_compile_policy(CompilePolicy.AUTO)
    try:
        schema = Schema({"a": int})
        assert schema({"a": 1}) == {"a": 1}
        assert not _is_compiled(schema)
    finally:
        set_compile_policy(CompilePolicy.OFF)


def test_policy_turned_off_after_arming_stays_interpreted() -> None:
    """A schema armed under ON that sees OFF by its first call stays interpreted."""
    set_compile_policy(CompilePolicy.ON)
    try:
        schema = Schema({"a": int})  # armed
        set_compile_policy(CompilePolicy.OFF)  # before the first call
        assert schema({"a": 1}) == {"a": 1}
        assert not _is_compiled(schema)
    finally:
        set_compile_policy(CompilePolicy.OFF)


@pytest.mark.parametrize(
    ("schema", "inputs"),
    [
        ([str], [["a", "b"], ["a", 1], [], "no", ("a",)]),
        (
            [All(Coerce(int), Range(min=0))],
            [["1", "2"], [-1], [], "no", [1.5], ["x"]],
        ),
        ([Any(int, str)], [[1, "a"], [1.5], []]),
    ],
)
def test_compiled_sequence_matches_interpreted(
    schema: list[object], inputs: list[object]
) -> None:
    """A compiled top-level list schema returns and raises what the engine does."""
    interpreted = Schema(list(schema), compile=False)
    compiled = Schema(list(schema), compile=True)
    for data in inputs:
        assert _outcome(interpreted, data) == _outcome(compiled, data)
    assert _is_compiled(compiled)


def test_top_level_sequence_compiles_to_a_loop() -> None:
    """A single-element list schema generates a loop instead of a per-item call chain."""
    schema = Schema([All(Coerce(int), Range(min=0))], compile=True).compile()
    assert _is_compiled(schema)
    assert schema(["1", "2", "3"]) == [1, 2, 3]


def test_multi_element_list_stays_interpreted() -> None:
    """A multi-element list (an each-item union) is left to the engine."""
    schema = Schema([str, int], compile=True).compile()
    assert not _is_compiled(schema)
    assert schema(["a", 1]) == ["a", 1]


def test_non_inlinable_element_list_stays_interpreted() -> None:
    """A list whose element does not inline stays interpreted."""
    schema = Schema([In(["a", "b"], fold_case=True)], compile=True).compile()
    assert not _is_compiled(schema)
    assert schema(["a"]) == ["a"]


def test_tuple_sequence_schema_stays_interpreted() -> None:
    """A tuple sequence schema is not a list, so the generator leaves it alone."""
    schema = Schema((str,), compile=True).compile()
    assert not _is_compiled(schema)
    assert schema(("a", "b")) == ("a", "b")
