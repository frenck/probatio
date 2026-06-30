"""Optional acceleration backends, resolved once at import time.

Each name is the imported module, or ``None`` when it is not installed. The
loaders and dumpers share these, so a backend is detected in exactly one place
(and tests patch one place to simulate its presence or absence).
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


def _load(name: str) -> Any:
    """Import a module by name, returning None when it is not installed.

    A genuinely absent backend raises ``ModuleNotFoundError`` naming that module, so
    return None for it. Any other import failure (a different ``ImportError``, or a
    ``ModuleNotFoundError`` naming some other module the backend imports) means the
    backend is installed but broken, so re-raise rather than silently masking it as
    absent and falling back.
    """
    try:
        return import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name == name:
            return None
        raise


orjson = _load("orjson")
yamlrocks = _load("yamlrocks")
pyyaml = _load("yaml")
# TOML is read with the standard library's tomllib; only writing needs a backend.
tomli_w = _load("tomli_w")
