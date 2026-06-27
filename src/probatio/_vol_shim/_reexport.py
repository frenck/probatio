"""Re-export a chosen slice of probatio's surface into a voluptuous-shaped module.

Each shim module passes the set of names voluptuous exposes for it (from
``_surface``), so the shim resolves voluptuous's names to probatio and nothing
more: a probatio-only validator, marker, or error cannot be imported through the
``voluptuous`` name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import probatio

if TYPE_CHECKING:
    from collections.abc import Iterable


def reexport(namespace: dict[str, object], names: Iterable[str]) -> None:
    """Copy the named probatio objects into ``namespace`` and set its ``__all__``."""
    selected = list(names)
    for name in selected:
        namespace[name] = getattr(probatio, name)
    namespace["__all__"] = selected
