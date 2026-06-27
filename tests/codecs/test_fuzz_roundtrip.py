"""Property-based tests for the JSON Schema codec (no external oracle).

JSON Schema is probatio's own dialect, so these are properties rather than a
differential: ``to_json_schema`` never crashes and always yields a dict;
``from_json_schema`` turns that back into a working validator; and the
encode/decode round trip reaches a *behavioral* fixed point. The first round trip
can be lossy (``Coerce(int)`` becomes a plain ``int`` check; JSON Schema "number"
decodes to an int-or-float validator), but once round-tripped, validating again
must not change which inputs are accepted or how they are normalized.
"""

from __future__ import annotations

from typing import Any

from hypothesis import HealthCheck, given, settings

import probatio
from tests import strategies


def _outcome(schema: Any, value: Any) -> Any:
    """Validate, reducing to a comparable ("ok", result) or ("err",)."""
    try:
        return ("ok", schema(value))
    except probatio.Invalid:
        return ("err",)


@given(spec=strategies.specs(), value=strategies.data())
@settings(
    max_examples=400, derandomize=True, suppress_health_check=[HealthCheck.too_slow]
)
def test_json_schema_roundtrip_is_stable_and_robust(spec: Any, value: Any) -> None:
    """to_json_schema/from_json_schema never crash and the round trip is stable."""
    schema = probatio.Schema(strategies.build(spec, probatio))

    first = probatio.to_json_schema(schema)
    assert isinstance(first, dict)

    once = probatio.from_json_schema(first)
    twice = probatio.from_json_schema(probatio.to_json_schema(once))

    # Both round-tripped schemas only ever raise Invalid, and they agree on the
    # outcome for the same input: the round trip has reached a behavioral fixpoint.
    assert _outcome(once, value) == _outcome(twice, value)
