"""The ``voluptuous`` top-level shim, backed by probatio.

These are real, auditable modules (not synthesized at import time):
``probatio.compat.install_as_voluptuous`` registers them in ``sys.modules`` under
the ``voluptuous`` name, so code that imports voluptuous resolves to probatio. This
module is the top-level ``voluptuous``; ``util`` and ``schema_builder`` are the
voluptuous submodules probatio has no direct counterpart for. The ``error``,
``humanize``, and ``validators`` submodules map to probatio's own modules.
"""

from __future__ import annotations

from probatio._vol_shim import _surface
from probatio._vol_shim._reexport import reexport

reexport(globals(), _surface.TOP)  # voluptuous's top-level surface only
