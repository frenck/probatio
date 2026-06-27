"""Compare probatio and voluptuous validation throughput.

Run with: ``uv run --no-sync python bench/bench.py``.

For each scenario the same schema is built once in both libraries, then a fixed
payload is validated many times. It prints a small table of total time and the
probatio/voluptuous ratio. This is a rough, single-machine comparison, not a
rigorous benchmark; CodSpeed (``just codspeed``) is the tracked one.
"""

from __future__ import annotations

import time
from typing import Any

import voluptuous

import probatio


def config(lib: Any) -> Any:
    """A configuration-style schema: coercion, ranges, defaults, a list, In."""
    return lib.Schema(
        {
            lib.Required("name"): str,
            lib.Optional("port", default=8080): lib.All(
                lib.Coerce(int),
                lib.Range(min=1, max=65535),
            ),
            lib.Optional("host", default="localhost"): str,
            lib.Optional("tags", default=list): [str],
            lib.Optional("mode"): lib.In(["auto", "manual", "off"]),
        },
    )


def nested(lib: Any) -> Any:
    """A nested service-call-style schema."""
    return lib.Schema(
        {
            lib.Required("entity_id"): str,
            lib.Optional("data", default=dict): {
                lib.Optional("brightness"): lib.All(
                    lib.Coerce(int),
                    lib.Range(min=0, max=255),
                ),
                lib.Optional("rgb"): [
                    lib.All(lib.Coerce(int), lib.Range(min=0, max=255))
                ],
            },
        },
    )


SCENARIOS = [
    (
        "config",
        config,
        {
            "name": "service",
            "port": "443",
            "host": "example.com",
            "tags": ["a", "b", "c"],
            "mode": "auto",
        },
    ),
    (
        "nested",
        nested,
        {
            "entity_id": "light.kitchen",
            "data": {"brightness": "200", "rgb": [255, 0, 0]},
        },
    ),
]

ITERATIONS = 50_000


def _time(validator: Any, payload: Any, iterations: int) -> float:
    """Return the total seconds to validate ``payload`` ``iterations`` times."""
    start = time.perf_counter()
    for _ in range(iterations):
        validator(payload)
    return time.perf_counter() - start


def main() -> None:
    """Run every scenario through both libraries and print a comparison."""
    print(f"{'scenario':<12} {'probatio':>12} {'voluptuous':>12} {'ratio':>8}")
    print("-" * 48)
    for name, builder, payload in SCENARIOS:
        probatio_schema = builder(probatio)
        voluptuous_schema = builder(voluptuous)
        probatio_schema(payload)
        voluptuous_schema(payload)
        probatio_time = _time(probatio_schema, payload, ITERATIONS)
        voluptuous_time = _time(voluptuous_schema, payload, ITERATIONS)
        ratio = probatio_time / voluptuous_time
        print(
            f"{name:<12} {probatio_time:>12.4f} {voluptuous_time:>12.4f} {ratio:>7.2f}x"
        )


if __name__ == "__main__":
    main()
