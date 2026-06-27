"""Tests for from_openapi() and the decoder extras: $ref, type arrays, nullable.

Behavioral: a schema is decoded, then the resulting Schema is run against valid
and invalid inputs. The OpenAPI extras (the 3.0 nullable keyword) and the shared
JSON Schema extras ($ref/$defs, type arrays, item-count bounds) are exercised here;
the mainline JSON Schema cases live in test_from_json_schema.
"""

from __future__ import annotations

import pytest

from probatio import (
    Invalid,
    MultipleInvalid,
    Schema,
    SchemaError,
    from_json_schema,
    from_openapi,
    to_openapi,
)


def test_nullable_accepts_none_and_value() -> None:
    """An OpenAPI 3.0 nullable value accepts both None and the base type."""
    schema = from_openapi({"type": "integer", "nullable": True})
    assert schema(3) == 3
    assert schema(None) is None
    with pytest.raises(Invalid):
        schema("nope")


def test_nullable_is_ignored_by_json_schema_decoder() -> None:
    """from_json_schema does not treat the OpenAPI nullable keyword specially."""
    schema = from_json_schema({"type": "integer", "nullable": True})
    assert schema(3) == 3
    with pytest.raises(Invalid):
        schema(None)


def test_nullable_object() -> None:
    """A nullable object accepts None or a valid object."""
    schema = from_openapi(
        {
            "type": "object",
            "properties": {"a": {"type": "integer"}},
            "required": ["a"],
            "nullable": True,
        },
    )
    assert schema({"a": 1}) == {"a": 1}
    assert schema(None) is None


@pytest.mark.parametrize(
    "node",
    [
        {"enum": [1, 2], "nullable": True},
        {"const": 5, "nullable": True},
        {"anyOf": [{"type": "integer"}, {"type": "string"}], "nullable": True},
        {"allOf": [{"type": "integer"}], "nullable": True},
    ],
)
def test_nullable_applies_to_combinator_nodes(node: dict[str, object]) -> None:
    """The OpenAPI nullable keyword also accepts None on enum/const/anyOf/allOf nodes."""
    assert from_openapi(node)(None) is None


def test_type_array_with_null() -> None:
    """A 3.1 type array like ["string", "null"] accepts each listed type."""
    schema = from_json_schema({"type": ["string", "null"]})
    assert schema("x") == "x"
    assert schema(None) is None
    with pytest.raises(Invalid):
        schema(5)


def test_array_item_count_bounds() -> None:
    """minItems and maxItems become a Length check on the array."""
    schema = from_json_schema(
        {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 2},
    )
    assert schema([1, 2]) == [1, 2]
    with pytest.raises(Invalid):
        schema([])
    with pytest.raises(Invalid):
        schema([1, 2, 3])


def test_date_time_format_becomes_datetime() -> None:
    """A string with format date-time decodes to a Datetime validator."""
    schema = from_openapi({"type": "string", "format": "date-time"})
    assert schema("2024-01-02T03:04:05.000000Z")
    with pytest.raises(Invalid):
        schema("not a datetime")


def test_array_item_bounds_without_items() -> None:
    """minItems/maxItems are enforced even when an array omits an items schema."""
    schema = from_json_schema({"type": "array", "minItems": 2})
    assert schema([1, "two", 3.0]) == [1, "two", 3.0]
    with pytest.raises(Invalid):
        schema([1])


def test_ref_into_array_index() -> None:
    """A $ref with an integer token resolves into a list (RFC 6901)."""
    schema = from_json_schema(
        {"$ref": "#/$defs/choices/0", "$defs": {"choices": [{"type": "integer"}]}},
    )
    assert schema(5) == 5
    with pytest.raises(Invalid):
        schema("x")


def test_ref_into_defs() -> None:
    """A $ref is resolved against $defs and validated like the referenced schema."""
    schema = from_json_schema(
        {
            "type": "object",
            "properties": {"port": {"$ref": "#/$defs/port"}},
            "required": ["port"],
            "$defs": {"port": {"type": "integer", "minimum": 1, "maximum": 65535}},
        },
    )
    assert schema({"port": 80}) == {"port": 80}
    with pytest.raises(MultipleInvalid):
        schema({"port": 0})


def test_ref_into_legacy_definitions() -> None:
    """A $ref into the older "definitions" section resolves too."""
    schema = from_json_schema(
        {
            "$ref": "#/definitions/name",
            "definitions": {"name": {"type": "string"}},
        },
    )
    assert schema("ada") == "ada"


def test_recursive_ref_becomes_recursive_validator() -> None:
    """A $ref that cycles back into a resolving schema becomes a recursive Self."""
    schema = from_json_schema(
        {
            "$ref": "#/$defs/node",
            "$defs": {
                "node": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "integer"},
                        "children": {
                            "type": "array",
                            "items": {"$ref": "#/$defs/node"},
                        },
                    },
                    "required": ["value"],
                },
            },
        },
    )
    tree = {"value": 1, "children": [{"value": 2}, {"value": 3, "children": []}]}
    assert schema(tree) == tree
    with pytest.raises(MultipleInvalid):
        schema({"value": 1, "children": [{"value": "nope"}]})


def test_recursive_ref_binds_to_the_node_not_the_root() -> None:
    """A recursive $ref reached from a property recurses into the node's shape.

    The node's shape differs from the root document, so a root-bound recursion
    (the earlier bug) would validate the wrong shape and reject valid data.
    """
    schema = from_json_schema(
        {
            "type": "object",
            "properties": {"tree": {"$ref": "#/$defs/node"}},
            "required": ["tree"],
            "$defs": {
                "node": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},
                        "kids": {"type": "array", "items": {"$ref": "#/$defs/node"}},
                    },
                    "required": ["tag"],
                },
            },
        },
    )
    data = {"tree": {"tag": "a", "kids": [{"tag": "b"}, {"tag": "c", "kids": []}]}}
    assert schema(data) == data
    with pytest.raises(MultipleInvalid):
        schema({"tree": {"tag": "a", "kids": [{"tag": 1}]}})


def test_unresolvable_ref_raises() -> None:
    """A $ref that points nowhere raises a clear error."""
    with pytest.raises(SchemaError, match="cannot resolve JSON pointer"):
        from_json_schema({"$ref": "#/$defs/missing"})


def test_non_local_ref_raises() -> None:
    """A non-local $ref (an external URL) is rejected."""
    with pytest.raises(SchemaError, match="only local JSON pointers"):
        from_json_schema({"$ref": "https://example.com/schema.json"})


def test_round_trip_through_to_openapi() -> None:
    """A schema survives a round trip through to_openapi and from_openapi."""
    source = from_json_schema(
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name"],
        },
    )
    rebuilt = from_openapi(to_openapi(source, openapi_version="3.1.0"))
    assert rebuilt({"name": "ada", "tags": ["x"]}) == {"name": "ada", "tags": ["x"]}
    with pytest.raises(MultipleInvalid):
        rebuilt({"tags": ["x"]})


def test_from_openapi_returns_schema() -> None:
    """from_openapi returns a Schema instance."""
    assert isinstance(from_openapi({"type": "string"}), Schema)
