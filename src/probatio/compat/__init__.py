"""voluptuous drop-in compatibility.

Probatio mirrors the voluptuous public API, so most code only needs to change
``import voluptuous`` to ``import probatio``. But some dependencies import
voluptuous *internals* (notably ``annotatedyaml``, which imports
``voluptuous.schema_builder._compile_scalar``), and those cannot be edited.

``install_as_voluptuous`` bridges that gap: it registers the real shim modules in
``probatio._vol_shim`` (plus probatio's own ``error``/``humanize``/``validators``)
into ``sys.modules`` under the ``voluptuous`` name. Call it once, very early in
process startup, and every later ``import voluptuous`` (including inside
dependencies) resolves to probatio:

    from probatio.compat import install_as_voluptuous

    install_as_voluptuous()

This is the seam the Home Assistant drop-in proof uses (see
``compat/home_assistant/`` in the repository).
"""

from __future__ import annotations

import sys
import warnings

import probatio._vol_shim as _voluptuous  # the top-level ``voluptuous`` shim
from probatio import humanize as _humanize
from probatio._vol_shim import error as _error
from probatio._vol_shim import schema_builder as _schema_builder
from probatio._vol_shim import util as _util
from probatio._vol_shim import validators as _validators

__all__ = ["install_as_voluptuous"]

# The voluptuous submodule layout, mapped to the backing module for each. All but
# ``humanize`` are shim modules limited to voluptuous's surface, so a probatio-only
# name cannot be imported through ``voluptuous`` or its submodules. ``humanize``
# maps to probatio's own module, whose surface exposes no probatio-only name.
_SUBMODULES = {
    "error": _error,
    "humanize": _humanize,
    "validators": _validators,
    "schema_builder": _schema_builder,
    "util": _util,
}


def install_as_voluptuous() -> None:
    """Register the voluptuous shim in ``sys.modules`` as ``voluptuous``.

    After this call, ``import voluptuous`` (and the submodules dependencies reach
    into) resolve to probatio for the rest of the process.

    This is a deliberate, process-wide aliasing intended to be called once at
    startup, before anything imports ``voluptuous``. It is idempotent and has no
    teardown. If a real ``voluptuous`` was already imported, it is shadowed and a
    ``RuntimeWarning`` is emitted, since references already taken to the real
    module will not update. Do not call it from library code that others import;
    it is for an application (or test harness) that owns the process.
    """
    existing = sys.modules.get("voluptuous")
    if existing is not None and existing is not _voluptuous:
        warnings.warn(
            "install_as_voluptuous is shadowing an already-imported voluptuous; "
            "call it before anything imports voluptuous so references resolve to "
            "probatio",
            RuntimeWarning,
            stacklevel=2,
        )
    sys.modules["voluptuous"] = _voluptuous
    for name, module in _SUBMODULES.items():
        sys.modules[f"voluptuous.{name}"] = module
        # Bind as an attribute of the top shim too, so ``import voluptuous.x as y``
        # resolves (the ``from voluptuous.x import y`` form works off sys.modules).
        setattr(_voluptuous, name, module)
