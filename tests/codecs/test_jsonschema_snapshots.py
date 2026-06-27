"""Snapshot tests for to_json_schema (probatio's own JSON Schema dialect).

JSON Schema output has no external oracle, so a snapshot of the full rendered
dictionary for a broad catalog guards against any unintended change to the shape,
complementing the targeted assertions in test_jsonschema.
"""

from __future__ import annotations

from typing import Any

import pytest

from probatio import (
    ALLOW_EXTRA,
    All,
    Boolean,
    Coerce,
    Email,
    FqdnUrl,
    In,
    Length,
    Lower,
    Match,
    Maybe,
    Optional,
    Range,
    Remove,
    Required,
    Schema,
    Url,
    to_json_schema,
)
from probatio import (
    Any as AnyValidator,
)

CATALOG: dict[str, Any] = {
    "primitives": Schema({"i": int, "s": str, "f": float, "b": bool, "n": None}),
    "markers": Schema(
        {
            Required("name"): str,
            Optional("port", default=8080): int,
            Optional("note", description="a note"): str,
            Remove("legacy"): str,
        },
    ),
    "extra_and_type_keys": Schema({str: int, "fixed": bool}, extra=ALLOW_EXTRA),
    "sequence_single": Schema([int]),
    "sequence_multi": Schema([int, str]),
    "membership": Schema(In(["a", "b", "c"])),
    "range_inclusive": Schema(Range(min=0, max=10)),
    "range_exclusive": Schema(
        Range(min=0, max=10, min_included=False, max_included=False)
    ),
    "range_one_sided": Schema(Range(max=5)),
    "length": Schema(Length(min=1, max=20)),
    "match": Schema(Match(r"^\d+$")),
    "coerce": Schema(All(Coerce(int), Range(min=0))),
    "any_of": Schema(AnyValidator(int, str)),
    "maybe": Schema(Maybe(int)),
    "named": Schema({"flag": Boolean(), "mail": Email, "site": Url, "host": FqdnUrl}),
    "string_func": Schema(Lower),
    "literal": Schema("on"),
    "nested": Schema({Required("outer"): {Required("inner"): int}}),
}


@pytest.mark.parametrize("name", list(CATALOG))
def test_to_json_schema_snapshot(name: str, snapshot: Any) -> None:
    """The rendered JSON Schema for each catalog entry matches its snapshot."""
    assert to_json_schema(CATALOG[name]) == snapshot
