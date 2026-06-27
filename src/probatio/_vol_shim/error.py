"""The ``voluptuous.error`` shim, exposing voluptuous's error classes via probatio.

Backed by probatio's error types, but limited to the names voluptuous's ``error``
module exposes, so a probatio-only error (``EnumInvalid``, ``ImmutableInvalid``,
and the like) cannot be imported through ``voluptuous.error``.
"""

from __future__ import annotations

from probatio._vol_shim import _surface
from probatio._vol_shim._reexport import reexport

reexport(globals(), _surface.ERROR)
