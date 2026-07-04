"""Dump a validated value to JSON, YAML, or TOML, mirroring the loaders' backends.

``dump_json`` uses orjson when it is available and falls back to the standard
library; ``dump_yaml`` uses YAMLRocks when available, then PyYAML's safe dumper;
``dump_toml`` uses ``tomli-w`` (install the ``probatio[toml]`` extra). ``dump`` is
the unified entry point that dispatches on ``format``.

Before handing the value to a backend, the few non-native types a validated value
commonly carries are normalized: ``Decimal`` becomes a float and
``set``/``frozenset``/``tuple`` become a list, across every format. The temporal
types are format-aware: TOML has native ``datetime``/``date``/``time``, so those
pass through for TOML and round-trip as the same type, while JSON and YAML have no
temporal types, so they become ISO 8601 strings. JSON also has no ``nan``/``inf``,
so a non-finite float is refused rather than silently corrupted to ``null`` (the
fast backend) or an invalid token (the standard library). A ``default`` hook
(called like the standard library's) handles anything else. This is a convenience
for round-tripping validated data, not a general serialization framework.
"""

from __future__ import annotations

import datetime
import json
import math
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from probatio.serde import _optional
from probatio.serde._config import effective_options
from probatio.serde.loaders import _forward_options

if TYPE_CHECKING:
    from collections.abc import Callable


def _encodable_str(value: str) -> str:
    """Return the string, or raise if it holds an unpaired surrogate.

    A lone surrogate has no UTF-8 encoding, so it cannot be represented in
    JSON/YAML/TOML text at all. orjson rejects it, but the stdlib JSON fallback (and
    the YAML path) would emit output that cannot be re-read, so it is refused here
    with a clear error rather than silently produced. ASCII strings skip the check.
    """
    if not value.isascii():
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            message = "cannot serialize a string containing unpaired surrogates"
            raise ValueError(message) from exc
    return value


def _normalize(  # noqa: PLR0911, PLR0912
    value: Any, default: Any, *, fmt: str, seen: set[int] | None = None
) -> Any:
    """Convert a value into one built only from the target format's native types.

    ``seen`` tracks the container ids on the current recursion path, so a circular
    structure fails with a clean ``ValueError`` instead of recursing until the
    interpreter raises ``RecursionError`` (or hangs a backend).
    """
    if isinstance(value, bool) or value is None:
        return value

    if isinstance(value, float):
        if fmt == "json" and not math.isfinite(value):
            message = "JSON cannot represent a non-finite float (nan, inf, -inf)"
            raise ValueError(message)
        return value

    if isinstance(value, str):
        return _encodable_str(value)

    if isinstance(value, int):
        return value

    if isinstance(value, dict | list | tuple | set | frozenset):
        if seen is None:
            seen = set()
        marker = id(value)
        if marker in seen:
            message = "circular reference detected"
            raise ValueError(message)
        seen.add(marker)
        try:
            if isinstance(value, dict):
                return _normalize_dict(value, default, fmt=fmt, seen=seen)
            return [_normalize(item, default, fmt=fmt, seen=seen) for item in value]
        finally:
            seen.discard(marker)

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, datetime.date | datetime.time):
        return value if fmt == "toml" else value.isoformat()

    if default is not None:
        return _normalize(default(value), default, fmt=fmt, seen=seen)

    message = f"cannot serialize value of type {type(value).__name__}"
    raise TypeError(message)


def _normalize_dict(
    value: dict[Any, Any], default: Any, *, fmt: str, seen: set[int]
) -> dict[Any, Any]:
    """Normalize a mapping, refusing JSON keys that collide once coerced to strings.

    JSON object keys are strings, so a non-string key is coerced (``1`` and ``"1"``
    both become ``"1"``). Two keys that coerce to the same string would silently
    overwrite each other in the output, so that is refused rather than dropped.
    """
    result: dict[Any, Any] = {}
    coerced_keys: set[str] | None = set() if fmt == "json" else None

    for key, item in value.items():
        if coerced_keys is not None:
            coerced = _json_key(key)
            if isinstance(coerced, str):
                if coerced in coerced_keys:
                    message = (
                        f"duplicate JSON object key {coerced!r} after coercing a "
                        f"non-string key"
                    )
                    raise ValueError(message)
                coerced_keys.add(coerced)
        result[key] = _normalize(item, default, fmt=fmt, seen=seen)

    return result


def _json_key(key: Any) -> str | None:
    """Return the JSON object-key string a key coerces to, or None if not coercible.

    A non-coercible key (a tuple, say) returns ``None``, so collision detection
    leaves it for the backend to reject, unchanged from before.
    """
    if isinstance(key, str):
        return key
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, int | float):
        return str(key)
    if key is None:
        return "null"
    return None


def _as_text(result: Any) -> str:
    """Normalize a backend's output to str (orjson and YAMLRocks return bytes)."""
    return cast("str", result.decode() if isinstance(result, bytes) else result)


def dump_json(
    value: Any,
    *,
    default: Any = None,
    options: dict[str, Any] | None = None,
) -> str:
    """Serialize a value to a JSON string, normalizing non-native types first.

    Without ``options`` the output does not depend on which backend is installed:
    orjson cannot serialize an integer beyond 64 bits or a non-string dict key, so
    those fall back to the standard library, which can, and the standard-library
    path matches orjson's compact separators and raw (non-escaped) UTF-8 so both
    backends produce the same text. With ``options`` (forwarded to the active
    backend, like ``orjson.OPT_INDENT_2`` via ``option=``), the output is tuned to
    that backend and the cross-backend guarantee no longer applies.
    """
    native = _normalize(value, default, fmt="json")
    opts = effective_options("json", "dump", options)

    if opts:
        if _optional.orjson is not None:
            return _as_text(
                _forward_options(
                    _optional.orjson.dumps,
                    native,
                    options=opts,
                    backend="orjson",
                    what="JSON dump",
                )
            )
        return cast(
            "str",
            _forward_options(
                json.dumps,
                native,
                options=opts,
                backend="standard library json",
                what="JSON dump",
            ),
        )

    if _optional.orjson is not None:
        try:
            return _as_text(_optional.orjson.dumps(native))
        except TypeError:
            # orjson rejects >64-bit ints and non-str keys; the stdlib handles
            # both, so fall back rather than diverge on which backend is present.
            pass
    # ``ensure_ascii=False`` so non-ASCII text is emitted raw, the way orjson
    # does, keeping the output identical regardless of which path ran.
    return json.dumps(native, separators=(",", ":"), ensure_ascii=False)


def dump_yaml(
    value: Any,
    *,
    default: Any = None,
    options: dict[str, Any] | None = None,
) -> str:
    """Serialize a value to a YAML string, normalizing non-native types first.

    ``options`` are forwarded to the active backend's ``dumps`` (the ``OPT_*``
    flags via ``option=`` for YAMLRocks, or kwargs like ``sort_keys`` for PyYAML).
    """
    native = _normalize(value, default, fmt="yaml")
    opts = effective_options("yaml", "dump", options)

    if _optional.yamlrocks is not None:
        return _as_text(
            _forward_options(
                _optional.yamlrocks.dumps,
                native,
                options=opts,
                backend="YAMLRocks",
                what="YAML dump",
            )
        )

    if _optional.pyyaml is not None:
        return _as_text(
            _forward_options(
                _optional.pyyaml.safe_dump,
                native,
                options=opts,
                backend="PyYAML",
                what="YAML dump",
            )
        )

    message = "no YAML dumper available; install probatio[yaml] or PyYAML"
    raise RuntimeError(message)


def dump_toml(
    value: Any,
    *,
    default: Any = None,
    options: dict[str, Any] | None = None,
) -> str:
    """Serialize a value to a TOML string (requires the ``probatio[toml]`` extra).

    A TOML document is a table, so the top-level value must be a mapping; a bare
    scalar or list is refused with a clear error rather than leaking an
    ``AttributeError`` from the backend. ``options`` are forwarded to ``tomli_w``.
    """
    native = _normalize(value, default, fmt="toml")
    if not isinstance(native, dict):
        message = (
            f"TOML can only serialize a mapping at the top level, "
            f"got {type(value).__name__}"
        )
        raise TypeError(message)

    if _optional.tomli_w is not None:
        return _as_text(
            _forward_options(
                _optional.tomli_w.dumps,
                native,
                options=effective_options("toml", "dump", options),
                backend="tomli-w",
                what="TOML dump",
            ),
        )
    message = "no TOML dumper available; install probatio[toml] or tomli-w"
    raise RuntimeError(message)


_DUMPERS: dict[str, Callable[..., str]] = {
    "json": dump_json,
    "yaml": dump_yaml,
    "toml": dump_toml,
}


def dump(
    value: Any,
    format: str,  # noqa: A002
    *,
    default: Any = None,
    options: dict[str, Any] | None = None,
) -> str:
    """Serialize a value, dispatching on ``format`` ("json", "yaml", or "toml").

    ``options`` are forwarded to the chosen dumper's backend.
    """
    try:
        dumper = _DUMPERS[format]
    except KeyError:
        message = f"unsupported format: {format!r}"
        raise ValueError(message) from None

    return dumper(value, default=default, options=options)
