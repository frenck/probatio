"""Property-based fuzzing of the validation engine.

Two guarantees, hammered with generated schemas and data:

- Differential: probatio agrees with voluptuous on a generated schema + input,
  either accepting with the same normalized result or rejecting with the same set
  of error paths. voluptuous is the oracle; a disagreement is a probatio bug (or a
  documented deviation that the strategy must then avoid).
- Robustness: probatio never raises anything other than ``Invalid`` from a
  validation. Arbitrary junk in must come out as a clean validation error, never
  an ``AttributeError``/``KeyError``/``TypeError`` leaking from the engine.
"""

from __future__ import annotations

import contextlib
from typing import Any

import voluptuous
from hypothesis import HealthCheck, assume, given, settings

import probatio
from tests import strategies


def _result(spec: Any, lib: Any, value: Any) -> Any:
    """Run a built schema, returning ("ok", result) or ("err", set of paths).

    Only ``Invalid`` is caught; any other exception propagates so the caller can
    tell a clean validation result from a crash. Error *class* is not compared:
    probatio deliberately refines voluptuous's hierarchy (voluptuous's broad
    ScalarInvalid becomes probatio's TypeInvalid / SequenceTypeInvalid /
    DictInvalid), so a differential class match would fight that design. Per-class
    correctness is pinned by the curated validator unit tests instead.
    """
    try:
        return ("ok", lib.Schema(strategies.build(spec, lib))(value))
    except lib.MultipleInvalid as exc:
        return ("err", {tuple(error.path) for error in exc.errors})
    except lib.Invalid as exc:
        return ("err", {tuple(exc.path)})


@given(spec=strategies.specs(), value=strategies.data())
@settings(
    max_examples=600, derandomize=True, suppress_health_check=[HealthCheck.too_slow]
)
def test_matches_voluptuous(spec: Any, value: Any) -> None:
    """probatio and voluptuous agree on acceptance, result, and error paths.

    The accept/reject decision and any normalized result must match exactly. On
    rejection, probatio must report at least the paths voluptuous does; it is free
    to report more (it collects every failing sequence element, where voluptuous
    surfaces only the deepest one, a documented deviation).
    """
    try:
        expected = _result(spec, voluptuous, value)
    except Exception:  # noqa: BLE001
        # voluptuous itself raised a non-Invalid error (it is less defensive than
        # probatio in places); that is not a fair comparison point.
        assume(False)
        return
    actual = _result(spec, probatio, value)
    assert actual[0] == expected[0]
    if expected[0] == "ok":
        assert actual[1] == expected[1]
    else:
        assert expected[1] <= actual[1]


@given(spec=strategies.specs(), value=strategies.data())
@settings(
    max_examples=400, derandomize=True, suppress_health_check=[HealthCheck.too_slow]
)
def test_engine_only_raises_invalid(spec: Any, value: Any) -> None:
    """Validation never leaks a non-Invalid exception, whatever the input."""
    with contextlib.suppress(probatio.Invalid):
        probatio.Schema(strategies.build(spec, probatio))(value)
