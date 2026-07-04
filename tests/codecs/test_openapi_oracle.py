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

import pytest
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


@pytest.mark.parametrize("version", ["3.0", "3.1.0"])
def test_inclusive_group_agrees_with_the_reference_validator(version: str) -> None:
    """An Inclusive group emits valid OpenAPI the reference validator reads as all-or-none.

    The all-or-none constraint is spelled differently per version (dependentRequired
    on 3.1, a oneOf form on 3.0), so both are checked against the matching reference
    validator for validity and behavior.
    """
    document = probatio.to_openapi(
        probatio.Schema(
            {probatio.Inclusive("a", "g"): int, probatio.Inclusive("b", "g"): int},
        ),
        openapi_version=version,
    )
    validator_cls = _VALIDATOR[version]
    validator_cls.check_schema(document)
    validator = validator_cls(document)
    assert validator.is_valid({"a": 1, "b": 2})
    assert validator.is_valid({})
    assert not validator.is_valid({"a": 1})
    assert not validator.is_valid({"b": 2})


@pytest.mark.parametrize("version", ["3.0", "3.1.0"])
def test_required_alias_agrees_with_the_reference_validator(version: str) -> None:
    """A required Alias emits valid OpenAPI the reference validator reads as at-least-one."""
    from probatio.markers import Alias  # noqa: PLC0415

    document = probatio.to_openapi(
        probatio.Schema({Alias("name", "userName", required=True): str}),
        openapi_version=version,
    )
    validator_cls = _VALIDATOR[version]
    validator_cls.check_schema(document)
    validator = validator_cls(document)
    assert validator.is_valid({"name": "a"})
    assert validator.is_valid({"userName": "a"})
    assert not validator.is_valid({})


@pytest.mark.parametrize("version", ["3.0", "3.1.0"])
def test_exclusive_group_agrees_with_the_reference_validator(version: str) -> None:
    """An Exclusive group emits valid OpenAPI the reference validator reads as at-most-one."""
    document = probatio.to_openapi(
        probatio.Schema(
            {probatio.Exclusive("a", "e"): int, probatio.Exclusive("b", "e"): int},
        ),
        openapi_version=version,
    )
    validator_cls = _VALIDATOR[version]
    validator_cls.check_schema(document)
    validator = validator_cls(document)
    assert validator.is_valid({})
    assert validator.is_valid({"a": 1})
    assert validator.is_valid({"b": 2})
    assert not validator.is_valid({"a": 1, "b": 2})
