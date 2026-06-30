"""Profile probatio's code generator and the validators it generates.

Two things are worth profiling separately: the cost of *generating* a validator
(``compile_mapping``: building the source, compiling it, binding the namespace) and
the cost of *running* a generated validator on a payload. This harness exposes both
as named targets so a hot spot can be found and tracked over time.

Usage:

    uv run --no-sync python bench/profiling.py cprofile <target>   # function-level
    uv run --no-sync python bench/profiling.py loop <target>       # bare loop, for py-spy

``cprofile`` prints the top functions by total time. ``loop`` just runs a long bare
loop so a sampling profiler can attach, for example:

    py-spy record --rate 1200 -o /tmp/run-config.svg -- \
        ./.venv/bin/python bench/profiling.py loop run-config

Targets:

    gen-config      generate a validator for a flat config mapping
    gen-dataclass   generate a fused validate-and-construct for a dataclass
    run-config      validate a config payload (fully inlined)
    run-leaf        validate a mapping of built-in leaf validators (Email, IP, ...)
    run-nested      validate a nested mapping (sub-mapping and a list)
    run-dataclass   validate and construct a dataclass
"""

from __future__ import annotations

import cProfile
import io
import pstats
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import probatio
from probatio._codegen import compile_mapping

if TYPE_CHECKING:
    from collections.abc import Callable

# Profile a known policy, never the process default: the interpreted schemas below
# are pinned with compile=False so they stay interpreted, and the compiled ones are
# generated up front, so a target measures exactly one engine.
probatio.set_compile_policy(probatio.CompilePolicy.OFF)


def _config_schema() -> dict[Any, Any]:
    """A flat configuration mapping: coercion, ranges, defaults, a list, In."""
    return {
        probatio.Required("name"): str,
        probatio.Optional("port", default=8080): probatio.All(
            probatio.Coerce(int), probatio.Range(min=1, max=65535)
        ),
        probatio.Optional("host", default="localhost"): str,
        probatio.Optional("tags", default=list): [str],
        probatio.Optional("mode"): probatio.In(["auto", "manual", "off"]),
    }


def _leaf_schema() -> dict[Any, Any]:
    """A mapping of built-in leaf validators, each a closure the generator calls."""
    return {
        probatio.Required("email"): probatio.Email(),
        probatio.Required("ip"): probatio.IPv4Address(),
        probatio.Required("host"): probatio.Hostname(),
        probatio.Required("code"): probatio.Match(r"^[A-Z]{3}$"),
        probatio.Required("slug"): probatio.Slug(),
    }


def _nested_schema() -> dict[Any, Any]:
    """A nested mapping: a sub-mapping and a list of coerced, range-checked numbers."""
    return {
        probatio.Required("entity_id"): str,
        probatio.Optional("data", default=dict): {
            probatio.Optional("brightness"): probatio.All(
                probatio.Coerce(int), probatio.Range(min=0, max=255)
            ),
            probatio.Optional("rgb"): [
                probatio.All(probatio.Coerce(int), probatio.Range(min=0, max=255))
            ],
        },
    }


@dataclass
class _Service:
    """A small dataclass for the fused validate-and-construct path."""

    name: str
    port: int
    enabled: bool
    weight: float


CONFIG_VALIDATOR = probatio.Schema(_config_schema(), compile=False)._compiled
DATACLASS_INTERP = probatio.DataclassSchema(_Service, compile=False)

CONFIG_COMPILED = probatio.Schema(_config_schema()).compile()
LEAF_COMPILED = probatio.Schema(_leaf_schema()).compile()
NESTED_COMPILED = probatio.Schema(_nested_schema()).compile()
SERVICE_COMPILED = probatio.DataclassSchema(_Service).compile()

CONFIG_PAYLOAD = {
    "name": "service",
    "port": "443",
    "host": "example.com",
    "tags": ["a", "b", "c"],
    "mode": "auto",
}
LEAF_PAYLOAD = {
    "email": "user@example.com",
    "ip": "192.168.1.1",
    "host": "example.com",
    "code": "ABC",
    "slug": "my-slug",
}
NESTED_PAYLOAD = {
    "entity_id": "light.kitchen",
    "data": {"brightness": "200", "rgb": [255, 0, 0]},
}
SERVICE_PAYLOAD = {"name": "service", "port": 443, "enabled": True, "weight": 1.5}


def _make(target: str) -> Callable[[], Any]:
    """Return a zero-argument callable that does one unit of the target's work."""
    work: dict[str, Callable[[], Any]] = {
        "gen-config": lambda: compile_mapping(CONFIG_VALIDATOR),
        "gen-dataclass": lambda: DATACLASS_INTERP._compile_from(
            DATACLASS_INTERP._compiled
        ),
        "run-config": lambda: CONFIG_COMPILED(CONFIG_PAYLOAD),
        "run-leaf": lambda: LEAF_COMPILED(LEAF_PAYLOAD),
        "run-nested": lambda: NESTED_COMPILED(NESTED_PAYLOAD),
        "run-dataclass": lambda: SERVICE_COMPILED(SERVICE_PAYLOAD),
    }
    if target not in work:
        message = f"unknown target {target!r}; choose one of {sorted(work)}"
        raise SystemExit(message)
    return work[target]


# Iteration counts tuned so each target runs for a few seconds: generation is far
# pricier per call than validation, so it needs far fewer iterations.
_ITERS = {
    "gen-config": 50_000,
    "gen-dataclass": 50_000,
    "run-config": 3_000_000,
    "run-leaf": 2_000_000,
    "run-nested": 2_000_000,
    "run-dataclass": 3_000_000,
}


def cprofile(target: str) -> None:
    """cProfile a warm hot loop and print the top functions by total time."""
    work = _make(target)
    iters = _ITERS[target]

    for _ in range(1000):  # warm the lazy paths before measuring
        work()

    profiler = cProfile.Profile()
    profiler.enable()
    for _ in range(iters):
        work()
    profiler.disable()

    buffer = io.StringIO()
    pstats.Stats(profiler, stream=buffer).sort_stats("tottime").print_stats(20)
    print(f"=== cProfile {target} ({iters:,} iterations) ===")
    print(buffer.getvalue())


def loop(target: str) -> None:
    """Run a long bare loop so a sampling profiler (py-spy) can attach."""
    work = _make(target)
    for _ in range(_ITERS[target] * 4):
        work()


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in {"cprofile", "loop"}:
        raise SystemExit(__doc__)
    {"cprofile": cprofile, "loop": loop}[sys.argv[1]](sys.argv[2])
