"""Property-based differential fuzzing of the codecs against their oracles.

``to_openapi`` is compared to voluptuous-openapi's ``convert`` (both OpenAPI
versions) and ``serialize`` to voluptuous-serialize's ``convert``, on the same
generated schema built in each library. When the oracle itself raises (it has
bugs probatio does not, like crashing on a multi-item array), the example is
skipped rather than counted against probatio.
"""

from __future__ import annotations

from typing import Any

import voluptuous
import voluptuous_openapi
import voluptuous_serialize
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from voluptuous_openapi import OpenApiVersion

import probatio
from tests import strategies

_ORACLE_VERSION = {"3.0": OpenApiVersion.V3, "3.1.0": OpenApiVersion.V3_1}

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


@given(spec=strategies.specs(), version=st.sampled_from(["3.0", "3.1.0"]))
@settings(
    max_examples=400, derandomize=True, suppress_health_check=[HealthCheck.too_slow]
)
def test_to_openapi_matches_oracle(spec: Any, version: str) -> None:
    """to_openapi matches voluptuous-openapi convert() on a generated schema."""
    try:
        expected = voluptuous_openapi.convert(
            voluptuous.Schema(strategies.build(spec, voluptuous)),
            openapi_version=_ORACLE_VERSION[version],
        )
    except Exception:  # noqa: BLE001
        assume(False)
        return
    actual = probatio.to_openapi(
        probatio.Schema(strategies.build(spec, probatio)),
        openapi_version=version,
    )
    assert actual == expected


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
    actual = probatio.serialize(probatio.Schema(strategies.build(spec, probatio)))
    assert actual == expected
