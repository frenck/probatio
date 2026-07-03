"""Differential tests for ``to_json_schema`` against the reference validator.

The round-trip fuzz (``test_fuzz_roundtrip``) checks a behavioral *fixpoint*, so
it is blind to a lossy *first* trip. These tests close that gap with an external
oracle: the ``jsonschema`` library. Two properties hold for every schema the
encoder produces:

- the emitted document is a valid, serializable JSON Schema (it never crashes
  ``json.dumps`` and passes ``Draft202012Validator.check_schema``);
- over the no-narrowing construct subset, the emitted schema never rejects an
  input probatio accepts (a narrowing is the failure mode that silently breaks a
  downstream consumer).

``format`` assertion is left off (the default), so an advisory ``format`` keyword
never rejects a value; probatio's format validators are stricter than the
advisory keyword, and enabling assertion could read as a spurious narrowing.
"""

from __future__ import annotations

import json
from typing import Any

import jsonschema
from hypothesis import HealthCheck, given, settings

import probatio
from tests import strategies

_VALIDATOR = jsonschema.Draft202012Validator


def _probatio_accepts(schema: Any, value: Any) -> bool:
    """Whether the probatio schema accepts the value."""
    try:
        schema(value)
    except probatio.Invalid:
        return False
    return True


def _jsonschema_accepts(document: dict[str, Any], value: Any) -> bool:
    """Whether the emitted JSON Schema accepts the value (format advisory)."""
    return _VALIDATOR(document).is_valid(value)


@given(spec=strategies.specs())
@settings(
    max_examples=400, derandomize=True, suppress_health_check=[HealthCheck.too_slow]
)
def test_emitted_schema_is_valid_and_serializable(spec: Any) -> None:
    """to_json_schema always yields a serializable, valid JSON Schema document."""
    schema = probatio.Schema(strategies.build(spec, probatio))
    document = probatio.to_json_schema(schema)

    # Must never crash a JSON encoder (a raw datetime/Decimal/Enum would).
    json.dumps(document)
    # Must be a valid Draft 2020-12 schema (a malformed emission would raise).
    _VALIDATOR.check_schema(document)


@given(spec=strategies.specs(no_narrowing=True), value=strategies.data(booleans=False))
@settings(
    max_examples=500, derandomize=True, suppress_health_check=[HealthCheck.too_slow]
)
def test_emitted_schema_never_narrows(spec: Any, value: Any) -> None:
    """The emitted schema never rejects an input probatio accepts."""
    # Widening (the emitted schema accepts what probatio rejects) is an expected,
    # documented consequence of the constructs JSON Schema cannot express
    # exactly, so the check is one-directional.
    schema = probatio.Schema(strategies.build(spec, probatio))
    document = probatio.to_json_schema(schema)

    if _probatio_accepts(schema, value):
        assert _jsonschema_accepts(document, value), (
            f"emitted schema narrows: probatio accepts {value!r} but the JSON "
            f"Schema {document!r} rejects it"
        )
