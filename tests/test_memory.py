"""Memory-shape guards: no uncollectable cycles, no per-call accumulation.

probatio has no caches, finalizers, or growing global state, so classic leaks are
not a concern and flaky tracemalloc tests are not worth their noise. These two
checks instead pin the only real invariants: a recursive ``Self`` schema (which
forms a reference cycle, Schema -> closure -> root Schema) stays garbage
collectable, and repeated validation does not accumulate objects on the schema.
"""

from __future__ import annotations

import contextlib
import gc
import weakref

from probatio import Invalid, Optional, Required, Schema, Self

# A handful of objects may settle between two snapshots (interned ints, gc
# bookkeeping), so the guard is a small absolute bound rather than exact
# equality. It is tiny next to the iteration count, so genuine per-call
# accumulation (which would grow by thousands) still fails loudly.
_ALLOWED_OBJECT_DRIFT = 100
_ITERATIONS = 2000


def _recursive_schema() -> Schema:
    """A schema that references itself (the one reference cycle in the engine)."""
    return Schema({Required("value"): int, Optional("next"): Self})


def test_recursive_schema_is_garbage_collectable() -> None:
    """A recursive Self schema is reclaimed once dropped (no uncollectable cycle)."""
    schema = _recursive_schema()
    schema({"value": 1, "next": {"value": 2}})  # exercise the recursion
    ref = weakref.ref(schema)
    del schema
    gc.collect()
    assert ref() is None


def test_repeated_validation_does_not_accumulate_objects() -> None:
    """Validating many times retains nothing: the live object count stays flat."""
    schema = _recursive_schema()
    payload = {"value": 1, "next": {"value": 2, "next": {"value": 3}}}
    schema(payload)  # warm any one-time allocations before the baseline

    gc.collect()
    before = len(gc.get_objects())
    for _ in range(_ITERATIONS):
        schema(payload)
    gc.collect()
    after = len(gc.get_objects())

    assert after - before < _ALLOWED_OBJECT_DRIFT


def test_repeated_failures_do_not_accumulate_objects() -> None:
    """Failing validation many times retains no errors, paths, or exceptions."""
    schema = _recursive_schema()
    bad = {"value": 1, "next": {"value": "not an int"}}
    with contextlib.suppress(Invalid):
        schema(bad)  # warm one-time allocations on the failure path

    gc.collect()
    before = len(gc.get_objects())
    for _ in range(_ITERATIONS):
        with contextlib.suppress(Invalid):
            schema(bad)
    gc.collect()
    after = len(gc.get_objects())

    assert after - before < _ALLOWED_OBJECT_DRIFT
