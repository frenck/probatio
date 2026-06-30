"""Compare voluptuous and probatio (interpreted and compiled) validation throughput.

Run with: ``uv run --no-sync python bench/bench.py``.

For each scenario the same schema is built in voluptuous and in probatio, the
probatio one twice: once interpreted (``compile=False``) and once compiled
(``.compile()``). A fixed payload is then validated many times through each. It
prints a small table of total time and the ratios against voluptuous, plus how much
the compiled path gains over the interpreted one. The compiled column only differs
where the schema shape actually generates code; where it does not, it bails to the
interpreted engine and the two read the same, which is honest to show.

This is a rough, single-machine comparison, not a rigorous benchmark; CodSpeed
(``just codspeed``) is the tracked one.
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


def flat_types(lib: Any) -> Any:
    """A flat mapping of plain type checks, no coercion (the isinstance hot path)."""
    return lib.Schema(
        {
            lib.Required("name"): str,
            lib.Optional("port"): int,
            lib.Optional("enabled"): bool,
            lib.Optional("ratio"): float,
        },
    )


def combinator(lib: Any) -> Any:
    """A mapping of combinators: an Any of literals and an All of Coerce plus Range."""
    return lib.Schema(
        {
            lib.Required("mode"): lib.Any("auto", "manual", "off"),
            lib.Required("level"): lib.All(lib.Coerce(int), lib.Range(min=0, max=10)),
        },
    )


def number_list(lib: Any) -> Any:
    """A list of coerced, range-checked numbers (a sequence schema, not a mapping)."""
    return lib.Schema([lib.All(lib.Coerce(int), lib.Range(min=0))])


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
        "flat types",
        flat_types,
        {"name": "service", "port": 443, "enabled": True, "ratio": 1.5},
    ),
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
        "combinator",
        combinator,
        {"mode": "auto", "level": "7"},
    ),
    (
        "number list",
        number_list,
        [str(value) for value in range(50)],
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

ITERATIONS = 100_000
REPEATS = 5


def _per_op_us(validator: Any, payload: Any) -> float:
    """Return microseconds per validation, the best of ``REPEATS`` timed runs.

    The best (minimum) run is the least disturbed by other activity on the machine,
    so it is the most stable single number for a rough comparison.
    """
    best = float("inf")
    for _ in range(REPEATS):
        start = time.perf_counter()
        for _ in range(ITERATIONS):
            validator(payload)
        best = min(best, time.perf_counter() - start)
    return best / ITERATIONS * 1_000_000


def measure() -> list[dict[str, Any]]:
    """Time every scenario, returning ``[{scenario, voluptuous, probatio, compiled}]``."""
    # Pin interpreted explicitly; the compiled schema is generated up front. Without
    # this the interpreted schema would compile itself partway through the loop.
    probatio.set_compile_policy(probatio.CompilePolicy.OFF)
    rows: list[dict[str, Any]] = []
    for name, builder, payload in SCENARIOS:
        vol_schema = builder(voluptuous)
        prob_schema = builder(probatio)
        prob_compiled = builder(probatio).compile()

        # Warm each once before timing.
        vol_schema(payload)
        prob_schema(payload)
        prob_compiled(payload)

        rows.append(
            {
                "scenario": name,
                "voluptuous": _per_op_us(vol_schema, payload),
                "probatio": _per_op_us(prob_schema, payload),
                "compiled": _per_op_us(prob_compiled, payload),
            }
        )
    return rows


def main() -> None:
    """Run every scenario through voluptuous and both probatio engines, and compare."""
    header = (
        f"{'scenario':<12} {'voluptuous':>11} {'probatio':>11} {'compiled':>11} "
        f"{'prob vs vol':>12} {'comp vs vol':>12}"
    )
    print(header)
    print("-" * len(header))
    for row in measure():
        vol, prob, comp = row["voluptuous"], row["probatio"], row["compiled"]
        print(
            f"{row['scenario']:<12} {vol:>9.3f}µs {prob:>9.3f}µs {comp:>9.3f}µs "
            f"{vol / prob:>11.2f}x {vol / comp:>11.2f}x"
        )
    print(
        "\nTimes are microseconds per validation (lower is faster). The last two "
        "columns are how many times faster than voluptuous probatio runs, "
        "interpreted and compiled. 'number list' does the most work per call (50 "
        "items), so its absolute time is the highest even though its per-item cost "
        "is in line with the rest."
    )


if __name__ == "__main__":
    main()
