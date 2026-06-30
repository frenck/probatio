"""Compare dataclass construction: mashumaro vs probatio (interpreted and compiled).

Run with: ``uv run --no-sync python bench/bench_dataclass.py``.

This is not an apples-to-apples comparison, and the point is to be honest about that.
mashumaro is a serialization library: its generated ``from_dict`` builds a dataclass
from a dict and mostly trusts the declared types. probatio's ``DataclassSchema``
*validates* every field against its type (and would reject a mismatch) and then
constructs. So mashumaro does strictly less work, and on matching, already-correct
input it should be the faster of the two. The interesting question is how close the
compiled probatio path gets while still validating.

Each row builds the same dataclass three ways (mashumaro's mixin, probatio
interpreted, probatio compiled) and constructs it from a fixed, type-correct payload
many times.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from mashumaro import DataClassDictMixin

import probatio

probatio.set_compile_policy(probatio.CompilePolicy.OFF)


@dataclass
class Small(DataClassDictMixin):
    """Four basic-typed fields."""

    name: str
    port: int
    enabled: bool
    weight: float


@dataclass
class Wide(DataClassDictMixin):
    """Twelve basic-typed fields, to show how the gap scales with field count."""

    a: str
    b: int
    c: bool
    d: float
    e: str
    f: int
    g: bool
    h: float
    i: str
    j: int
    k: bool
    m: float


SMALL_PAYLOAD = {"name": "service", "port": 443, "enabled": True, "weight": 1.5}
WIDE_PAYLOAD = {
    "a": "x", "b": 1, "c": True, "d": 1.0, "e": "y", "f": 2,
    "g": False, "h": 2.0, "i": "z", "j": 3, "k": True, "m": 3.0,
}  # fmt: skip

SCENARIOS = [
    ("small (4 fields)", Small, SMALL_PAYLOAD),
    ("wide (12 fields)", Wide, WIDE_PAYLOAD),
]

ITERATIONS = 100_000
REPEATS = 5


def _per_op_us(call: Any, payload: Any) -> float:
    """Return microseconds per construction, the best of ``REPEATS`` timed runs."""
    best = float("inf")
    for _ in range(REPEATS):
        start = time.perf_counter()
        for _ in range(ITERATIONS):
            call(payload)
        best = min(best, time.perf_counter() - start)
    return best / ITERATIONS * 1_000_000


def measure() -> list[dict[str, Any]]:
    """Time every dataclass, returning ``[{scenario, mashumaro, probatio, compiled}]``."""
    rows: list[dict[str, Any]] = []
    for name, cls, payload in SCENARIOS:
        mash = cls.from_dict
        interp = probatio.DataclassSchema(cls, compile=False)
        compiled = probatio.DataclassSchema(cls).compile()

        # Warm each once before timing.
        mash(payload)
        interp(payload)
        compiled(payload)

        rows.append(
            {
                "scenario": name,
                "mashumaro": _per_op_us(mash, payload),
                "probatio": _per_op_us(interp, payload),
                "compiled": _per_op_us(compiled, payload),
            }
        )
    return rows


def main() -> None:
    """Run every dataclass through mashumaro and both probatio engines, and compare."""
    header = (
        f"{'scenario':<18} {'mashumaro':>11} {'probatio':>11} {'compiled':>11} "
        f"{'comp vs mash':>13}"
    )
    print(header)
    print("-" * len(header))
    for row in measure():
        mash_us, interp_us, comp_us = row["mashumaro"], row["probatio"], row["compiled"]
        print(
            f"{row['scenario']:<18} {mash_us:>9.3f}µs {interp_us:>9.3f}µs "
            f"{comp_us:>9.3f}µs {comp_us / mash_us:>12.2f}x"
        )
    print(
        "\nTimes are microseconds per construction (lower is faster). 'comp vs mash' "
        "is how much slower compiled probatio is than mashumaro. mashumaro only "
        "deserializes; probatio also validates every field's type, so it does more "
        "work for that price."
    )


if __name__ == "__main__":
    main()
