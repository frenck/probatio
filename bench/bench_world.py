"""Compare probatio against the rest of the world on the dict-to-object path.

Run with: ``uv run --no-sync python bench/bench_world.py`` (after
``uv sync --group bench-world``, which ``just bench-world`` does for you).

This mirrors mashumaro's cross-library benchmark idea: take one representative
nested record, hand each library the same dict, and time how long it takes to turn
it into a validated/constructed object. Every library gets its own idiomatic
definition of the same shape, the way you would actually write it.

Be honest about what is being compared. These libraries do different amounts of
work, and the table groups them by that:

- Validators check every field against its type (and would reject a mismatch) and
  then build the result: probatio, pydantic, marshmallow. voluptuous validates but
  returns a plain dict, it does not construct an object, so it is the lightest of
  this group.
- Deserializers build the object and largely trust the declared types: mashumaro,
  cattrs, dacite, dataclasses-json.

So a deserializer being faster than probatio is expected; it is doing less. The
point is to place probatio honestly among both groups on the same workload.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import cattrs
import dacite
import voluptuous
from dataclasses_json import dataclass_json
from marshmallow import Schema, fields, post_load
from mashumaro import DataClassDictMixin
from pydantic import BaseModel
from pydantic.v1 import BaseModel as BaseModelV1

import probatio

probatio.set_compile_policy(probatio.CompilePolicy.OFF)

PAYLOAD = {
    "name": "ada",
    "age": 30,
    "active": True,
    "score": 9.5,
    "tags": ["red", "green", "blue"],
    "location": {"x": 1, "y": 2},
}


# --- plain dataclasses: probatio, cattrs, dacite all read these directly ---
@dataclass
class Point:
    x: int
    y: int


@dataclass
class Record:
    name: str
    age: int
    active: bool
    score: float
    tags: list[str]
    location: Point


# --- mashumaro: the same shape with its mixin ---
@dataclass
class PointMashumaro(DataClassDictMixin):
    x: int
    y: int


@dataclass
class RecordMashumaro(DataClassDictMixin):
    name: str
    age: int
    active: bool
    score: float
    tags: list[str]
    location: PointMashumaro


# --- dataclasses-json: the same shape with its decorator ---
@dataclass_json
@dataclass
class PointJson:
    x: int
    y: int


@dataclass_json
@dataclass
class RecordJson:
    name: str
    age: int
    active: bool
    score: float
    tags: list[str]
    location: PointJson


# --- pydantic v2 ---
class PointV2(BaseModel):
    x: int
    y: int


class RecordV2(BaseModel):
    name: str
    age: int
    active: bool
    score: float
    tags: list[str]
    location: PointV2


# --- pydantic v1 (through v2's compatibility namespace) ---
class PointV1(BaseModelV1):
    x: int
    y: int


class RecordV1(BaseModelV1):
    name: str
    age: int
    active: bool
    score: float
    tags: list[str]
    location: PointV1


# --- marshmallow: schemas that construct the plain dataclasses on load ---
class PointSchema(Schema):
    x = fields.Int(required=True)
    y = fields.Int(required=True)

    @post_load
    def _build(self, data: dict[str, Any], **_: Any) -> Point:
        return Point(**data)


class RecordSchema(Schema):
    name = fields.Str(required=True)
    age = fields.Int(required=True)
    active = fields.Bool(required=True)
    score = fields.Float(required=True)
    tags = fields.List(fields.Str(), required=True)
    location = fields.Nested(PointSchema, required=True)

    @post_load
    def _build(self, data: dict[str, Any], **_: Any) -> Record:
        return Record(**data)


# --- voluptuous: validates the dict, does not construct an object ---
VOLUPTUOUS_SCHEMA = voluptuous.Schema(
    {
        voluptuous.Required("name"): str,
        voluptuous.Required("age"): int,
        voluptuous.Required("active"): bool,
        voluptuous.Required("score"): float,
        voluptuous.Required("tags"): [str],
        voluptuous.Required("location"): {
            voluptuous.Required("x"): int,
            voluptuous.Required("y"): int,
        },
    }
)

PROBATIO = probatio.DataclassSchema(Record, compile=False)
PROBATIO_COMPILED = probatio.DataclassSchema(Record).compile()
MARSHMALLOW_SCHEMA = RecordSchema()
CATTRS = cattrs.Converter()

# (label, group, impl, loader). group is "validate" or "deserialize" (does it check
# the types or trust them); impl is "python" or "native" (pydantic v2 has a Rust
# core, pydantic-core; everything else here, including probatio, is pure Python).
LOADERS: list[tuple[str, str, str, Any]] = [
    ("probatio (compiled)", "validate", "python", PROBATIO_COMPILED),
    ("probatio", "validate", "python", PROBATIO),
    ("pydantic v2", "validate", "native", RecordV2.model_validate),
    ("pydantic v1", "validate", "python", RecordV1.parse_obj),
    ("marshmallow", "validate", "python", MARSHMALLOW_SCHEMA.load),
    ("voluptuous", "validate", "python", VOLUPTUOUS_SCHEMA),
    # probatio.construct is the opt-in "trusted input" path: it builds the dataclass
    # without validating, the same job the deserializers do, so it belongs in their
    # group for a like-for-like comparison.
    ("probatio (construct)", "deserialize", "python", PROBATIO.construct),
    ("mashumaro", "deserialize", "python", RecordMashumaro.from_dict),
    (
        "cattrs",
        "deserialize",
        "python",
        lambda payload: CATTRS.structure(payload, Record),
    ),
    (
        "dacite",
        "deserialize",
        "python",
        lambda payload: dacite.from_dict(Record, payload),
    ),
    ("dataclasses-json", "deserialize", "python", RecordJson.from_dict),
]

ITERATIONS = 50_000
REPEATS = 5


def _best_us(loader: Any) -> float:
    """Return microseconds per load for ``loader``, the best of ``REPEATS`` runs."""
    best = float("inf")
    for _ in range(REPEATS):
        start = time.perf_counter()
        for _ in range(ITERATIONS):
            loader(PAYLOAD)
        best = min(best, time.perf_counter() - start)
    return best / ITERATIONS * 1_000_000


def measure() -> list[dict[str, Any]]:
    """Time every library, returning ``[{label, group, impl, us}, ...]``, fastest first."""
    results = []
    for label, group, impl, loader in LOADERS:
        loader(PAYLOAD)  # warm
        results.append(
            {"label": label, "group": group, "impl": impl, "us": _best_us(loader)}
        )
    results.sort(key=lambda row: row["us"])
    return results


def main() -> None:
    """Print the cross-library comparison table."""
    rows = measure()
    fastest = rows[0]["us"]
    print(f"{'library':<20} {'group':<12} {'time':>10} {'vs fastest':>11}")
    print("-" * 55)
    for row in rows:
        print(
            f"{row['label']:<20} {row['group']:<12} {row['us']:>8.3f}µs "
            f"{row['us'] / fastest:>10.2f}x"
        )
    print(
        "\nMicroseconds per dict-to-object load (lower is faster). Validators check "
        "every field's type; deserializers mostly trust the types and do less work. "
        "voluptuous validates but returns a dict, it does not construct an object."
    )


if __name__ == "__main__":
    main()
