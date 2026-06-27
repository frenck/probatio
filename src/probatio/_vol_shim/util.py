"""The ``voluptuous.util`` shim, backed by probatio.

voluptuous keeps its string helpers (``Lower``, ``Upper``, ``Strip``, and the
like) here. probatio has one flat namespace, so this re-exports the whole public
surface, which covers those names and any other a caller reaches for.
"""

from __future__ import annotations

from probatio._vol_shim import _surface
from probatio._vol_shim._reexport import reexport

reexport(globals(), _surface.UTIL)
