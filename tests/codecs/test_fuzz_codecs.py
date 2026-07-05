"""Property-based differential fuzzing of ``to_field_list`` against its oracle.

``to_field_list`` is compared to voluptuous-serialize's ``convert`` on the same
generated schema built in each library. When the oracle itself raises (it has
bugs probatio does not), the example is skipped rather than counted against
probatio.

``to_openapi`` is no longer fuzzed against voluptuous-openapi: it now emits
correct OpenAPI even where the oracle is buggy, so a byte-for-byte comparison
fails on the oracle's own errors. Its property-based gate lives in
``test_openapi_oracle.py``, which validates the emitted document against the
``openapi-schema-validator`` reference implementation instead.
"""

from __future__ import annotations

from typing import Any

import voluptuous
import voluptuous_serialize
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

import probatio
from tests import strategies

# serialize works on a mapping of fields; keep the values to the leaf validators
# both it and voluptuous-serialize handle (no nested mappings or sequences).
_SERIALIZE_VALUES = st.one_of(
    st.sampled_from([int, str, bool, float]).map(lambda t: ("type", t)),
    st.lists(st.integers(min_value=-5, max_value=5), min_size=1, max_size=3).map(
        lambda xs: ("in", xs),
    ),
    st.tuples(
        st.integers(min_value=-10, max_value=0),
        st.integers(min_value=0, max_value=10),
    ).map(lambda mm: ("range", mm[0], mm[1])),
    st.tuples(
        st.integers(min_value=0, max_value=2),
        st.integers(min_value=2, max_value=5),
    ).map(lambda mm: ("length", mm[0], mm[1])),
    st.sampled_from([int, str, float]).map(lambda t: ("coerce", t)),
)
_SERIALIZE_FIELDS = st.dictionaries(
    st.text(min_size=1, max_size=3),
    st.tuples(st.sampled_from(["required", "optional"]), _SERIALIZE_VALUES),
    max_size=4,
)


@given(fields=_SERIALIZE_FIELDS)
@settings(
    max_examples=300, derandomize=True, suppress_health_check=[HealthCheck.too_slow]
)
def test_serialize_matches_oracle(fields: dict[str, Any]) -> None:
    """serialize matches voluptuous-serialize convert() on a generated mapping."""
    spec = ("dict", fields, None, None)
    try:
        expected = voluptuous_serialize.convert(
            voluptuous.Schema(strategies.build(spec, voluptuous)),
        )
    except Exception:  # noqa: BLE001
        assume(False)
        return
    actual = probatio.to_field_list(probatio.Schema(strategies.build(spec, probatio)))
    assert actual == expected
