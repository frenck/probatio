"""Tests for the compiled-variant code generator (the ``compile`` flag).

A compiled schema must be behaviorally identical to its interpreted twin; the
generator's whole safety argument is that any failure bails to the interpreted
validator. These tests pin both the parity and which shapes do (and do not)
generate.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, IntEnum, StrEnum
from math import inf, nan
from types import MappingProxyType
from typing import Annotated, TypedDict

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from probatio import (
    ALLOW_EXTRA,
    REMOVE_EXTRA,
    UNDEFINED,
    All,
    Any,
    Byte,
    Coerce,
    CompilePolicy,
    DataclassSchema,
    Exclusive,
    Forbidden,
    In,
    Invalid,
    Key,
    Latitude,
    Length,
    Longitude,
    Match,
    Maybe,
    MultipleInvalid,
    Negative,
    NonNegative,
    Optional,
    Positive,
    Range,
    Remove,
    Required,
    Schema,
    Self,
    SmallFloat,
    TypedDictSchema,
    from_json_schema,
    set_compile_policy,
)
from probatio._codegen import _emitters, compile_mapping
from probatio._engine import _MappingValidator
from probatio.codecs.jsonschema import _DeferredRef
from probatio.schema import _AUTO_COMPILE_THRESHOLD
from tests import strategies


def _is_compiled(schema: Schema) -> bool:
    """Report whether the schema swapped in a generated validator."""
    return getattr(schema._compiled, "__name__", "") == "_validate"


def _key_order(value: object) -> object:
    """Capture the key order of a result, recursively, as something comparable.

    Two dicts holding the same pairs in a different order compare equal, so an
    order-only divergence between the two paths slips straight through ``==``
    (that is how issue #307 survived the differential tests and the compiled CI
    lane). This makes the layout part of what is compared.
    """
    if isinstance(value, dict):
        return tuple((key, _key_order(item)) for key, item in value.items())
    if isinstance(value, list):
        return [_key_order(item) for item in value]
    return None


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
    return ("ok", result, type(result).__name__, _key_order(result))


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
    # Bounds whose repr is not source: ``inf`` and ``nan`` are not names, and an
    # IntEnum member reprs as ``<_Level.LOW: 1>``. They must compile, not crash.
    "range_neg_inf": lambda **k: Schema({"x": Range(min=float("-inf"))}, **k),
    "range_inf": lambda **k: Schema({"x": Range(max=float("inf"))}, **k),
    "range_nan": lambda **k: Schema({"x": Range(min=nan)}, **k),
    "range_int_enum": lambda **k: Schema(
        {"x": Range(min=_Level.LOW, max=_Level.HIGH)}, **k
    ),
    "range_int_enum_coerced": lambda **k: Schema(
        {"x": All(Coerce(int), Range(min=_Level.LOW))}, **k
    ),
    "length_int_enum": lambda **k: Schema(
        {"x": Length(min=_Level.LOW, max=_Level.HIGH)}, **k
    ),
    # A bound whose own comparison raises: the interpreted validator reports it as
    # invalid, so the compiled check must bail there rather than leak the TypeError.
    "range_refusing_bound": lambda **k: Schema({"x": Range(min=_RefusingInt(1))}, **k),
    "length_refusing_bound": lambda **k: Schema(
        {"x": Length(max=_RefusingInt(4))}, **k
    ),
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
    # Length inlining: an integer-bounded len check (both bounds, then each single
    # bound), a no-bounds Length (always passes, so it emits nothing), and a
    # non-integer bound (unusual for a length, left to the closure). Match inlining:
    # an anchored regex, hit and miss and a non-string that bails on the TypeError.
    "length": lambda **k: Schema({"x": All(str, Length(min=2, max=4))}, **k),
    "length_min_only": lambda **k: Schema({"x": All(str, Length(min=2))}, **k),
    "length_max_only": lambda **k: Schema({"x": All(str, Length(max=4))}, **k),
    "length_no_bounds": lambda **k: Schema({"x": All(str, Length())}, **k),
    "length_float_bound": lambda **k: Schema({"x": Length(min=1.5)}, **k),
    "match": lambda **k: Schema({"x": Match(r"^[a-z]+$")}, **k),
}


class _Color(Enum):
    RED = "red"
    BLUE = "blue"


class _Level(IntEnum):
    """An integer enum: its members are int instances, but repr is not source."""

    LOW = 1
    HIGH = 4


class _RefusingInt(int):
    """An int whose comparisons raise, so a check against it can only fail."""

    def __lt__(self, other: int) -> bool:
        """Refuse every ordering comparison."""
        msg = "no ordering"
        raise TypeError(msg)

    __le__ = __gt__ = __ge__ = __lt__


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
    # Length/Match: an in-range lowercase hit, an over-length value that still
    # matches the regex, a zero-length string, and (reusing the cases above) a
    # too-short "a", an uppercase miss "A", and a non-string 5 that bails on
    # len/match.
    {"x": "abc"},
    {"x": "abcdef"},
    {"x": ""},
    # Inputs whose key order is not the schema's declaration order: the result must
    # be laid out the way the input is, not the way the schema is written (issue
    # #307). Reversed against "types", against "defaults" (leaving the defaulted key
    # to be appended), an extra key ahead of a known one, and a reversed nested value.
    {"f": 1.5, "ok": True, "p": 1, "n": "x"},
    {"p": 1, "n": "x"},
    {"b": 2, "a": 1},
    {"srv": {"port": 2, "host": "h"}},
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


@pytest.mark.parametrize(
    "mapping",
    [
        {In(["a", "b"]): str},
        {"x": int, In(["a", "b"]): str},
        {Match(r"^[a-z]+$"): int},
    ],
    ids=["membership", "with_property", "match"],
)
def test_key_validator_mapping_stays_interpreted(mapping: dict) -> None:
    """A validator key (what propertyNames decodes to) is not generated, and agrees.

    The generator inlines a literal or type key; an arbitrary key validator has to
    run per key, so it bails to the engine. Compilation declining is the safe
    outcome, but only if the two paths still agree, so both are asserted here.
    """
    compiled = Schema(mapping, compile=True).compile()
    assert not _is_compiled(compiled)

    interpreted = Schema(mapping, compile=False)
    for data in ({"a": "s"}, {"x": 1}, {"zz": "s"}, {"a": 1}, {1: "s"}, {}):
        assert _outcome(interpreted, dict(data)) == _outcome(compiled, dict(data))


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


@dataclass
class _Guarded:
    """A dataclass whose __post_init__ rejects a value the field type accepts."""

    weight: float

    def __post_init__(self) -> None:
        if self.weight < 0:
            message = "weight must not be negative"
            raise ValueError(message)


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


def test_compiled_dataclass_post_init_error_matches_interpreted() -> None:
    """A __post_init__ ValueError normalizes identically compiled and interpreted.

    Construction runs outside the field try, so a leaked ValueError would escape the
    compiled path as itself; it must defer to the interpreted constructor, which
    reports a ValueInvalid. Regression test for the compiled path leaking a raw
    __post_init__ error (issue #176); runs in the default gate, not only the
    ``--compiled`` lane, so CI guards it.
    """
    interpreted = DataclassSchema(_Guarded)
    compiled = DataclassSchema(_Guarded, compile=True).compile()
    assert _is_compiled(compiled)
    for data in ({"weight": -1.0}, {"weight": 1.0}):
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


def test_auto_keeps_the_key_order_stable_across_the_threshold() -> None:
    """Going hot under AUTO does not relayout the result dict (issue #307).

    The engine lays a result out the way the input is laid out and appends the
    defaulted keys; the generated code writes fields in declaration order. When the
    two disagreed, a schema silently started returning a differently ordered dict on
    its 50th call, which anything serializing a validated config can see.
    """
    set_compile_policy(CompilePolicy.AUTO)
    try:
        schema = Schema({Optional("step", default=1): int, Optional("mode"): str})
        cold = list(schema({"mode": "box"}))
        for _ in range(_AUTO_COMPILE_THRESHOLD):
            hot = list(schema({"mode": "box"}))

        assert _is_compiled(schema)
        assert cold == ["mode", "step"]
        assert hot == cold
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
        ([Range(min=-inf)], [[1]]),
        ([Range(max=inf)], [[1]]),
        ([Range(min=nan)], [[1]]),
        ([Range(min=_Level.LOW, max=_Level.HIGH)], [[1, 4], [0], [5]]),
        ([Length(min=_Level.LOW, max=_Level.HIGH)], [["abc"], [""], ["abcde"]]),
        ([Range(max=_RefusingInt(4))], [[1]]),
        ([Length(min=_RefusingInt(1))], [["abc"]]),
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


def test_a_call_arriving_during_generation_does_not_recurse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second caller crossing the threshold mid-generation must not re-enter.

    Generation is real work, so another caller can arrive while it runs and find
    ``_compiled`` still holding the counter. Delegating to it there lands back on
    the counter, which increments and delegates again, until the stack gives out.
    Reported against Home Assistant blueprint validation, where config is
    validated from an executor thread.
    """
    set_compile_policy(CompilePolicy.AUTO)
    schema = Schema({"a": int})
    data = {"a": 1}

    original = Schema._compile_from
    arrived: list[bool] = []

    def reentrant(self: Schema, interpreted: object) -> object:
        # Stands in for the caller that arrives while generation is running.
        if not arrived:
            arrived.append(True)
            schema(data)
        return original(self, interpreted)

    monkeypatch.setattr(Schema, "_compile_from", reentrant)

    for _ in range(_AUTO_COMPILE_THRESHOLD + 5):
        assert schema(data) == data

    assert arrived, "the re-entrant call never happened, so nothing was proven"


# One entry per validator codegen can inline: the class that owns the emitter, the
# class to instantiate (a built-in subclass inherits the emitter), a way to build
# it, a value its base ``__call__`` accepts (otherwise the generated code bails to
# the interpreted engine and a test passes for the wrong reason), and an int the
# base accepts too, for the ``All(Coerce(int), ...)`` composition (``None`` where
# the validator does not take an int).
_INLINABLE = {
    "Coerce": (Coerce, Coerce, lambda cls: cls(int), "5", 5),
    "Range": (Range, Range, lambda cls: cls(min=0, max=10), 3, 3),
    "Positive": (Range, Positive, lambda cls: cls(), 3, 3),
    "NonNegative": (Range, NonNegative, lambda cls: cls(), 3, 3),
    "Negative": (Range, Negative, lambda cls: cls(), -3, -3),
    "Byte": (Range, Byte, lambda cls: cls(), 3, 3),
    "SmallFloat": (Range, SmallFloat, lambda cls: cls(), 0.5, None),
    "Latitude": (Range, Latitude, lambda cls: cls(), 45, 45),
    "Longitude": (Range, Longitude, lambda cls: cls(), 45, 45),
    "In": (In, In, lambda cls: cls([1, 2, 3]), 1, 1),
    "Any": (Any, Any, lambda cls: cls(1, 2), 1, 1),
    "All": (All, All, lambda cls: cls(Range(min=0, max=10)), 3, 3),
    "Length": (Length, Length, lambda cls: cls(min=1, max=3), "ab", None),
    "Match": (Match, Match, lambda cls: cls("^a"), "ab", None),
    "Maybe": (Maybe, Maybe, lambda cls: cls(int), 3, 3),
}

_OVERRIDDEN = object()


class _OverridesCall:
    """A mixin that supplies ``__call__``, as a framework base class might."""

    def __call__(self, _value: object) -> object:
        """Ignore the value and return a sentinel the base would never produce."""
        return _OVERRIDDEN


def _override_directly(cls: type) -> type:
    """Subclass ``cls`` with its own ``__call__``."""

    class Overridden(cls):  # type: ignore[misc]
        """A user extension that replaces the validation."""

        def __call__(self, _value: object) -> object:
            """Ignore the value and return a sentinel the base would never produce."""
            return _OVERRIDDEN

    return Overridden


def _override_through_mixin(cls: type) -> type:
    """Subclass ``cls`` with a ``__call__`` that arrives through a mixin."""

    class Mixed(_OverridesCall, cls):  # type: ignore[misc]
        """A user extension whose ``__call__`` is not in its own body."""

    return Mixed


_OVERRIDES = {
    "directly": _override_directly,
    "mixin": _override_through_mixin,
}


def test_every_inlinable_validator_is_covered_by_the_override_table() -> None:
    """A new codegen emitter fails here until the override table covers its class."""
    covered = {base for base, *_ in _INLINABLE.values()}

    assert covered == set(_emitters())


@pytest.mark.parametrize("how", sorted(_OVERRIDES))
@pytest.mark.parametrize("name", sorted(_INLINABLE))
def test_compiled_schema_runs_a_call_override_in_every_position(
    name: str, how: str
) -> None:
    """A subclass with its own ``__call__`` is called, not inlined as its base."""
    _, cls, build, value, int_value = _INLINABLE[name]
    validator = build(_OVERRIDES[how](cls))
    schemas = {
        "mapping value": (Schema({"k": validator}, compile=True), value, _OVERRIDDEN),
        "list element": (
            Schema({"k": [validator]}, compile=True),
            [value],
            [_OVERRIDDEN],
        ),
        "all member": (
            Schema({"k": All(validator)}, compile=True),
            value,
            _OVERRIDDEN,
        ),
    }
    if int_value is not None:
        schemas["all member after Coerce"] = (
            Schema({"k": All(Coerce(int), validator)}, compile=True),
            int_value,
            _OVERRIDDEN,
        )

    for position, (schema, given_value, expected) in schemas.items():
        assert schema({"k": given_value}) == {"k": expected}, position


def test_compiled_override_rejects_where_the_base_accepts() -> None:
    """The override's own rejection reaches the caller when compiled (the report)."""

    class EvenRange(Range):
        """A range that only takes even numbers."""

        def __call__(self, value: int) -> int:
            """Run the range check, then reject odd numbers."""
            value = super().__call__(value)
            if value % 2:
                message = "odd"
                raise Invalid(message)
            return value

    compiled = Schema({"x": EvenRange(min=0, max=10)}, compile=True)
    interpreted = Schema({"x": EvenRange(min=0, max=10)}, compile=False)

    assert _outcome(compiled, {"x": 3}) == _outcome(interpreted, {"x": 3})
    assert _outcome(compiled, {"x": 3})[0] == "err"
    assert _outcome(compiled, {"x": 4}) == ("ok", {"x": 4}, "dict", (("x", None),))


def test_auto_does_not_flip_the_outcome_of_a_call_override() -> None:
    """One schema holding an override answers the same before and after going hot."""
    set_compile_policy(CompilePolicy.AUTO)
    schema = Schema({"x": _override_directly(Range)(min=0, max=10)})

    outcomes = {
        repr(_outcome(schema, {"x": 3})) for _ in range(_AUTO_COMPILE_THRESHOLD + 10)
    }

    assert _is_compiled(schema)
    assert outcomes == {repr(("ok", {"x": _OVERRIDDEN}, "dict", (("x", None),)))}


class _PlainRange(Range):
    """A user subclass that leaves ``__call__`` alone."""


@pytest.mark.parametrize("validator", [Positive(), _PlainRange(min=0, max=10)])
def test_a_subclass_without_a_call_override_is_still_inlined(
    validator: Range,
) -> None:
    """Inheriting ``__call__`` keeps the base's inline code, with no closure call."""
    schema = Schema({"k": validator}, compile=False)
    generated = compile_mapping(schema._compiled)

    assert generated is not None
    # A value that is not inlined is bound as a closure named ``_c<index>``.
    assert "_c0" not in generated.__globals__
    assert _outcome(Schema({"k": validator}, compile=True), {"k": 3}) == _outcome(
        schema, {"k": 3}
    )
    assert _outcome(Schema({"k": validator}, compile=True), {"k": -3})[0] == "err"


class _Unhashable(type):
    """A metaclass whose classes cannot be dictionary keys."""

    __hash__ = None  # type: ignore[assignment]


class _UnhashableCallable(metaclass=_Unhashable):
    """A plain callable validator whose class is unhashable."""

    def __call__(self, value: object) -> object:
        """Accept anything."""
        return value


class _UnhashableRange(Range, metaclass=_Unhashable):
    """A Range subclass whose class is unhashable but whose ``__call__`` is Range's."""


def test_a_validator_with_an_unhashable_class_still_compiles() -> None:
    """A class that cannot be a dictionary key does not break the emitter lookup."""
    callable_schema = Schema({"k": _UnhashableCallable()}, compile=True)
    range_schema = Schema({"k": _UnhashableRange(min=0, max=10)}, compile=True)

    assert callable_schema({"k": 3}) == {"k": 3}
    assert range_schema({"k": 3}) == {"k": 3}
    assert _is_compiled(callable_schema)
    assert _is_compiled(range_schema)
    assert _outcome(range_schema, {"k": 30})[0] == "err"


def test_a_subclass_with_a_call_override_is_bound_as_a_closure() -> None:
    """The counterpart of the inlined case: an override is called through ``_c0``."""
    schema = Schema({"k": _override_directly(Range)(min=0, max=10)}, compile=False)
    generated = compile_mapping(schema._compiled)

    assert generated is not None
    assert "_c0" in generated.__globals__


# Validators for the compiled-versus-interpreted differential: every inlinable
# base class as the override table builds it, plus the arguments that send an
# emitter down a different branch.
_DIFFERENTIAL = {
    **{
        name: build(cls)
        for name, (base, cls, build, _, _) in _INLINABLE.items()
        if base is cls
    },
    "Coerce to float": Coerce(float),
    "Range with exclusive bounds": Range(
        min=0, max=10, min_included=False, max_included=False
    ),
    "Range with one bound": Range(min=0),
    "In of strings": In(["a", "b"]),
    "Any of types": Any(int, str),
    "Any of a type and None": Any(int, None),
    "Maybe": Maybe(Coerce(int)),
    "All chain": All(Coerce(int), Range(min=1, max=65535)),
    "Length with one bound": Length(min=1),
}


@given(data=st.one_of(st.just({}), strategies.data().map(lambda value: {"k": value})))
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@pytest.mark.parametrize("name", sorted(_DIFFERENTIAL))
def test_compiled_matches_interpreted_for_every_inlinable_validator(
    name: str, data: object
) -> None:
    """Each inlinable validator, in a mapping, behaves the same compiled or not."""
    validator = _DIFFERENTIAL[name]
    compiled = Schema({"k": validator}, compile=True)
    interpreted = Schema({"k": validator}, compile=False)

    # Compared by repr: a coerced ``nan`` is a fresh object on each side, and
    # ``nan != nan`` would report a difference that is not one.
    assert repr(_outcome(compiled, data)) == repr(_outcome(interpreted, data))


def _nested(depth: int, leaf: object) -> dict[str, object]:
    """A mapping nested ``depth`` levels deep, with ``leaf`` at the bottom."""
    spec: dict[str, object] = {"leaf": leaf}
    for _ in range(depth):
        spec = {"child": spec}
    return spec


def _nested_data(depth: int, value: object) -> dict[str, object]:
    """Input matching ``_nested(depth, ...)``, with ``value`` at the bottom."""
    data: dict[str, object] = {"leaf": value}
    for _ in range(depth):
        data = {"child": data}
    return data


@pytest.mark.parametrize("depth", [1, 4, 16])
def test_a_deep_failure_runs_the_interpreted_engine_once(depth: int) -> None:
    """A failing leaf is validated twice whatever the depth: compiled, then interpreted."""
    calls: list[object] = []

    def reject(value: object) -> object:
        """Record the call, then fail the way a user callable does."""
        calls.append(value)
        message = "no"
        raise ValueError(message)

    compiled = Schema(_nested(depth, reject), compile=True)
    interpreted = Schema(_nested(depth, reject), compile=False)
    data = _nested_data(depth, 1)

    assert _outcome(compiled, data)[0] == "err"
    assert _is_compiled(compiled)
    calls.clear()

    compiled_outcome = _outcome(compiled, data)
    assert len(calls) == 2

    assert compiled_outcome == _outcome(interpreted, data)


def test_a_nested_bail_that_the_engine_accepts_still_succeeds() -> None:
    """A nested value the generated code defers on is settled by the engine."""
    spec = {"outer": {"n": Coerce(int)}, "name": str}
    compiled = Schema(spec, compile=True)
    interpreted = Schema(spec, compile=False)
    data = {"outer": {"n": 1.9}, "name": "x"}

    assert compiled(data) == {"outer": {"n": 1}, "name": "x"}
    assert _is_compiled(compiled)
    assert _outcome(compiled, data) == _outcome(interpreted, data)


def test_a_nested_value_that_is_not_a_dict_runs_the_engine_once() -> None:
    """A failing nested dict subclass is validated once, by the outermost mapping."""
    calls: list[object] = []

    def reject(value: object) -> object:
        """Record the call, then fail the way a user callable does."""
        calls.append(value)
        message = "no"
        raise ValueError(message)

    class Settings(dict[str, object]):
        """A dict subclass, which the generated code leaves to the engine."""

    spec = {"child": {"leaf": reject}}
    compiled = Schema(spec, compile=True)
    interpreted = Schema(spec, compile=False)
    data = {"child": Settings(leaf=1)}

    assert _outcome(compiled, data)[0] == "err"
    assert _is_compiled(compiled)
    calls.clear()

    compiled_outcome = _outcome(compiled, data)
    assert len(calls) == 1

    assert compiled_outcome == _outcome(interpreted, data)
    assert _outcome(compiled, {"child": None}) == _outcome(interpreted, {"child": None})


def test_a_nested_dict_subclass_keeps_its_type() -> None:
    """A valid nested dict subclass comes back as that subclass."""

    class Settings(dict[str, object]):
        """A dict subclass, which the generated code leaves to the engine."""

    compiled = Schema({"child": {"leaf": int}}, compile=True)

    result = compiled({"child": Settings(leaf=1)})

    assert _is_compiled(compiled)
    assert type(result["child"]) is Settings


class _Sensor(TypedDict):
    """A leaf TypedDict, nested under ``_Station`` in every position."""

    unit: str
    value: float


class _Station(TypedDict):
    """A TypedDict holding ``_Sensor`` directly, optionally, in a list, and in a dict."""

    direct: _Sensor
    maybe: _Sensor | None
    items: list[_Sensor]
    by_name: dict[str, _Sensor]


_SENSOR = {"unit": "W", "value": 1.5}
_STATION = {
    "direct": _SENSOR,
    "maybe": None,
    "items": [_SENSOR, _SENSOR],
    "by_name": {"a": _SENSOR},
}


@pytest.mark.parametrize(
    "data",
    [
        _STATION,
        {**_STATION, "maybe": _SENSOR},
        {**_STATION, "direct": {"unit": 1, "value": 1.5}},
        {**_STATION, "direct": [_SENSOR]},
        {**_STATION, "maybe": {"unit": "W"}},
        {**_STATION, "items": [_SENSOR, {"unit": "W", "value": "x"}]},
        {**_STATION, "items": (_SENSOR,)},
        {**_STATION, "by_name": {"a": {"unit": "W", "value": 1.5, "extra": 1}}},
    ],
)
def test_compiled_typeddict_calls_the_twins_of_its_nested_typeddicts(
    data: dict[str, object],
) -> None:
    """A compiled TypedDict runs its nested TypedDicts through generated twins.

    A direct field, an optional one, and a list of them each bind a twin (``_g``)
    in the generated code; the dict-valued field is a shape the generator does not
    inline, so it binds the interpreted validator (``_c``). The nested schema's own
    engine is untouched, which is what keeps a failure's interpreted rerun out of
    generated code. Results and errors match the interpreted tree.
    """
    interpreted = TypedDictSchema(_Station, compile=False)
    compiled = TypedDictSchema(_Station, compile=True).compile()
    assert _is_compiled(compiled)

    bound = compiled._compiled.__globals__
    assert {"_g0", "_g1", "_g2s", "_c3"} <= set(bound)
    direct = compiled.schema["direct"]
    assert direct.__probatio_twin__() is bound["_g0"]
    assert isinstance(direct._compiled, _MappingValidator)

    assert _outcome(interpreted, data) == _outcome(compiled, data)


def test_nested_typeddict_schema_never_swaps_its_own_engine() -> None:
    """A nested TypedDict schema stays interpreted under ON, and on ``compile()``.

    Its interpreted engine is what a generated parent's bail-out reruns, so it must
    not turn into generated code by policy, by going hot, or by an explicit call.
    """
    set_compile_policy(CompilePolicy.ON)
    schema = TypedDictSchema(_Station)
    for _ in range(3):
        assert schema(_STATION) == _STATION
    assert _is_compiled(schema)

    direct = schema.schema["direct"]
    assert "_interpreted" not in direct.__dict__
    assert isinstance(direct._compiled, _MappingValidator)
    assert direct.compile() is direct
    assert isinstance(direct._compiled, _MappingValidator)
    assert direct(_SENSOR) == _SENSOR


def test_compile_false_keeps_the_nested_typeddict_schemas_interpreted() -> None:
    """``compile=False`` on the outer TypedDict keeps the whole tree interpreted.

    A nested schema never arms on its own, under any policy; only a compiling
    outer schema asks for its twin. So a pinned outer leaves no twin behind.
    """
    set_compile_policy(CompilePolicy.ON)
    schema = TypedDictSchema(_Station, compile=False)
    for _ in range(3):
        assert schema(_STATION) == _STATION
    assert not _is_compiled(schema)
    assert "_twin" not in schema.schema["direct"].__dict__


def test_auto_compiles_a_hot_typeddict_tree() -> None:
    """Under AUTO a TypedDict that goes hot generates its nested twins with it."""
    set_compile_policy(CompilePolicy.AUTO)
    schema = TypedDictSchema(_Station)
    for _ in range(_AUTO_COMPILE_THRESHOLD):
        assert schema(_STATION) == _STATION
    assert _is_compiled(schema)
    assert "_g0" in schema._compiled.__globals__
    assert isinstance(schema.schema["direct"]._compiled, _MappingValidator)


@dataclass
class _Mast:
    """A dataclass holding TypedDicts, directly and as optional list items."""

    sensor: _Sensor
    spares: list[_Sensor | None]


def test_compiled_dataclass_calls_the_twins_of_its_nested_typeddicts() -> None:
    """A compiled dataclass reaches a nested TypedDict through its twin too."""
    interpreted = DataclassSchema(_Mast, compile=False)
    compiled = DataclassSchema(_Mast, compile=True).compile()
    assert _is_compiled(compiled)
    assert {"_g0", "_g1s"} <= set(compiled._compiled.__globals__)

    for data in (
        {"sensor": _SENSOR, "spares": [None, _SENSOR]},
        {"sensor": _SENSOR, "spares": [None, {"unit": "W"}]},
        {"sensor": {"unit": 1, "value": 1.5}, "spares": []},
    ):
        assert _outcome(interpreted, data) == _outcome(compiled, data)


def test_top_level_list_of_nested_typeddicts_calls_the_twin() -> None:
    """A compiled ``Schema([nested TypedDict schema])`` validates items by the twin."""
    element = TypedDictSchema(_Station).schema["direct"]
    interpreted = Schema([element], compile=False)
    compiled = Schema([element], compile=True).compile()
    assert _is_compiled(compiled)
    assert compiled._compiled.__globals__["_g0s"] is element.__probatio_twin__()

    for data in ([_SENSOR, _SENSOR], [_SENSOR, {"unit": "W", "value": "x"}], []):
        assert _outcome(interpreted, data) == _outcome(compiled, data)


def test_maybe_msg_survives_the_twin_bail_out() -> None:
    """A failure under an inlined ``Maybe`` is reported by the interpreted one."""
    element = TypedDictSchema(_Station).schema["direct"]
    interpreted = Schema({"a": Maybe(element, msg="no sensor")}, compile=False)
    compiled = Schema({"a": Maybe(element, msg="no sensor")}, compile=True).compile()
    assert _is_compiled(compiled)
    assert "_g0" in compiled._compiled.__globals__

    for data in ({"a": _SENSOR}, {"a": None}, {"a": {"unit": 1}}):
        assert _outcome(interpreted, data) == _outcome(compiled, data)
    with pytest.raises(MultipleInvalid, match="no sensor"):
        compiled({"a": {"unit": 1}})


class _LoudMaybe(Maybe[object]):
    """A ``Maybe`` subclass whose call replaces the validated value."""

    def __call__(self, value: object) -> object:
        """Validate as ``Maybe`` does, then report that the override ran."""
        return ("loud", super().__call__(value))


def test_maybe_subclass_around_a_nested_typeddict_keeps_its_call() -> None:
    """A ``Maybe`` subclass is called as written, not inlined down to the twin."""
    element = TypedDictSchema(_Station).schema["direct"]
    compiled = Schema({"a": _LoudMaybe(element)}, compile=True).compile()
    assert _is_compiled(compiled)
    assert "_g0" not in compiled._compiled.__globals__
    assert compiled({"a": _SENSOR}) == {"a": ("loud", _SENSOR)}
    assert compiled({"a": None}) == {"a": ("loud", None)}


def test_maybe_around_a_schema_with_no_twin_stays_a_validator_call() -> None:
    """Only a ``Maybe`` whose inner schema offers a twin is inlined."""
    interpreted = Schema({"a": Maybe(int, msg="int or nothing")}, compile=False)
    compiled = Schema({"a": Maybe(int, msg="int or nothing")}, compile=True).compile()
    assert _is_compiled(compiled)
    assert "_c0" in compiled._compiled.__globals__

    for data in ({"a": 1}, {"a": None}, {"a": "x"}):
        assert _outcome(interpreted, data) == _outcome(compiled, data)


class _Aliased(TypedDict):
    """A TypedDict the generator does not handle: its key is an alias."""

    unit: Annotated[str, Key(alias="Unit")]


class _HoldsAliased(TypedDict):
    """A generatable TypedDict holding one that is not."""

    inner: _Aliased


def test_nested_typeddict_the_generator_cannot_handle_stays_a_schema_call() -> None:
    """A nested TypedDict with no twin is called as a schema, and decided once."""
    interpreted = TypedDictSchema(_HoldsAliased, compile=False)
    compiled = TypedDictSchema(_HoldsAliased, compile=True).compile()
    assert _is_compiled(compiled)

    bound = compiled._compiled.__globals__
    assert "_c0" in bound
    assert "_g0" not in bound
    inner = compiled.schema["inner"]
    assert inner.__dict__["_twin"] is None
    assert inner.__probatio_twin__() is None

    for data in ({"inner": {"Unit": "W"}}, {"inner": {"Unit": 1}}):
        assert _outcome(interpreted, data) == _outcome(compiled, data)


class _SelfChild(TypedDict):
    """A nested TypedDict whose field uses ``Self``, resolved by its own schema."""

    name: str
    child: Annotated[object, Any(Self, None)]


class _HoldsSelfChild(TypedDict):
    """A TypedDict holding a ``Self``-using one."""

    node: _SelfChild


def test_self_using_nested_typeddict_has_no_twin() -> None:
    """A ``Self``-using nested TypedDict is called as a schema, which roots ``Self``."""
    interpreted = TypedDictSchema(_HoldsSelfChild, compile=False)
    compiled = TypedDictSchema(_HoldsSelfChild, compile=True).compile()
    assert _is_compiled(compiled)
    assert compiled.schema["node"].__probatio_twin__() is None

    good = {"node": {"name": "a", "child": {"name": "b", "child": None}}}
    bad = {"node": {"name": "a", "child": {"name": 1, "child": None}}}
    for data in (good, bad):
        assert _outcome(interpreted, data) == _outcome(compiled, data)


def test_failing_deep_typeddict_tree_does_not_cost_exponential_time() -> None:
    """A failure at the bottom of 24 distinct nested TypedDicts is rejected fast.

    No cycle is involved: each level is its own TypedDict holding the next as a
    required field, and under the ON policy every level that may compile does. The
    outer bail-out reruns its interpreted engine, which must call the nested
    *schema* (interpreted), not its generated twin. If it re-entered generated
    code, each level would double the work and this rejection would take minutes;
    it has to stay well under a second, and report exactly what the interpreted
    tree reports.
    """
    set_compile_policy(CompilePolicy.ON)
    depth = 24
    # The functional form: each level is a distinct TypedDict made in a loop.
    cls = TypedDict("Level0", {"value": int})  # noqa: UP013
    for index in range(1, depth):
        cls = TypedDict(f"Level{index}", {"name": str, "child": cls})  # noqa: UP013
    data: dict[str, object] = {"value": "bottom"}
    for _ in range(1, depth):
        data = {"name": "n", "child": data}

    interpreted = TypedDictSchema(cls, compile=False)
    compiled = TypedDictSchema(cls)
    start = time.perf_counter()
    outcome = _outcome(compiled, data)
    assert time.perf_counter() - start < 1.0
    assert _is_compiled(compiled)
    assert "_g1" in compiled._compiled.__globals__
    assert outcome[0] == "err"
    assert outcome == _outcome(interpreted, data)
