"""Default backend options for the serde loaders and dumpers.

Two layers sit beneath a call's own ``options``: a process-wide default set with
``set_default_options`` (for an application's entry point), and a scoped override
from the ``default_options`` context manager (async- and thread-safe, for code
that must not mutate global state). ``effective_options`` merges all three for a
given format and direction, with a per-call option winning over a scoped one,
which wins over the process-wide default.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

_FORMATS = frozenset({"json", "yaml", "toml"})

# Process-wide defaults (visible to every thread), keyed by (format, direction).
_global: dict[tuple[str, str], dict[str, Any]] = {}

# Scoped overrides, per context (thread or async task), pushed by default_options.
# The default is None (not a shared mutable ``{}``); readers treat it as empty.
_scoped: ContextVar[dict[tuple[str, str], dict[str, Any]] | None] = ContextVar(
    "probatio_serde_options",
    default=None,
)


def _check_format(fmt: str) -> None:
    """Reject a format name that is not one of json/yaml/toml."""
    if fmt not in _FORMATS:
        message = f"unknown format {fmt!r}; expected one of {sorted(_FORMATS)}"
        raise ValueError(message)


def set_default_options(
    format: str,  # noqa: A002
    *,
    load: dict[str, Any] | None = None,
    dump: dict[str, Any] | None = None,
) -> None:
    """Set process-wide default backend options for a format's load and/or dump.

    These apply to every later ``load_*``/``dump_*`` call for that format unless
    the call passes its own ``options`` (which win per key). Set this once at your
    application's entry point; a reusable library should prefer ``default_options``
    so it does not change behavior for the whole process. Pass an empty mapping to
    clear a previously set default.
    """
    _check_format(format)
    if load is not None:
        _global[format, "load"] = dict(load)
    if dump is not None:
        _global[format, "dump"] = dict(dump)


def clear_default_options() -> None:
    """Drop every process-wide default set by ``set_default_options``."""
    _global.clear()


@contextlib.contextmanager
def default_options(
    format: str,  # noqa: A002
    *,
    load: dict[str, Any] | None = None,
    dump: dict[str, Any] | None = None,
) -> Iterator[None]:
    """Apply backend options for a format inside a ``with`` block, then restore.

    Scoped to the current context (thread or async task), so it never leaks to
    other code. Nested blocks compose, and a per-call ``options`` still wins over
    the scoped value.
    """
    _check_format(format)
    current = _scoped.get() or {}
    updated = dict(current)
    if load is not None:
        updated[format, "load"] = {**current.get((format, "load"), {}), **load}
    if dump is not None:
        updated[format, "dump"] = {**current.get((format, "dump"), {}), **dump}
    token = _scoped.set(updated)
    try:
        yield
    finally:
        _scoped.reset(token)


def effective_options(
    format: str,  # noqa: A002
    direction: str,
    per_call: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge the process-wide default, the scoped override, and per-call options.

    Per-call wins over the scoped override, which wins over the process-wide
    default. Returns the merged mapping (possibly empty) for the backend call.
    """
    key = (format, direction)
    merged: dict[str, Any] = {}
    merged.update(_global.get(key, {}))
    merged.update((_scoped.get() or {}).get(key, {}))
    if per_call:
        merged.update(per_call)
    return merged
