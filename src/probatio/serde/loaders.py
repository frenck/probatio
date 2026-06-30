"""Load JSON, YAML, and TOML, picking the fastest safe parser that is installed.

``load_json`` uses orjson when it is available and falls back to the standard
library. ``load_yaml`` uses YAMLRocks when available, then PyYAML's safe loader;
it never uses an unsafe YAML loader, because the input is untrusted by default.
``load_toml`` uses the standard library's ``tomllib`` (always present on the
supported Python versions). The YAML parser is not a hard dependency: install the
``probatio[yaml]`` or ``probatio[fast]`` extras to get one.

``load`` is the unified entry point: it dispatches on ``format``, or, when
``format`` is omitted and the source is a path, auto-detects from the extension.

A source may be a string or bytes (the content itself), a ``pathlib.Path`` (read
from disk), or a file-like object (its ``read()`` is used).

Each loader takes an optional ``options`` mapping that is forwarded as keyword
arguments to the active backend (for example a YAML spec switch for YAMLRocks, or
``parse_float`` for TOML). Options are backend-specific, so passing them couples
the call to whichever backend is installed; without them, the backend stays an
invisible implementation detail.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from probatio.error import Location
from probatio.serde import _optional
from probatio.serde._config import effective_options

if TYPE_CHECKING:
    from collections.abc import Callable


def _read(source: Any) -> Any:
    """Read the raw content from a string, bytes, path, or file-like object."""
    if isinstance(source, str | bytes):
        return source
    if isinstance(source, Path):
        return source.read_text()
    if hasattr(source, "read"):
        return source.read()
    message = "source must be a string, bytes, path, or file-like object"
    raise TypeError(message)


def _forward_options(
    fn: Callable[..., Any],
    *args: Any,
    options: dict[str, Any],
    backend: str,
    what: str,
) -> Any:
    """Call ``fn(*args, **options)``, turning an unaccepted-option error into a clear one.

    Backend options are specific to the installed backend (YAMLRocks and PyYAML do
    not share option names, for one), so an option meant for one backend reaches
    another as an unexpected keyword. Rather than leak the raw ``TypeError``, name
    the backend and the offending options so the cause is obvious.
    """
    try:
        return fn(*args, **options)
    except TypeError as exc:
        if options and "argument" in str(exc):
            keys = ", ".join(sorted(options))
            message = (
                f"the active {what} backend ({backend}) does not accept the "
                f"option(s): {keys}. Backend options are specific to the installed "
                f"backend."
            )
            raise ValueError(message) from exc
        raise


def _reject_json_constant(token: str) -> Any:
    """Refuse the non-standard JSON constants NaN/Infinity/-Infinity."""
    message = f"{token} is not valid JSON"
    raise ValueError(message)


def load_json(source: Any, *, options: dict[str, Any] | None = None) -> Any:
    """Parse JSON from a string, bytes, path, or file-like object.

    ``options`` are forwarded to the active backend's ``loads``. orjson's takes no
    keyword arguments, so options apply only on the standard-library path.
    """
    data = _read(source)
    opts = effective_options("json", "load", options)
    if opts:
        # orjson.loads accepts no options at all, so any load option (parse_float,
        # object_hook, and the like) is a standard-library one; honor it there,
        # whether or not orjson is installed, instead of leaking a TypeError. Default
        # to rejecting NaN/Infinity (the caller can override parse_constant) so the
        # result does not depend on which backend is installed.
        merged: dict[str, Any] = {"parse_constant": _reject_json_constant, **opts}
        return json.loads(data, **merged)
    if _optional.orjson is not None:
        return _optional.orjson.loads(data)
    # The standard library accepts the JavaScript constants NaN/Infinity/-Infinity by
    # default, where orjson (strict RFC 8259) rejects them. Reject them here too so
    # hostile non-standard JSON behaves the same with or without orjson installed.
    return json.loads(data, parse_constant=_reject_json_constant)


def load_yaml(source: Any, *, options: dict[str, Any] | None = None) -> Any:
    """Parse YAML safely, using YAMLRocks or PyYAML when available.

    ``options`` are forwarded to the active backend's ``loads`` (for YAMLRocks, the
    ``OPT_*`` flags via ``option=``, ``include_dir=``, and so on).

    Safe here means no arbitrary object construction (no ``!!python/object`` and the
    like): the input is treated as untrusted. For a YAML "alias bomb" (the
    billion-laughs pattern of anchors that reference each other), the backend
    matters. YAMLRocks counts the expanded nodes and refuses a document that blows
    up, so the ``probatio[fast]`` backend is bomb-resistant. PyYAML does not: it
    shares the alias references, so the document parses cheaply and the cost lands
    later when the structure is walked (during validation, say). Prefer the fast
    backend for genuinely untrusted YAML, and bound the input size on the PyYAML
    fallback.
    """
    data = _read(source)
    opts = effective_options("yaml", "load", options)
    if _optional.yamlrocks is not None:
        return _forward_options(
            _optional.yamlrocks.loads,
            data,
            options=opts,
            backend="YAMLRocks",
            what="YAML load",
        )
    if _optional.pyyaml is not None:
        return _forward_options(
            _optional.pyyaml.safe_load,
            data,
            options=opts,
            backend="PyYAML",
            what="YAML load",
        )
    message = "no YAML parser available; install probatio[yaml] or PyYAML"
    raise RuntimeError(message)


def _resolve_merge_keys(value: Any) -> Any:
    """Apply YAML merge keys (``<<``) in a round-tripped document, like ``load_yaml``.

    The round-trip parser keeps ``<<`` as a literal key; the plain loader resolves
    it. This walks the structure and merges, so both loaders return the same data.
    Explicit keys win over merged ones, and an earlier source in a ``<<`` list wins
    over a later one, matching the YAML merge specification.
    """
    if isinstance(value, list):
        return [_resolve_merge_keys(item) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[Any, Any] = {
        key: _resolve_merge_keys(item) for key, item in value.items() if key != "<<"
    }
    if "<<" in value:
        merged = value["<<"]
        sources = merged if isinstance(merged, list) else [merged]
        for source in sources:
            resolved = _resolve_merge_keys(source)
            if isinstance(resolved, dict):
                for key, item in resolved.items():
                    result.setdefault(key, item)
    return result


def load_yaml_with_locations(
    source: Any,
    *,
    options: dict[str, Any] | None = None,
) -> tuple[Any, Callable[[Any], Location | None]]:
    """Load YAML and return ``(data, locator)`` for source-located error messages.

    ``data`` is the parsed value, the same as ``load_yaml``. ``locator`` maps a
    validation error's ``path`` to a ``Location`` (file, line, column), so a
    failure can point at the exact place in the file. Pass it to
    ``humanize_error(..., locator=locator)``.

    This needs the YAMLRocks backend, version 0.5.0 or newer, which carries source
    positions and resolves a data path to the exact node (install ``probatio[fast]``).
    The locator points at the precise value, scalar leaves included. A
    ``pathlib.Path`` source sets the document origin, so the location's ``file`` is
    filled in, following nested ``!include`` layers to the source that holds the
    value. A path that is not in the document yields ``None``.
    """
    yamlrocks = _optional.yamlrocks
    if yamlrocks is None:
        message = (
            "YAML source locations require the YAMLRocks backend; "
            "install probatio[fast]"
        )
        raise RuntimeError(message)
    opts = effective_options("yaml", "load", options)
    opts["option"] = yamlrocks.OPT_ROUND_TRIP | opts.get("option", 0)
    document = yamlrocks.loads(_read(source), **opts)
    if isinstance(source, Path):
        document.set_origin(str(source))
    if not hasattr(document, "locate"):
        message = (
            "YAML source locations need YAMLRocks 0.5.0 or newer; "
            "upgrade the probatio[fast] backend"
        )
        raise RuntimeError(message)
    origin = document.origin

    def locator(path: Any) -> Location | None:
        """Resolve a validation path to the exact source position of its value."""
        try:
            handle = document.locate(list(path))
        except TypeError:
            # A path segment that is not a valid mapping key (a non-str, non-int)
            # is not something the document can locate.
            return None
        if handle is None:
            return None  # the path is not present in the document
        return Location(
            line=handle.line,
            column=handle.column,
            file=handle.file or origin,
        )

    return _resolve_merge_keys(document.to_dict()), locator


def load_toml(source: Any, *, options: dict[str, Any] | None = None) -> Any:
    """Parse TOML from a string, bytes, path, or file-like object (stdlib tomllib).

    ``options`` are forwarded to ``tomllib.loads`` (for example ``parse_float``).
    """
    data = _read(source)
    if isinstance(data, bytes):
        data = data.decode()
    return tomllib.loads(data, **effective_options("toml", "load", options))


_LOADERS: dict[str, Callable[..., Any]] = {
    "json": load_json,
    "yaml": load_yaml,
    "toml": load_toml,
}
# File extensions that map to a format for ``load``'s auto-detection.
_EXTENSIONS: dict[str, str] = {
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
}


def _detect_format(source: Any) -> str:
    """Infer the format of a source from a path extension, or fail clearly."""
    name = source.name if isinstance(source, Path) else getattr(source, "name", None)
    if isinstance(name, str):
        fmt = _EXTENSIONS.get(Path(name).suffix.lower())
        if fmt is not None:
            return fmt
    message = "cannot detect format; pass format= explicitly"
    raise ValueError(message)


def load(
    source: Any,
    format: str | None = None,  # noqa: A002
    *,
    options: dict[str, Any] | None = None,
) -> Any:
    """Parse a source, dispatching on ``format`` (auto-detected from a path).

    ``options`` are forwarded to the chosen loader's backend.
    """
    fmt = format if format is not None else _detect_format(source)
    try:
        loader = _LOADERS[fmt]
    except KeyError:
        message = f"unsupported format: {fmt!r}"
        raise ValueError(message) from None
    return loader(source, options=options)
