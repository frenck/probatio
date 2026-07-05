"""Snapshot of Probatio's full public surface: the 1.0 freeze guard.

The public API is the contract, so a change to it should be deliberate and
visible. This captures every name in ``probatio.__all__`` and, for the callables,
a version-stable shape of the signature: each parameter's name, kind, and default,
but not the annotation strings (those render differently across Python versions,
so they would make the snapshot flap without saying anything about the surface).

An unintended change to the surface (a renamed parameter, a dropped export, a
default flipped) fails this test. An intended one is a reviewable diff: regenerate
with ``pytest --snapshot-update`` and the changed snapshot is the record of what
moved and why.
"""

from __future__ import annotations

import inspect
from typing import Any

import probatio

# Defaults whose ``repr`` is stable across runs and Python versions. Anything else
# (a factory, a sentinel object, a marker) is recorded by type name instead, so a
# memory-address repr can never make the snapshot flap. A set or frozenset is left
# out on purpose: its repr order depends on ``PYTHONHASHSEED``, so it would flap
# between runs; such a default falls back to the stable ``<frozenset>`` token.
_STABLE_DEFAULT = (type(None), bool, int, float, str, bytes)


def _default(param: inspect.Parameter) -> str:
    """Render a parameter's default as a stable token."""
    if param.default is inspect.Parameter.empty:
        return "required"
    if isinstance(param.default, _STABLE_DEFAULT):
        return repr(param.default)
    return f"<{type(param.default).__name__}>"


def _signature(obj: Any) -> list[str] | None:
    """A version-stable signature: ``name/kind/default`` per parameter, no annotations."""
    try:
        signature = inspect.signature(obj)
    except (TypeError, ValueError):
        return None
    return [
        f"{param.name} {param.kind.name} {_default(param)}"
        for param in signature.parameters.values()
    ]


def _kind(obj: Any) -> str:
    """Classify a public name as a class, a function, or a plain value."""
    if inspect.isclass(obj):
        return "class"
    if inspect.isroutine(obj):
        return "function"
    return "value"


def test_public_surface_snapshot(snapshot: Any) -> None:
    """The complete public surface matches the committed snapshot (the 1.0 freeze).

    Regenerate deliberately with ``pytest --snapshot-update`` when you mean to move
    the surface; the snapshot diff is the record of the change.
    """
    surface: dict[str, dict[str, Any]] = {}
    for name in sorted(probatio.__all__):
        obj = getattr(probatio, name)
        entry: dict[str, Any] = {"kind": _kind(obj)}
        signature = _signature(obj)
        if signature is not None:
            entry["signature"] = signature
        surface[name] = entry
    assert surface == snapshot
