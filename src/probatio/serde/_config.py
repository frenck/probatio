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
from typing import TYPE_CHECKING, Any

from probatio._overlay import ContextOverlay

if TYPE_CHECKING:
    from collections.abc import Iterator

_FORMATS = frozenset({"json", "yaml", "toml"})

# Two layers keyed by (format, direction): the process-wide ``set_default_options``
# map and a ``default_options`` overlay scoped to the current thread or async task.
_options: ContextOverlay[tuple[str, str], dict[str, Any]] = ContextOverlay(
    "probatio_serde_options",
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
        _options.glob[format, "load"] = dict(load)
    if dump is not None:
        _options.glob[format, "dump"] = dict(dump)


def clear_default_options() -> None:
    """Drop every process-wide default set by ``set_default_options``."""
    _options.glob.clear()


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

    current = _options.current()
    updated = dict(current)
    if load is not None:
        updated[format, "load"] = {**current.get((format, "load"), {}), **load}
    if dump is not None:
        updated[format, "dump"] = {**current.get((format, "dump"), {}), **dump}

    with _options.pushed(updated):
        yield


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
    merged.update(_options.glob.get(key, {}))
    merged.update(_options.current().get(key, {}))
    if per_call:
        merged.update(per_call)

    return merged
