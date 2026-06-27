"""Snapshot tests for humanize_error (human-readable error rendering).

The rendered strings have no external oracle, so a snapshot of the output for a
catalog of failing validations guards the exact wording, path, and value
formatting against unintended drift.
"""

from __future__ import annotations

from typing import Any

import pytest

from probatio import (
    All,
    Coerce,
    Exclusive,
    In,
    Inclusive,
    Invalid,
    Range,
    Required,
    Schema,
)
from probatio.humanize import humanize_error


def _cases() -> dict[str, tuple[Any, Any]]:
    """A catalog of (schema, data) pairs that each fail validation."""
    return {
        "wrong_type": (Schema({"port": int}), {"port": "nope"}),
        "missing_required": (Schema({Required("name"): str}), {}),
        "extra_key": (Schema({"x": int}), {"x": 1, "y": 2}),
        "nested_path": (Schema({"a": {"b": int}}), {"a": {"b": "x"}}),
        "out_of_range": (
            Schema({"n": All(Coerce(int), Range(min=0, max=10))}),
            {"n": 99},
        ),
        "not_in": (Schema({"mode": In(["auto", "manual"])}), {"mode": "off"}),
        "multiple": (Schema({"a": int, "b": int}), {"a": "x", "b": "y"}),
        "list_index_path": (Schema({"ports": [int]}), {"ports": [80, "x"]}),
        "exclusive_group": (
            Schema({Exclusive("a", "g"): int, Exclusive("b", "g"): int}),
            {"a": 1, "b": 2},
        ),
        "inclusive_group": (
            Schema({Inclusive("a", "g"): int, Inclusive("b", "g"): int}),
            {"a": 1},
        ),
    }


@pytest.mark.parametrize("name", list(_cases()))
def test_humanize_error_snapshot(name: str, snapshot: Any) -> None:
    """Rendering each failing validation matches its snapshot."""
    schema, data = _cases()[name]
    with pytest.raises(Invalid) as caught:
        schema(data)
    assert humanize_error(data, caught.value) == snapshot
