"""A registry mapping a type to a validator, for the annotation-driven builders.

The structural builders (``create_dataclass_schema`` today, the ``Annotated`` and
``TypedDict`` paths as they land) turn a field's type into a validator. For a
scalar type that arrives as a string (a ``datetime``, a ``UUID``, a ``Path``),
the default is a strict ``isinstance`` check, which rejects the string a loader
produced. Registering a validator for that type tells the builders to use it
instead, so coercion becomes opt-in without making it the default (ADR-008).

Two layers, like the serde options in ``serde/_config.py``: a process-wide
registry set with ``register_type`` (for an application's entry point), and a
scoped overlay from the ``type_registry`` context manager (async- and thread-safe,
for code that must not mutate global state). A scoped registration wins over a
process-wide one for the same type.

The registry is read when a schema is *built*, and the chosen validator is baked
in, so a schema is stable once constructed: registering later does not change a
schema already built. The match is by exact type, not by subclass. The builders'
``isinstance`` path for hand-written schemas is unaffected; only annotation-driven
building consults the registry.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

# Process-wide registrations (visible to every thread), keyed by exact type.
_global: dict[type, Any] = {}

# Scoped overlays, per context (thread or async task), pushed by type_registry.
# The default is None (not a shared mutable ``{}``); readers treat it as empty.
_scoped: ContextVar[dict[type, Any] | None] = ContextVar(
    "probatio_type_registry",
    default=None,
)


def register_type(cls: type, validator: Any) -> None:
    """Register ``validator`` as the schema for ``cls`` in annotation-driven builders.

    From this point, a field annotated with ``cls`` builds to ``validator`` (any
    schema: a ``Coerce``, a callable, an ``All`` chain, a nested ``Schema``)
    instead of a bare ``isinstance`` check. Set this once at an application's entry
    point; a reusable library should prefer ``type_registry`` so it does not change
    behavior for the whole process. Re-registering replaces the previous entry.
    """
    if not isinstance(cls, type):
        message = f"register_type expects a type, got {cls!r}"
        raise TypeError(message)
    _global[cls] = validator


def clear_type_registry() -> None:
    """Drop every process-wide registration made with ``register_type``."""
    _global.clear()


@contextlib.contextmanager
def type_registry(registrations: Mapping[type, Any]) -> Iterator[None]:
    """Apply type-to-validator registrations inside a ``with`` block, then restore.

    Scoped to the current context (thread or async task), so it never leaks to
    other code. Nested blocks compose, and a scoped registration wins over a
    process-wide one for the same type. Schemas built inside the block pick up the
    registrations; schemas built outside do not.
    """
    for cls in registrations:
        if not isinstance(cls, type):
            message = f"type_registry keys must be types, got {cls!r}"
            raise TypeError(message)
    current = _scoped.get() or {}
    updated = {**current, **registrations}
    token = _scoped.set(updated)
    try:
        yield
    finally:
        _scoped.reset(token)


def resolve_type_validator(cls: type) -> Any | None:
    """Return the validator registered for ``cls`` (scoped over global), or ``None``.

    Consulted by the annotation-driven builders for an exact-type match. Returns
    ``None`` when nothing is registered, so the caller keeps its default handling.
    """
    scoped = _scoped.get()
    if scoped is not None and cls in scoped:
        return scoped[cls]
    return _global.get(cls)
