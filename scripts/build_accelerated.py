"""Build the optional mypyc-accelerated core in place (ADR-010).

This is the opt-in accelerated build. It compiles the four hot core modules
(``error``, ``markers``, ``_engine``, ``schema``) into a C extension with mypyc
and leaves the rest of the package, including every validator, interpreted. The
default build stays pure Python (ADR-005); this script is something you run
yourself, never part of the published wheel. Run it with ``just build-fast``.

The compiled ``.so`` files land next to their ``.py`` sources under ``src/`` (the
import root for the editable install), so CPython imports the native versions
when present and falls back to the pure Python sources anywhere they are absent.
Run ``just clean`` to delete them and return to pure Python.

The validators stay interpreted on purpose: the measured win (ADR-010, 1.30x
construction and 1.38x validation on a Home-Assistant-representative workload)
already lands with just these four compiled, and keeping the validators
interpreted avoids an interpreted-inherits-compiled boundary on their shared base.
"""

from __future__ import annotations

import os
from pathlib import Path

from mypyc.build import mypycify
from setuptools import setup

# The repository root, derived from this script's location (scripts/..).
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
# Build artifacts (generated C, object files, the staging lib) stay out of the
# tree under build/; only the final .so files land next to the sources.
BUILD = ROOT / "build" / "accelerated"

# The validation hot loop. mypyc compiles this into one extension; everything
# else, including every validator, stays interpreted. A compiled engine that
# imports, raises, and tags interpreted classes is fine; only the reverse
# (interpreted code inheriting a compiled class) is the boundary to avoid, and
# nothing outside _engine subclasses what it defines.
#
# The other three "core" modules from the ADR-010 spike are deliberately left
# interpreted, because a compiled build of each breaks behavior the suite catches:
#
#   error.py   The Invalid hierarchy reads its per-subclass ``default_code`` off
#              the type object (``type(self).default_code``). mypyc stores it as
#              an instance slot, not a class attribute, so ``.code`` raises and the
#              failure path segfaults.
#   schema.py  ``Schema`` must be non-native (``DataclassSchema``/``TypedDictSchema``
#              and user code subclass it, and mypyc forbids interpreted classes
#              inheriting a compiled one). Compiling a non-native ``Schema`` trips an
#              internal mypyc assertion on ``_compile_self``'s nested closure.
#   markers.py The markers must be non-native too (they are copied and subclassed).
#              A compiled non-native subclass breaks ``isinstance(x, Marker)``, so
#              marker ordering and equality go wrong.
#
# These are not cosmetic adjustments; they are real blockers (see ADR-010). The
# engine is the part that compiles cleanly and keeps full behavioral parity, so it
# is the honest floor for this opt-in build.
CORE_MODULES = [str(SRC / "probatio" / "_engine.py")]


def main() -> None:
    """Compile the core modules in place with mypyc.

    The build runs from ``src/`` so ``build_ext --inplace`` places each compiled
    module next to its source (``probatio.error`` to ``src/probatio/error.so``,
    the shared group module to ``src/``) and so setuptools does not read the
    project's ``pyproject.toml`` (its license metadata is for the pure-Python
    wheel, not this throwaway extension build).
    """
    BUILD.mkdir(parents=True, exist_ok=True)
    os.chdir(SRC)

    setup(
        name="probatio-accelerated",
        ext_modules=mypycify(
            CORE_MODULES,
            target_dir=str(BUILD / "c"),
            group_name="probatio",
        ),
        script_args=[
            "build_ext",
            "--inplace",
            "--build-temp",
            str(BUILD / "temp"),
            "--build-lib",
            str(BUILD / "lib"),
        ],
    )


if __name__ == "__main__":
    main()
