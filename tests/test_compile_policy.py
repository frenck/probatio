"""Tests for the compile flag, the process-wide policy, and Schema.compile()."""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

import pytest

from probatio import (
    Any,
    CompilePolicy,
    DataclassSchema,
    Required,
    Schema,
    TypedDictSchema,
    get_compile_policy,
    set_compile_policy,
)
from probatio._compile_policy import _DEFAULT_POLICY
from probatio.schema import _AUTO_COMPILE_THRESHOLD

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import FrameType


@pytest.fixture(autouse=True)
def _reset_policy() -> Iterator[None]:
    """Restore the process-wide policy after each test, so they do not leak."""
    original = get_compile_policy()
    try:
        yield
    finally:
        set_compile_policy(original)


def test_default_policy_is_auto() -> None:
    """The library default is AUTO: schemas compile themselves once they prove hot.

    The test session pins a deterministic policy, so assert the real default through
    the module constant rather than the live value.
    """
    assert _DEFAULT_POLICY is CompilePolicy.AUTO
    set_compile_policy(CompilePolicy.AUTO)
    assert Schema({"a": int})._should_compile() is True
    assert Schema({"a": int}, compile=False)._should_compile() is False


def test_set_compile_policy_rejects_a_non_policy() -> None:
    """A stray value (a string like "off") is refused, not stored and silently wrong."""
    with pytest.raises(TypeError, match="CompilePolicy"):
        set_compile_policy("off")  # type: ignore[arg-type]
    assert isinstance(get_compile_policy(), CompilePolicy)  # unchanged, still valid


def test_policy_on_compiles_an_unset_schema() -> None:
    """Under the ON policy a schema with no flag opts in."""
    set_compile_policy(CompilePolicy.ON)
    assert Schema({"a": int})._should_compile() is True


def test_policy_auto_arms_a_schema() -> None:
    """AUTO is a compile policy: an unset schema is set up to compile (adaptively)."""
    set_compile_policy(CompilePolicy.AUTO)
    assert Schema({"a": int})._should_compile() is True


def test_auto_bootstrap_is_thread_safe_on_a_cold_schema() -> None:
    """Many threads racing a cold AUTO schema's first call all get the right result.

    The first call resolves the bootstrap, popping the interpreted validator and
    swapping in the adaptive one. That one-time swap is locked, so a thread that loses
    the race delegates to the resolved validator instead of re-entering the bootstrap
    against a half-installed one.
    """
    set_compile_policy(CompilePolicy.AUTO)
    schema = Schema({"a": int})

    workers = 50
    start = threading.Barrier(workers)
    results: list[object] = []
    errors: list[BaseException] = []
    guard = threading.Lock()

    def hammer() -> None:
        start.wait()
        try:
            out = schema({"a": 1})
        except BaseException as exc:  # noqa: BLE001 - captured for the assertion below
            with guard:
                errors.append(exc)
        else:
            with guard:
                results.append(out)

    threads = [threading.Thread(target=hammer) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert results == [{"a": 1}] * workers


def test_captured_bootstrap_is_thread_safe_through_a_combinator() -> None:
    """Threads racing a combinator's captured mapping-branch bootstrap all succeed.

    A combinator branch captures the armed bootstrap at construction and keeps
    calling through it after the schema resolves. The resolver installs the final
    validator before dropping the interpreted one, so a racer that observes the
    resolved state always finds a real validator, never the bootstrap itself
    (which would recurse).
    """
    set_compile_policy(CompilePolicy.AUTO)
    schema = Schema(Any({Required("value"): int}, str))

    workers = 50
    start = threading.Barrier(workers)
    results: list[object] = []
    errors: list[BaseException] = []
    guard = threading.Lock()

    def hammer() -> None:
        start.wait()
        try:
            # Enough calls per thread to cross the AUTO threshold mid-race, so
            # the counter-to-generated swap is exercised through the stale
            # reference as well.
            for _ in range(60):
                out = schema({"value": 1})
        except BaseException as exc:  # noqa: BLE001 - captured for the assertion below
            with guard:
                errors.append(exc)
        else:
            with guard:
                results.append(out)

    threads = [threading.Thread(target=hammer) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert results == [{"value": 1}] * workers


def test_explicit_true_overrides_a_policy_of_off() -> None:
    """compile=True compiles even when the policy is off."""
    assert Schema({"a": int}, compile=True)._should_compile() is True


def test_explicit_false_overrides_a_policy_of_on() -> None:
    """compile=False opts out even when the policy is on."""
    set_compile_policy(CompilePolicy.ON)
    assert Schema({"a": int}, compile=False)._should_compile() is False


def test_compile_method_opts_in_and_returns_self() -> None:
    """schema.compile() records the intent and returns the same schema."""
    schema = Schema({"a": int})
    assert schema.compile() is schema
    assert schema._should_compile() is True


def test_compile_method_wins_over_an_explicit_false() -> None:
    """Calling compile() is more explicit than a construction-time compile=False."""
    schema = Schema({"a": int}, compile=False).compile()
    assert schema._should_compile() is True


def test_compiled_schema_still_validates_identically() -> None:
    """The flag only affects speed; a compiled mapping returns the same result."""
    interpreted = Schema({"a": int, "b": str})
    compiled = Schema({"a": int, "b": str}, compile=True)
    data = {"a": 1, "b": "x"}
    assert compiled(data) == interpreted(data) == data


def test_dataclass_and_typeddict_schemas_accept_the_flag() -> None:
    """DataclassSchema and TypedDictSchema thread the compile flag through."""

    @dataclass
    class Point:
        x: int
        y: int

    class Movie(TypedDict):
        title: str

    assert DataclassSchema(Point, compile=True)._should_compile() is True
    assert TypedDictSchema(Movie, compile=False)._should_compile() is False


def test_auto_compiles_when_the_count_moves_on_before_it_is_tested() -> None:
    """A count that passes the threshold between increment and test still compiles.

    The counter is not synchronized, so a second caller can add to it right after
    the first one did. That interleaving is replayed here on one thread: a trace
    function calls the schema again at the moment the count has just reached the
    threshold, before the line that tests it runs.
    """
    set_compile_policy(CompilePolicy.AUTO)
    schema = Schema({"a": int})
    data = {"a": 1}
    for _ in range(_AUTO_COMPILE_THRESHOLD - 1):
        schema(data)

    counter = schema._compiled
    interleaved: list[bool] = []

    def tracer(frame: FrameType, event: str, _arg: object) -> object:
        """Call the counter once more, right after the count reaches the threshold."""
        if frame.f_code is not counter.__code__:
            return None
        if (
            event == "line"
            and not interleaved
            and frame.f_locals["calls"] == _AUTO_COMPILE_THRESHOLD
        ):
            interleaved.append(True)
            counter(data)
        return tracer

    previous = sys.gettrace()
    sys.settrace(tracer)
    try:
        schema(data)
    finally:
        sys.settrace(previous)

    assert interleaved
    assert schema._compiled is not counter
    assert schema(data) == data


def test_a_captured_auto_counter_stops_counting_once_it_compiled() -> None:
    """A counter something still holds delegates after the swap and compiles once."""
    set_compile_policy(CompilePolicy.AUTO)
    schema = Schema({"a": int})
    data = {"a": 1}
    schema(data)
    counter = schema._compiled

    compiles: list[object] = []
    original = schema._compile_from

    def counting(interpreted: object) -> object:
        """Record the compile, then do it."""
        compiles.append(interpreted)
        return original(interpreted)

    schema._compile_from = counting  # type: ignore[method-assign]
    for _ in range(_AUTO_COMPILE_THRESHOLD * 3):
        assert counter(data) == data

    assert len(compiles) == 1
    assert schema._compiled is not counter
