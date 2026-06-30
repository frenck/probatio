"""Tests for the compile flag, the process-wide policy, and Schema.compile()."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

import pytest

from probatio import (
    CompilePolicy,
    DataclassSchema,
    Schema,
    TypedDictSchema,
    get_compile_policy,
    set_compile_policy,
)
from probatio._compile_policy import _DEFAULT_POLICY

if TYPE_CHECKING:
    from collections.abc import Iterator


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
    """The flag only affects speed; results are unchanged (it falls back today)."""
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
