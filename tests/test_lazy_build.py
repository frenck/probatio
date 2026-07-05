"""Lazy schema building: defer the compile walk to first validation.

Under ``BuildPolicy.LAZY`` a top-level ``Schema`` stores its declaration and
compiles it on first validation instead of at construction, so a schema that is
built but never validated never pays to build. The default is ``EAGER`` (the
voluptuous parity), so these tests opt in per case and restore it after.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

import pytest

from probatio import (
    All,
    Any,
    BuildPolicy,
    Coerce,
    DataclassSchema,
    Optional,
    Range,
    Required,
    Schema,
    Self,
    TypedDictSchema,
    get_build_policy,
    set_build_policy,
)
from probatio.error import MultipleInvalid, SchemaError

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def lazy() -> Iterator[None]:
    """Run a test under the LAZY build policy, restoring EAGER afterwards."""
    set_build_policy(BuildPolicy.LAZY)
    try:
        yield
    finally:
        set_build_policy(BuildPolicy.EAGER)


def test_policy_defaults_to_eager() -> None:
    """The process starts EAGER, so the drop-in construct-time errors hold."""
    assert get_build_policy() is BuildPolicy.EAGER


def test_set_build_policy_rejects_a_non_policy() -> None:
    """A stray value fails loudly rather than silently disabling lazy building."""
    with pytest.raises(TypeError, match="BuildPolicy"):
        set_build_policy("lazy")  # type: ignore[arg-type]


def test_eager_builds_at_construction() -> None:
    """Under the default policy a schema is compiled when it is built."""
    schema = Schema({Required("a"): int})
    assert schema._built is True


@pytest.mark.usefixtures("lazy")
def test_lazy_defers_until_first_validation() -> None:
    """A lazy schema is not built at construction, and builds on first call."""
    schema = Schema({Required("port"): All(Coerce(int), Range(min=1, max=65535))})
    assert schema._built is False
    assert schema({"port": "8080"}) == {"port": 8080}
    assert schema._built is True


@pytest.mark.usefixtures("lazy")
def test_lazy_result_matches_eager() -> None:
    """Deferring the build changes nothing about the validated result."""
    spec = {
        Required("a"): int,
        Optional("b", default="x"): str,
        Optional("c"): [All(Coerce(int), Range(min=0))],
    }
    set_build_policy(BuildPolicy.EAGER)
    eager = Schema(spec)({"a": 1, "c": ["2", "3"]})
    set_build_policy(BuildPolicy.LAZY)
    lazy = Schema(spec)({"a": 1, "c": ["2", "3"]})
    assert lazy == eager == {"a": 1, "b": "x", "c": [2, 3]}


@pytest.mark.usefixtures("lazy")
def test_lazy_still_reports_validation_errors() -> None:
    """A missing required key still fails, just on first validation."""
    schema = Schema({Required("x"): int})
    with pytest.raises(MultipleInvalid):
        schema({})


@pytest.mark.usefixtures("lazy")
def test_lazy_defers_a_malformed_schema_error_to_first_use() -> None:
    """A definition error is not raised at construction, but still raised on use."""
    schema = Schema({Required(Optional("y")): int})  # two presence markers
    assert schema._built is False
    with pytest.raises(SchemaError, match="two presence markers"):
        schema({"y": 1})


@pytest.mark.usefixtures("lazy")
def test_lazy_recursive_self_builds_on_first_call() -> None:
    """A recursive Self schema takes the recursive path on its deferred first call."""
    tree = Schema({Required("v"): int, Optional("kids", default=list): [Self]})
    assert tree({"v": 1, "kids": [{"v": 2, "kids": []}]}) == {
        "v": 1,
        "kids": [{"v": 2, "kids": []}],
    }


@pytest.mark.usefixtures("lazy")
def test_lazy_nested_schema_builds_with_its_parent() -> None:
    """A lazy schema reused as a value builds when its parent is first validated."""
    inner = Schema({Required("n"): int})
    outer = Schema({Required("a"): inner})
    assert inner._built is False
    assert outer({"a": {"n": 5}}) == {"a": {"n": 5}}
    assert inner._built is True


@pytest.mark.usefixtures("lazy")
def test_lazy_combinator_branch_is_built_eagerly() -> None:
    """A combinator compiles its branches at its own construction, even under LAZY."""
    schema = Schema({Required("v"): Any(int, str)})
    assert schema({"v": "x"}) == {"v": "x"}
    with pytest.raises(MultipleInvalid):
        schema({"v": 1.5})


@pytest.mark.usefixtures("lazy")
def test_lazy_dataclass_schema_is_eager() -> None:
    """A DataclassSchema constructs its instance-building engine at build time."""

    @dataclass
    class Point:
        x: int
        y: int

    schema = DataclassSchema(Point)
    assert schema._built is True
    assert schema({"x": 1, "y": 2}) == Point(1, 2)


@pytest.mark.usefixtures("lazy")
def test_lazy_typeddict_schema_validates() -> None:
    """A TypedDictSchema validates the same under LAZY (its inner is forced eager)."""

    class Movie(TypedDict):
        title: str
        year: int

    assert TypedDictSchema(Movie)({"title": "x", "year": 2020}) == {
        "title": "x",
        "year": 2020,
    }


@pytest.mark.usefixtures("lazy")
def test_lazy_compile_forces_the_build() -> None:
    """Eagerly compiling a lazy schema builds it first, then generates."""
    schema = Schema({Required("a"): int}).compile()
    assert schema._built is True
    assert schema({"a": 1}) == {"a": 1}


@pytest.mark.usefixtures("lazy")
def test_lazy_introspection_does_not_force_a_build() -> None:
    """Reading the declaration, extending, and rendering stay lazy."""
    schema = Schema({Required("a"): int})
    assert schema.schema == {Required("a"): int}
    assert str(schema).startswith("{")
    extended = schema.extend({Optional("b"): str})
    assert schema._built is False
    assert extended._built is False
    assert extended({"a": 1, "b": "x"}) == {"a": 1, "b": "x"}


@pytest.mark.usefixtures("lazy")
def test_ensure_built_is_idempotent() -> None:
    """Building twice is a no-op the second time (the built steady state is lock-free)."""
    schema = Schema({Required("a"): int})
    schema({"a": 1})
    engine = schema._compiled
    schema({"a": 2})
    assert schema._compiled is engine


@pytest.mark.usefixtures("lazy")
def test_concurrent_first_validation_of_a_recursive_combinator_self_is_safe() -> None:
    """Racing the first validation of a lazy recursive combinator-Self schema is safe.

    ``__call__`` dispatches on ``_uses_self``, which a deferred build sets. If the
    build were not serialized before that dispatch, a thread could read a stale
    ``_uses_self`` and skip the active-root setup a combinator-deferred ``Self``
    needs, raising instead of validating. Building in ``__call__`` closes that.
    """
    data = {"next": {"next": None}}
    errors: list[Exception] = []
    for _ in range(25):  # fresh instances widen the one-time first-call window
        schema = Schema({Optional("next"): Any(Self, None)})
        barrier = threading.Barrier(8)

        def run(schema: Schema = schema, barrier: threading.Barrier = barrier) -> None:
            barrier.wait()  # release all threads into the first call together
            try:
                assert schema(data) == data
            except Exception as exc:  # noqa: BLE001 - any raise is the failure mode
                errors.append(exc)

        threads = [threading.Thread(target=run) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert not errors, errors
