"""Memory-shape guards: no reference cycles on the error paths, no accumulation.

Two kinds of garbage matter. Uncollectable garbage is a leak; the cyclic
collector reclaims everything probatio builds, and the tests that call
``gc.collect()`` before counting pin that: a recursive ``Self`` schema (which
forms a reference cycle, Schema -> closure -> root Schema) stays garbage
collectable, and repeated validation does not accumulate objects.

Floating garbage is subtler. A cycle is reclaimed eventually, but the collector
triggers on container counts, not bytes, so a ten-object cycle can pin a large
input payload for a long time. The engine therefore must not form a cycle per
validation (see the note on ``Invalid``), and the grids below check that with the
collector switched off: they count what only the collector could free. A compiled
schema, or one the AUTO policy armed, is itself cyclic and needs the collector to
go away; that is per schema, not per validation, and matches voluptuous. The
code-generation cache in ``_codegen.py`` is bounded, so it is not growth either.
"""

from __future__ import annotations

import contextlib
import dataclasses
import gc
import weakref
from typing import TYPE_CHECKING, Any

import pytest

from probatio import (
    All,
    Coerce,
    DataclassSchema,
    ExactSequence,
    Exclusive,
    In,
    Invalid,
    Length,
    Maybe,
    Optional,
    Remove,
    Required,
    Schema,
    Secret,
    Self,
    SomeOf,
)
from probatio import (
    Any as AnyOf,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# A handful of objects may settle between two snapshots (interned ints, gc
# bookkeeping), so the guard is a small absolute bound rather than exact
# equality. It is tiny next to the iteration count, so genuine per-call
# accumulation (which would grow by thousands) still fails loudly.
_ALLOWED_OBJECT_DRIFT = 100
_ITERATIONS = 2000


def _recursive_schema() -> Schema:
    """A schema that references itself (a cycle per schema, not per validation)."""
    return Schema({Required("value"): int, Optional("next"): Self})


def test_recursive_schema_is_garbage_collectable() -> None:
    """A recursive Self schema is reclaimed once dropped (no uncollectable cycle)."""
    schema = _recursive_schema()
    schema({"value": 1, "next": {"value": 2}})  # exercise the recursion
    ref = weakref.ref(schema)
    del schema
    gc.collect()
    assert ref() is None


def test_repeated_validation_does_not_accumulate_objects() -> None:
    """Validating many times retains nothing: the live object count stays flat."""
    schema = _recursive_schema()
    payload = {"value": 1, "next": {"value": 2, "next": {"value": 3}}}
    schema(payload)  # warm any one-time allocations before the baseline

    gc.collect()
    before = len(gc.get_objects())
    for _ in range(_ITERATIONS):
        schema(payload)
    gc.collect()
    after = len(gc.get_objects())

    assert after - before < _ALLOWED_OBJECT_DRIFT


def test_repeated_failures_do_not_accumulate_objects() -> None:
    """Failing validation many times retains no errors, paths, or exceptions."""
    schema = _recursive_schema()
    bad = {"value": 1, "next": {"value": "not an int"}}
    with contextlib.suppress(Invalid):
        schema(bad)  # warm one-time allocations on the failure path

    gc.collect()
    before = len(gc.get_objects())
    for _ in range(_ITERATIONS):
        with contextlib.suppress(Invalid):
            schema(bad)
    gc.collect()
    after = len(gc.get_objects())

    assert after - before < _ALLOWED_OBJECT_DRIFT


_CYCLE_ITERATIONS = 200


def _cyclic_objects_left(action: Callable[[], object]) -> int:
    """Run ``action`` repeatedly with the collector off; count what only it can free.

    Anything this returns above zero is a reference cycle that refcounting could
    not break, so whatever the frames in it hold (the input data, the partial
    output) stays alive until the collector happens to run.
    """
    action()  # warm one-time work (lazy compile, message catalogs) off the count
    gc.collect()
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(_CYCLE_ITERATIONS):
            action()
        return gc.collect()
    finally:
        if was_enabled:
            gc.enable()


def _assert_no_cycles(action: Callable[[], object]) -> None:
    """Fail with the leftover count and where to look when ``action`` cycles."""
    left = _cyclic_objects_left(action)
    assert left == 0, (
        f"{left} cyclic objects left after {_CYCLE_ITERATIONS} runs. A frame that "
        "caught an Invalid is probably still holding it (in a local or a list) when "
        "it returns or raises; see the reference cycle note on Invalid in error.py."
    )


def _slug(value: Any) -> Any:
    """Accept a lowercase string; reject anything else the way a user callable would."""
    if not isinstance(value, str) or not value.islower():
        message = "not a slug"
        raise ValueError(message)
    return value


@dataclasses.dataclass
class _Point:
    """A dataclass with a typed field for the dataclass-schema case."""

    x: int
    y: int = 0


class _TrackedDict(dict[Any, Any]):
    """A dict that can be weakly referenced."""


class _TrackedList(list[Any]):
    """A list that can be weakly referenced."""


class _TrackedStr(str):  # noqa: SLOT000 - a slotless subclass is weakly referenceable
    """A str that can be weakly referenced."""


_COMPILE_MODES = pytest.mark.parametrize(
    "compiled", [False, True], ids=["interpreted", "compiled"]
)

# Each failure case is ``(schema spec, bad input)``. The input is built by a
# factory so a case that mutates or tracks its input gets a fresh one every run.
_FAILURE_CASES: dict[str, tuple[Any, Callable[[], Any]]] = {
    "top-level type": (int, lambda: "x"),
    "top-level coerce": (Coerce(int), lambda: _TrackedStr("abc")),
    "not a mapping": ({"a": int}, lambda: 5),
    "mapping type value": ({"a": int}, lambda: {"a": "x"}),
    "mapping validator value": (
        {"a": All(str, Length(min=3))},
        lambda: _TrackedDict({"a": "x"}),
    ),
    "mapping coerce value": ({"a": Coerce(int)}, lambda: {"a": "abc"}),
    "missing required key": ({Required("a"): int}, dict),
    "extra key": ({"a": int}, lambda: {"b": 1}),
    "several errors at once": (
        {Required("a"): int, "b": Coerce(int), "c": All(str, Length(min=3))},
        lambda: {"b": "x", "c": "y", "zzz": 1},
    ),
    "nested mapping": (
        {"a": {"b": {"c": All(str, Length(min=3))}}},
        lambda: {"a": {"b": {"c": "x"}}},
    ),
    "list item type": ([int], lambda: [1, "x", 3]),
    "list item validator": (
        [All(str, Length(min=3))],
        lambda: _TrackedList(["abcd", "x"]),
    ),
    "list of mappings": ([{"a": int}], lambda: [{"a": 1}, {"a": "x"}]),
    "list, no element matches": ([Coerce(int), Coerce(float)], lambda: [1, "x"]),
    "all": (All(str, Length(min=3)), lambda: _TrackedStr("x")),
    "any, every validator branch fails": (
        AnyOf(Coerce(int), Coerce(float)),
        lambda: _TrackedStr("z"),
    ),
    "any, every type branch fails": ({"a": AnyOf(int, None)}, lambda: {"a": "x"}),
    "in": ({"a": In(["x", "y"])}, lambda: {"a": "z"}),
    "some of": (
        SomeOf([Coerce(int), Coerce(float)], min_valid=1),
        lambda: _TrackedStr("z"),
    ),
    "exact sequence": (ExactSequence([Coerce(int), str]), lambda: ["x", "y"]),
    "maybe": (Maybe(All(str, Length(min=3))), lambda: _TrackedStr("x")),
    "key validator rejects the key": ({str: int}, lambda: {1: 1}),
    "key falls through every candidate": ({_slug: int}, lambda: {"Up": 1}),
    "remove key whose value fails": ({Remove("a"): Coerce(int)}, lambda: {"a": "x"}),
    "default that fails its own schema": (
        {Optional("a", default="x"): Coerce(int)},
        dict,
    ),
    "exclusive group": (
        {Exclusive("a", "group"): int, Exclusive("b", "group"): int},
        lambda: {"a": 1, "b": 2},
    ),
    "user callable raising ValueError": ({"a": _slug}, lambda: {"a": "Up"}),
    "any of mappings, none match": (
        AnyOf({"a": int}, {"b": int}),
        lambda: {"a": "x"},
    ),
    "list of any, none match": ([AnyOf(Coerce(int), Coerce(float))], lambda: ["x"]),
    "secret key": (
        {Secret("password"): All(str, Length(min=5))},
        lambda: {"password": "x"},
    ),
    "self recursive in a list": (
        {"a": [Self]},
        lambda: {"a": [{"a": ["x"]}]},
    ),
    "self recursive": (
        {Required("value"): int, Optional("next"): Self},
        lambda: {"value": 1, "next": {"value": "x"}},
    ),
}

# The success cases reject a branch on the way to accepting the value.
_SUCCESS_CASES: dict[str, tuple[Any, Callable[[], Any]]] = {
    "any, second branch accepts": (
        AnyOf(Coerce(int), str),
        lambda: _TrackedStr("abc"),
    ),
    "any, mapping branch rejected": (
        AnyOf({"a": int}, str),
        lambda: _TrackedStr("abc"),
    ),
    "any in a mapping value": (
        {"v": AnyOf(Coerce(int), str)},
        lambda: _TrackedDict({"v": "abc"}),
    ),
    "list, items fall to the second element": (
        [int, str],
        lambda: _TrackedList(["a", "b", 1]),
    ),
    "list, coerce then type": ([Coerce(int), str], lambda: _TrackedList(["a"])),
    "key falls through to the catch-all": (
        {_slug: int, str: str},
        lambda: _TrackedDict({"Up": "x"}),
    ),
    "some of": (
        SomeOf([Coerce(int), str], min_valid=1),
        lambda: _TrackedStr("abc"),
    ),
    "maybe": (Maybe(All(str, Length(min=1))), lambda: _TrackedStr("abc")),
    "remove key, catch-all takes the rest": (
        {Remove(_slug): int, str: str},
        lambda: _TrackedDict({"a": "x"}),
    ),
    "any of mappings, second matches": (
        AnyOf({"a": int}, {"b": int}),
        lambda: _TrackedDict({"b": 1}),
    ),
}


def _run_ignoring_invalid(
    schema: Callable[[Any], Any], make_data: Callable[[], Any]
) -> None:
    """Validate a fresh input, dropping the error the way a caller handling it would."""
    with contextlib.suppress(Invalid):
        schema(make_data())


@_COMPILE_MODES
@pytest.mark.parametrize(
    ("spec", "make_data"), _FAILURE_CASES.values(), ids=_FAILURE_CASES
)
def test_failed_validation_forms_no_reference_cycle(
    spec: Any, make_data: Callable[[], Any], *, compiled: bool
) -> None:
    """A caught failure leaves nothing for the cyclic collector to free."""
    schema = Schema(spec, compile=compiled)

    _assert_no_cycles(lambda: _run_ignoring_invalid(schema, make_data))


def _declines_with_invalid() -> Any:
    """A default factory that fails validation itself."""
    message = "no default today"
    raise Invalid(message)


def _explodes(_value: Any) -> Any:
    """A user callable with a bug: it raises something that is not ``Invalid``."""
    message = "boom"
    raise RuntimeError(message)


# Each case collects an error first and is then cut short by an exception that is
# not part of the normal "collect, then raise" ending.
_EARLY_EXIT_CASES: dict[str, tuple[Any, Callable[[], Any]]] = {
    "mapping, default factory raises": (
        {"a": Coerce(int), Optional("b", default=_declines_with_invalid): int},
        lambda: _TrackedDict({"a": "bad"}),
    ),
    "mapping, later value explodes": (
        {"a": Coerce(int), "b": _explodes},
        lambda: _TrackedDict({"a": "bad", "b": 1}),
    ),
    "list, later item explodes": (
        [Coerce(int), All(str, _explodes)],
        lambda: _TrackedList([1.5j, "x"]),
    ),
    "list item, later candidate explodes": (
        [int, _explodes],
        lambda: _TrackedList(["x"]),
    ),
    "exact sequence, later position explodes": (
        ExactSequence([Coerce(int), _explodes]),
        lambda: _TrackedList(["bad", 1]),
    ),
    "some of, later branch explodes": (
        SomeOf([Coerce(int), _explodes], min_valid=1),
        lambda: _TrackedStr("abc"),
    ),
    "any, later branch explodes": (
        AnyOf(Coerce(int), _explodes),
        lambda: _TrackedStr("abc"),
    ),
}


def _run_ignoring_everything(
    schema: Callable[[Any], Any], make_data: Callable[[], Any]
) -> None:
    """Validate a fresh input, dropping whatever it raises."""
    with contextlib.suppress(Invalid, RuntimeError):
        schema(make_data())


@_COMPILE_MODES
@pytest.mark.parametrize(
    ("spec", "make_data"), _EARLY_EXIT_CASES.values(), ids=_EARLY_EXIT_CASES
)
def test_validation_cut_short_forms_no_reference_cycle(
    spec: Any, make_data: Callable[[], Any], *, compiled: bool
) -> None:
    """An exception that leaves mid-validation does not strand the errors so far."""
    schema = Schema(spec, compile=compiled)

    _assert_no_cycles(lambda: _run_ignoring_everything(schema, make_data))


@_COMPILE_MODES
def test_failed_dataclass_validation_forms_no_reference_cycle(
    *, compiled: bool
) -> None:
    """A dataclass schema failure leaves nothing for the cyclic collector to free."""
    schema = DataclassSchema(_Point, compile=compiled)

    _assert_no_cycles(lambda: _run_ignoring_invalid(schema, lambda: {"x": "no"}))


@_COMPILE_MODES
@pytest.mark.parametrize(
    ("spec", "make_data"), _SUCCESS_CASES.values(), ids=_SUCCESS_CASES
)
def test_success_after_rejected_branch_forms_no_reference_cycle(
    spec: Any, make_data: Callable[[], Any], *, compiled: bool
) -> None:
    """A success that rejected a branch on the way leaves nothing for the collector."""
    schema = Schema(spec, compile=compiled)

    _assert_no_cycles(lambda: schema(make_data()))


@_COMPILE_MODES
@pytest.mark.parametrize(
    "case",
    [
        "top-level coerce",
        "mapping validator value",
        "list item validator",
        "all",
        "any, every validator branch fails",
        "some of",
        "maybe",
    ],
)
def test_failed_validation_releases_the_payload_without_the_collector(
    case: str, *, compiled: bool
) -> None:
    """The input is freed by refcounting alone once the caught error is dropped."""
    spec, make_data = _FAILURE_CASES[case]
    schema = Schema(spec, compile=compiled)
    _run_ignoring_invalid(schema, make_data)  # warm up lazy work

    gc.collect()
    gc.disable()
    try:
        payload = make_data()
        payload_ref = weakref.ref(payload)
        with contextlib.suppress(Invalid):
            schema(payload)
        del payload

        assert payload_ref() is None
    finally:
        gc.enable()


@_COMPILE_MODES
@pytest.mark.parametrize(
    "case",
    [
        "any, second branch accepts",
        "list, items fall to the second element",
        "key falls through to the catch-all",
        "some of",
    ],
)
def test_success_after_rejected_branch_releases_the_payload_without_the_collector(
    case: str, *, compiled: bool
) -> None:
    """The input is freed by refcounting alone after a success that rejected a branch."""
    spec, make_data = _SUCCESS_CASES[case]
    schema = Schema(spec, compile=compiled)
    schema(make_data())  # warm up lazy work

    gc.collect()
    gc.disable()
    try:
        payload = make_data()
        payload_ref = weakref.ref(payload)
        schema(payload)
        del payload

        assert payload_ref() is None
    finally:
        gc.enable()
