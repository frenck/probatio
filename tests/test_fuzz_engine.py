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
from typing import TYPE_CHECKING, Any

import voluptuous
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

import probatio
from tests import strategies

if TYPE_CHECKING:
    from random import Random


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


def _assert_agrees_with_voluptuous(spec: Any, value: Any) -> None:
    """Probatio accepts and rejects what voluptuous does, with the same result.

    The accept/reject decision and any normalized result must match exactly. On
    rejection, probatio must report at least the paths voluptuous does; it is free
    to report more (it collects every failing sequence element, where voluptuous
    surfaces only the deepest one, a documented deviation). The one exception is
    a schema where that deviation decides which ``Any`` branch is reported; see
    ``_chooses_between_branches_with_a_list``.
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
    elif not _chooses_between_branches_with_a_list(spec):
        assert expected[1] <= actual[1]


def _children(spec: Any) -> list[Any]:
    """The specs directly inside a spec."""
    kind = spec[0]
    if kind in ("maybe", "list"):
        return [spec[1]]
    if kind in ("any", "union"):
        return list(spec[1])
    if kind == "dict":
        _, fields, _, catchall = spec
        inside = [child for _, child in fields.values()]
        return inside if catchall is None else [*inside, *catchall[1:]]
    return []


def _holds(kinds: tuple[str, ...], spec: Any) -> bool:
    """Whether a spec of one of the kinds sits anywhere in a spec, itself included."""
    return spec[0] in kinds or any(_holds(kinds, child) for child in _children(spec))


def _chooses_between_branches_with_a_list(spec: Any) -> bool:
    """Whether an ``Any`` or ``Union`` in a spec can pick a branch by a list's error.

    A failing ``Any`` reports the branch whose error reached the deepest path, and
    both libraries measure that on the branch's first error. A list reports every
    failing item in probatio and only the deepest failure in voluptuous, a
    documented deviation, so a list branch can open with a shallow error in
    probatio and lose a contest it wins in voluptuous:
    ``Any([int], [{"a": int}])`` against ``[1, {"a": "x"}]`` is ``[1]`` in probatio
    and ``[1, "a"]`` in voluptuous. Both still reject.

    The contest needs two branches that reach below the value, so two holding a
    list or a mapping, one of them a list. For a spec that holds such a choice
    anywhere, the differential compares the decision and the result, and leaves
    the error paths of a rejection uncompared.
    """
    if spec[0] in ("any", "union"):
        deep_branches = [
            branch for branch in spec[1] if _holds(("list", "dict"), branch)
        ]
        if len(deep_branches) > 1 and any(
            _holds(("list",), branch) for branch in deep_branches
        ):
            return True

    return any(
        _chooses_between_branches_with_a_list(child) for child in _children(spec)
    )


# The two documented deviations a generated schema can land on are switched off,
# so everything left is a region where a disagreement is a bug: ``Extra`` beside
# another variable key, and the ``float`` type against an ``int`` (ADR-017).
#
# The value is built from the spec. Random data rarely gets past a schema's first
# type check, and with it this test takes thousands of examples to notice a
# deviation that is switched back on, or never does.
@given(
    spec=strategies.specs(
        extra_beside_a_variable_key=False, float_type=False, markers=True
    ),
    random=st.randoms(use_true_random=False),
)
@settings(
    max_examples=3000, derandomize=True, suppress_health_check=[HealthCheck.too_slow]
)
def test_matches_voluptuous(spec: Any, random: Random) -> None:
    """probatio and voluptuous agree on acceptance, result, and error paths."""
    _assert_agrees_with_voluptuous(spec, strategies.fitting(spec, random))


@given(
    spec=strategies.specs(extra_beside_a_variable_key=False, markers=True),
    random=st.randoms(use_true_random=False),
)
@settings(
    max_examples=1500, derandomize=True, suppress_health_check=[HealthCheck.too_slow]
)
def test_float_schemas_match_voluptuous_on_everything_but_an_int(
    spec: Any, random: Random
) -> None:
    """With ``float`` in the schemas, the libraries agree on every value but an int.

    An ``int`` under a ``float`` schema is the one input ADR-017 changes, so the
    values here hold none, and the ``float`` type is still compared on the rest.
    """
    value = strategies.without_integers(strategies.fitting(spec, random))
    _assert_agrees_with_voluptuous(spec, value)


@given(spec=strategies.specs(markers=True), random=st.randoms(use_true_random=False))
@settings(
    max_examples=1500, derandomize=True, suppress_health_check=[HealthCheck.too_slow]
)
def test_engine_only_raises_invalid_for_a_fitting_value(
    spec: Any, random: Random
) -> None:
    """A value shaped like the schema never leaks a non-Invalid exception either."""
    with contextlib.suppress(probatio.Invalid):
        probatio.Schema(strategies.build(spec, probatio))(
            strategies.fitting(spec, random)
        )


@given(spec=strategies.specs(markers=True), value=strategies.data())
@settings(
    max_examples=400,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_engine_only_raises_invalid(spec: Any, value: Any) -> None:
    """Validation never leaks a non-Invalid exception, whatever the input."""
    with contextlib.suppress(probatio.Invalid):
        probatio.Schema(strategies.build(spec, probatio))(value)
