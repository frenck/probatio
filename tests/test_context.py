"""Call-time validation context: ``schema(data, context=...)`` and current_context.

A validator reads ``current_context()`` to validate against state supplied per
call, like a set of allowed values known only at request time. The context is set
for the duration of the call, inherited by nested schema calls that pass none, and
overridden by those that pass their own (ADR-009).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from probatio import Required, Schema, current_context
from probatio.error import Invalid, MultipleInvalid


def _allowed(value: Any) -> Any:
    """Reject a value that is not in the per-call set of allowed values."""
    context = current_context() or {}
    if value not in context.get("allowed", ()):
        message = f"{value!r} is not allowed"
        raise Invalid(message)
    return value


def test_validator_reads_the_call_context() -> None:
    """A value in the per-call allow-set passes; one outside it fails."""
    schema = Schema({Required("entity"): _allowed})
    allow = {"allowed": {"light.kitchen"}}
    assert schema({"entity": "light.kitchen"}, context=allow) == {
        "entity": "light.kitchen",
    }
    with pytest.raises(MultipleInvalid) as caught:
        schema({"entity": "light.bath"}, context=allow)
    assert caught.value.errors[0].path == ["entity"]


def test_absent_context_is_none() -> None:
    """Without a context, current_context() is None and the validator decides."""
    schema = Schema({Required("entity"): _allowed})
    with pytest.raises(MultipleInvalid):
        schema({"entity": "anything"})


def test_context_outside_any_call_is_none() -> None:
    """current_context() is None when no validation is in progress."""
    assert current_context() is None


def test_common_path_is_unchanged_without_context() -> None:
    """A schema called without a context behaves exactly as before."""
    assert Schema({Required("n"): int})({"n": 5}) == {"n": 5}


def test_context_does_not_leak_after_the_call() -> None:
    """The context is reset when the call returns, so nothing leaks out."""
    Schema(_allowed)("x", context={"allowed": {"x"}})
    assert current_context() is None


def test_nested_call_overrides_then_restores() -> None:
    """A nested schema with its own context overrides for its subtree only."""
    inner = Schema(_allowed)
    seen: dict[str, Any] = {}

    def outer(value: Any) -> Any:
        """Call a nested schema with a different context, then check restoration."""
        assert inner("inner.ok", context={"allowed": {"inner.ok"}}) == "inner.ok"
        seen["after"] = current_context()
        return value

    schema = Schema({Required("v"): outer})
    schema({"v": "z"}, context={"allowed": {"outer.ok"}})
    assert seen["after"] == {"allowed": {"outer.ok"}}


def test_nested_call_without_context_inherits() -> None:
    """A nested schema that passes no context sees the enclosing call's."""
    inner = Schema(_allowed)

    def outer(value: Any) -> Any:
        """Validate with the inherited context (no context passed to inner)."""
        return inner(value)

    schema = Schema({Required("v"): outer})
    assert schema({"v": "ok"}, context={"allowed": {"ok"}}) == {"v": "ok"}
    with pytest.raises(MultipleInvalid):
        schema({"v": "no"}, context={"allowed": {"ok"}})


def test_inherit_context_sentinel_reprs_readably() -> None:
    """The omitted-context sentinel renders cleanly in the call signature."""
    from probatio.schema import _INHERIT_CONTEXT  # noqa: PLC0415

    assert repr(_INHERIT_CONTEXT) == "<inherit>"


def test_nested_call_with_explicit_none_clears_the_inherited_context() -> None:
    """``inner(value, context=None)`` clears the inherited context, unlike omitting it."""
    seen: list[Any] = []

    def record(value: Any) -> Any:
        """Record the context the inner call sees."""
        seen.append(current_context())
        return value

    inner = Schema(record)

    def outer(value: Any) -> Any:
        """Call the inner schema with an explicit None to clear the context."""
        return inner(value, context=None)

    Schema({Required("v"): outer})({"v": "x"}, context={"allowed": {"x"}})
    assert seen == [None]  # explicit None won over the inherited {"allowed": ...}


def test_context_is_isolated_across_async_tasks() -> None:
    """Concurrent tasks each see their own context, with no bleed between them."""
    inner = Schema(_allowed)

    async def one(value: str) -> str:
        return inner(value, context={"allowed": {value}})

    async def main() -> list[str]:
        return await asyncio.gather(one("a.id"), one("b.id"))

    assert asyncio.run(main()) == ["a.id", "b.id"]
