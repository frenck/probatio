"""The ``voluptuous.validators`` shim, exposing voluptuous's validators via probatio.

Backed by probatio's validators, but limited to the names voluptuous's
``validators`` module exposes, so a probatio-only validator (``CreditCard``,
``Alias``, ``Immutable``, and the like) cannot be imported through
``voluptuous.validators``.
"""

from __future__ import annotations

from probatio._vol_shim import _surface
from probatio._vol_shim._reexport import reexport

reexport(globals(), _surface.VALIDATORS)
