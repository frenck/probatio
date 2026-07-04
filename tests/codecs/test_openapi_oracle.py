"""Behavioral oracle for ``to_openapi`` against the reference validator.

``to_openapi`` now emits correct OpenAPI even where it diverges from
voluptuous-openapi, so a byte-for-byte comparison is no longer the right gate.
These properties validate the emitted document against ``openapi-schema-validator``
(the reference implementation), in both OpenAPI 3.0 and 3.1:

- the document is a valid OpenAPI Schema Object (``check_schema``) and is
  serializable (``json.dumps``);
- it never rejects an input probatio accepts (no narrowing). Widening (the schema
  accepts what probatio rejects) is expected where OpenAPI cannot express a
  construct exactly, so the check is one-directional.

The no-narrowing check drops booleans and floats from the value battery: Python's
numeric equality (``0 == 0.0``, ``1 == True``) makes probatio's ``==`` accept a
cross-type number an ``enum`` encodes under the strict JSON type model, which
would read as a spurious narrowing.
"""

from __future__ import annotations

import json
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from openapi_schema_validator import OAS30Validator, OAS31Validator

import probatio
from tests import strategies

_VALIDATOR = {"3.0": OAS30Validator, "3.1.0": OAS31Validator}


def _probatio_accepts(schema: Any, value: Any) -> bool:
    """Whether the probatio schema accepts the value."""
    try:
        schema(value)
    except probatio.Invalid:
        return False
    return True


@given(spec=strategies.specs(), version=st.sampled_from(["3.0", "3.1.0"]))
@settings(
    max_examples=500, derandomize=True, suppress_health_check=[HealthCheck.too_slow]
)
def test_emitted_openapi_is_valid_and_serializable(spec: Any, version: str) -> None:
    """to_openapi always yields a serializable, valid OpenAPI Schema Object."""
    schema = probatio.Schema(strategies.build(spec, probatio))
    document = probatio.to_openapi(schema, openapi_version=version)

    json.dumps(document)
    _VALIDATOR[version].check_schema(document)


@given(
    spec=strategies.specs(no_narrowing=True),
    value=strategies.data(booleans=False, floats=False),
    version=st.sampled_from(["3.0", "3.1.0"]),
)
@settings(
    max_examples=800, derandomize=True, suppress_health_check=[HealthCheck.too_slow]
)
def test_emitted_openapi_never_narrows(spec: Any, value: Any, version: str) -> None:
    """The emitted schema never rejects an input probatio accepts (no narrowing)."""
    schema = probatio.Schema(strategies.build(spec, probatio))
    document = probatio.to_openapi(schema, openapi_version=version)

    if _probatio_accepts(schema, value):
        assert _VALIDATOR[version](document).is_valid(value), (
            f"emitted schema narrows: probatio accepts {value!r} but the "
            f"{version} schema {document!r} rejects it"
        )
