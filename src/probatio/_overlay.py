"""A process-wide mapping with a context-scoped overlay, thread- and async-safe.

The type registry (``_type_registry``) and the serde option defaults
(``serde/_config``) both layer a per-context override over a process-wide default in
the same shape: a plain ``dict`` for the global layer, and a ``ContextVar`` overlay
pushed inside a ``with`` block and restored on exit. This holds that contextvar
plumbing (the ``None`` default that readers treat as empty, and the set/reset token)
in one place, so the restore semantics cannot drift between the two. Each module
keeps its own merge and lookup rules on top.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


class ContextOverlay[K, V]:
    """A process-wide ``dict`` plus a context-scoped overlay of the same shape."""

    def __init__(self, name: str) -> None:
        """Create the empty global map and the per-context overlay variable."""
        self.glob: dict[K, V] = {}
        # Default None (not a shared mutable dict, which every context would alias);
        # readers treat None as an empty overlay.
        self.scoped: ContextVar[dict[K, V] | None] = ContextVar(name, default=None)

    def current(self) -> dict[K, V]:
        """Return the current context's overlay, or an empty dict when none is set."""
        return self.scoped.get() or {}

    @contextlib.contextmanager
    def pushed(self, overlay: dict[K, V]) -> Iterator[None]:
        """Install ``overlay`` for the current context, restoring the prior one on exit."""
        token = self.scoped.set(overlay)
        try:
            yield
        finally:
            self.scoped.reset(token)
