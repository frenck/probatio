"""Tests for from_json_schema(): building a Schema from a JSON Schema dict.

These are behavioral: a JSON Schema is converted, then the resulting Schema is
run against valid and invalid inputs. Building a validator that accepts the right
data matters more than the exact internal shape, so that is what is asserted.
"""

from __future__ import annotations

import pytest

from probatio import (
    Invalid,
    MultipleInvalid,
    Schema,
    from_json_schema,
    to_json_schema,
)
from probatio.error import SchemaError
from probatio.markers import Forbidden
from probatio.validators import (
    All,
    Base64,
    Contains,
    ExactSequence,
    Length,
    MultipleOf,
    Range,
    Unique,
)


def test_primitive_types() -> None:
    """Each primitive type converts to a validator accepting that type."""
    assert from_json_schema({"type": "string"})("x") == "x"
    assert from_json_schema({"type": "integer"})(3) == 3
    truthy = True
    assert from_json_schema({"type": "boolean"})(truthy) is True
    assert from_json_schema({"type": "null"})(None) is None


def test_number_accepts_int_and_float() -> None:
    """A JSON Schema number accepts both integers and floats."""
    schema = from_json_schema({"type": "number"})
    assert schema(3) == 3
    assert schema(3.5) == 3.5
    with pytest.raises(Invalid):
        schema("nope")


def test_no_type_accepts_anything() -> None:
    """A schema without a recognized type keyword accepts any value."""
    schema = from_json_schema({})
    assert schema("anything") == "anything"
    assert schema(42) == 42


def test_object_required_and_optional() -> None:
    """An object maps required and optional properties onto markers."""
    schema = from_json_schema(
        {
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
            "required": ["name"],
        },
    )

    assert schema({"name": "ada", "age": 36}) == {"name": "ada", "age": 36}
    assert schema({"name": "ada"}) == {"name": "ada"}
    with pytest.raises(MultipleInvalid):
        schema({"age": 36})


def test_object_rejects_extra_by_default() -> None:
    """A closed object rejects keys not present in properties."""
    schema = from_json_schema(
        {"type": "object", "properties": {"a": {"type": "integer"}}},
    )
    with pytest.raises(MultipleInvalid):
        schema({"a": 1, "b": 2})


def test_object_additional_properties_true_allows_extra() -> None:
    """additionalProperties: true allows unknown keys through unchanged."""
    schema = from_json_schema(
        {
            "type": "object",
            "properties": {"a": {"type": "integer"}},
            "additionalProperties": True,
        },
    )
    assert schema({"a": 1, "b": "anything"}) == {"a": 1, "b": "anything"}


def test_object_additional_properties_schema_validates_extra() -> None:
    """additionalProperties as a schema validates the extra values."""
    schema = from_json_schema(
        {
            "type": "object",
            "properties": {"a": {"type": "integer"}},
            "additionalProperties": {"type": "string"},
        },
    )

    assert schema({"a": 1, "b": "text"}) == {"a": 1, "b": "text"}
    with pytest.raises(MultipleInvalid):
        schema({"a": 1, "b": 2})


def test_object_default_is_applied() -> None:
    """A property default is applied when the key is absent."""
    schema = from_json_schema(
        {
            "type": "object",
            "properties": {"port": {"type": "integer", "default": 8080}},
        },
    )
    assert schema({}) == {"port": 8080}


def test_array_single_item_schema() -> None:
    """An array with one item schema validates every element against it."""
    schema = from_json_schema({"type": "array", "items": {"type": "integer"}})
    assert schema([1, 2, 3]) == [1, 2, 3]
    with pytest.raises(MultipleInvalid):
        schema([1, "two"])


def test_array_without_items_is_any_list() -> None:
    """An array without items accepts any list."""
    schema = from_json_schema({"type": "array"})
    assert schema([1, "two", None]) == [1, "two", None]


def test_array_items_anyof() -> None:
    """An array whose items are an anyOf accepts each listed type."""
    schema = from_json_schema(
        {
            "type": "array",
            "items": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
        },
    )
    assert schema([1, "two", 3]) == [1, "two", 3]


def test_enum_and_const() -> None:
    """enum becomes a membership check and const a literal match."""
    enum_schema = from_json_schema({"enum": ["a", "b"]})
    assert enum_schema("a") == "a"
    with pytest.raises(Invalid):
        enum_schema("c")

    const_schema = from_json_schema({"const": "on"})
    assert const_schema("on") == "on"
    with pytest.raises(Invalid):
        const_schema("off")


def test_anyof_and_allof() -> None:
    """anyOf accepts any branch; allOf requires all branches."""
    any_schema = from_json_schema({"anyOf": [{"type": "integer"}, {"type": "string"}]})
    assert any_schema(1) == 1
    assert any_schema("x") == "x"

    all_schema = from_json_schema(
        {"allOf": [{"type": "string"}, {"type": "string", "minLength": 2}]},
    )

    assert all_schema("ok") == "ok"
    with pytest.raises(Invalid):
        all_schema("x")


def test_string_length_and_pattern() -> None:
    """String minLength/maxLength and pattern become Length and Match checks."""
    schema = from_json_schema(
        {"type": "string", "minLength": 2, "maxLength": 4, "pattern": r"^[a-z]+$"},
    )

    assert schema("abc") == "abc"
    with pytest.raises(Invalid):
        schema("a")
    with pytest.raises(Invalid):
        schema("toolong")
    with pytest.raises(Invalid):
        schema("AB")


def test_string_format_email_and_uri() -> None:
    """String format email and uri map onto the Email and Url validators."""
    email = from_json_schema({"type": "string", "format": "email"})
    assert email("a@example.com") == "a@example.com"
    with pytest.raises(Invalid):
        email("not-an-email")

    uri = from_json_schema({"type": "string", "format": "uri"})
    assert uri("https://example.com") == "https://example.com"


def test_number_bounds_inclusive_and_exclusive() -> None:
    """minimum/maximum are inclusive and exclusiveMinimum/Maximum are not."""
    inclusive = from_json_schema({"type": "integer", "minimum": 1, "maximum": 10})
    assert inclusive(1) == 1
    assert inclusive(10) == 10
    with pytest.raises(Invalid):
        inclusive(0)

    exclusive = from_json_schema(
        {"type": "integer", "exclusiveMinimum": 1, "exclusiveMaximum": 10},
    )

    assert exclusive(2) == 2
    with pytest.raises(Invalid):
        exclusive(1)
    with pytest.raises(Invalid):
        exclusive(10)


def test_non_dict_node_raises() -> None:
    """A non-object, non-boolean JSON Schema node is rejected with a SchemaError."""
    with pytest.raises(SchemaError, match="must be an object or boolean"):
        from_json_schema({"anyOf": ["nope"]})


def test_round_trips_through_to_json_schema() -> None:
    """A mapping survives a round trip through to_json_schema and back."""
    original = Schema(
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "port": {"type": "integer", "minimum": 1, "maximum": 65535},
            },
            "required": ["name"],
        },
    )
    rebuilt = from_json_schema(to_json_schema(from_json_schema(original.schema)))

    assert rebuilt({"name": "ada", "port": 80}) == {"name": "ada", "port": 80}
    with pytest.raises(MultipleInvalid):
        rebuilt({"port": 80})


def test_missing_required_reports_its_path() -> None:
    """A decoded object schema reports a missing required key at its path."""
    schema = from_json_schema(
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    )

    with pytest.raises(MultipleInvalid) as caught:
        schema({})

    assert caught.value.errors[0].path == ["name"]


def test_extra_key_reports_its_path() -> None:
    """A decoded closed object reports an unexpected key at that key's path."""
    schema = from_json_schema(
        {
            "type": "object",
            "properties": {"a": {"type": "integer"}},
            "additionalProperties": False,
        },
    )

    with pytest.raises(MultipleInvalid) as caught:
        schema({"a": 1, "extra": 2})

    assert caught.value.errors[0].path == ["extra"]


def test_array_item_reports_its_index() -> None:
    """A decoded array reports a bad item at its index in the path."""
    schema = from_json_schema({"type": "array", "items": {"type": "integer"}})
    with pytest.raises(MultipleInvalid) as caught:
        schema([1, "nope", 3])
    assert caught.value.errors[0].path == [1]


def test_additional_properties_schema_reports_the_key_path() -> None:
    """A failing additionalProperties value is reported at its key's path."""
    schema = from_json_schema(
        {
            "type": "object",
            "properties": {},
            "additionalProperties": {"type": "integer"},
        },
    )

    with pytest.raises(MultipleInvalid) as caught:
        schema({"x": "not an int"})

    assert caught.value.errors[0].path == ["x"]


def test_recursive_ref_reports_a_nested_path() -> None:
    """A recursive $ref reports a deep failure with the full nested path."""
    schema = from_json_schema(
        {
            "$ref": "#/$defs/node",
            "$defs": {
                "node": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "integer"},
                        "next": {"$ref": "#/$defs/node"},
                    },
                },
            },
        },
    )

    with pytest.raises(MultipleInvalid) as caught:
        schema({"value": 1, "next": {"value": "bad"}})

    assert caught.value.errors[0].path == ["next", "value"]


def test_root_ref_resolves_to_the_whole_document() -> None:
    """A bare ``#`` references the document root, the recursive-schema idiom."""
    schema = from_json_schema(
        {
            "type": "object",
            "properties": {
                "value": {"type": "integer"},
                "children": {"type": "array", "items": {"$ref": "#"}},
            },
        },
    )

    assert schema({"value": 1, "children": [{"value": 2, "children": []}]}) == {
        "value": 1,
        "children": [{"value": 2, "children": []}],
    }
    with pytest.raises(MultipleInvalid) as caught:
        schema({"value": 1, "children": [{"value": "bad", "children": []}]})

    assert caught.value.errors[0].path == ["children", 0, "value"]


@pytest.mark.parametrize(
    ("json_format", "valid", "invalid"),
    [
        ("ipv4", "192.0.2.1", "not-an-ip"),
        ("ipv6", "::1", "192.0.2.1"),
        ("uuid", "12345678-1234-5678-1234-567812345678", "nope"),
        ("hostname", "host.example.com", "-bad"),
        ("date", "2026-06-25", "2026-13-99"),
        ("time", "14:30:00", "99:99:99"),
    ],
)
def test_string_format_decodes_to_a_validator(
    json_format: str,
    valid: str,
    invalid: str,
) -> None:
    """A string format decodes to the matching validator (accept/reject)."""
    schema = from_json_schema({"type": "string", "format": json_format})
    schema(valid)  # accepted
    with pytest.raises(MultipleInvalid):
        schema(invalid)


def test_multiple_of_decodes() -> None:
    """A multipleOf keyword decodes to a MultipleOf check."""
    schema = from_json_schema({"type": "integer", "multipleOf": 3})
    assert schema(9) == 9
    with pytest.raises(MultipleInvalid):
        schema(7)


def test_write_only_decodes_to_secret() -> None:
    """A writeOnly string decodes to a Secret, so the value is masked."""
    schema = from_json_schema({"type": "string", "writeOnly": True})
    result = schema("token")
    assert "token" not in repr(result)
    assert result.get_secret_value() == "token"


def test_non_dict_properties_is_a_clean_schema_error() -> None:
    """A malformed 'properties' (not an object) is refused, not leaked as AttributeError."""
    with pytest.raises(SchemaError, match="properties"):
        from_json_schema({"type": "object", "properties": [1, 2]})


def test_non_list_required_is_a_clean_schema_error() -> None:
    """A malformed 'required' (not an array) is refused with a clean SchemaError."""
    with pytest.raises(SchemaError, match="required"):
        from_json_schema({"type": "object", "required": "name"})


@pytest.mark.parametrize("entry", [1, ["a"], {"a": 1}])
def test_non_string_required_entry_is_a_clean_schema_error(entry: object) -> None:
    """A non-string 'required' entry is refused, not silently ignored.

    A number or nested value never matches a property name, so honoring it would
    quietly turn a required field into an optional one.
    """
    node = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": [entry],
    }
    with pytest.raises(SchemaError, match="required"):
        from_json_schema(node)


@pytest.mark.parametrize("key", ["minItems", "maxItems"])
def test_negative_item_count_is_a_clean_schema_error(key: str) -> None:
    """A negative item-count keyword is refused; the JSON Schema counts are >= 0."""
    with pytest.raises(SchemaError, match=key):
        from_json_schema({"type": "array", key: -1})


def test_non_string_type_array_entry_is_a_clean_schema_error() -> None:
    """A non-string entry in a 'type' array is refused rather than widening.

    A ``null`` entry would become a ``type`` of None and fall through to an
    accept-anything schema, silently widening validation; refuse it instead.
    """
    with pytest.raises(SchemaError, match="type"):
        from_json_schema({"type": [None]})


def test_type_array_decodes_to_a_union() -> None:
    """A valid 'type' array decodes to an Any of each named type, including null."""
    schema = from_json_schema({"type": ["string", "null"]})
    assert schema("x") == "x"
    assert schema(None) is None
    with pytest.raises(MultipleInvalid):
        schema(123)


def test_prefix_items_round_trips_an_exact_sequence() -> None:
    """An ExactSequence encodes to prefixItems and decodes back to a tuple schema."""
    schema = from_json_schema(to_json_schema(Schema(ExactSequence([int, str]))))
    assert schema([1, "a"]) == [1, "a"]
    with pytest.raises(MultipleInvalid):
        schema([1, 2])


def test_bool_items_decodes_without_leaking() -> None:
    """A bool 'items' (false/true) carries no per-item schema and is handled."""
    assert from_json_schema({"type": "array", "items": False})([1, "x"]) == [1, "x"]


def test_non_list_prefix_items_is_a_clean_schema_error() -> None:
    """A malformed 'prefixItems' (not an array) is refused with a clean SchemaError."""
    with pytest.raises(SchemaError, match="prefixItems"):
        from_json_schema({"type": "array", "prefixItems": {"type": "integer"}})


@pytest.mark.parametrize(
    "node",
    [
        {"type": "array", "prefixItems": [{"type": "string"}]},  # open tail
        {  # typed tail
            "type": "array",
            "prefixItems": [{"type": "string"}],
            "items": {"type": "integer"},
        },
        {"type": "array", "prefixItems": [{"type": "string"}], "items": True},
    ],
)
def test_prefix_items_open_tail_is_a_clean_schema_error(
    node: dict[str, object],
) -> None:
    """prefixItems with an open or typed tail is refused, not mapped to a fixed length.

    Only the closed form (``items: false``) maps to an ``ExactSequence``. Without it,
    JSON Schema allows items beyond the prefix, so decoding to a fixed-length tuple
    would wrongly reject a valid array; refuse it with a clean SchemaError instead.
    """
    with pytest.raises(SchemaError, match="prefixItems"):
        from_json_schema(node)


@pytest.mark.parametrize(
    "validator",
    [Unique(), Contains(1), MultipleOf(2), Range(min=1), Length(min=2)],
)
def test_typeless_constraint_round_trips(validator: object) -> None:
    """A typeless constraint encodes and decodes back into an enforcing validator."""
    schema = from_json_schema(to_json_schema(Schema(validator)))
    # Each must still reject a value that violates the constraint after the trip.
    bad = {
        "Unique": [1, 1],
        "Contains": [2, 3],
        "MultipleOf": 3,
        "Range": 0,
        "Length": "",
    }[type(validator).__name__]
    with pytest.raises(Invalid):
        schema(bad)


def test_typeless_multiple_constraints_combine() -> None:
    """A typeless schema with several constraints enforces all of them."""
    schema = from_json_schema({"minimum": 1, "multipleOf": 2})
    assert schema(4) == 4
    with pytest.raises(Invalid):
        schema(3)  # not a multiple of 2
    with pytest.raises(Invalid):
        schema(0)  # below the minimum


def test_typeless_pattern_constrains_strings() -> None:
    """A typeless schema with only a pattern still enforces the pattern."""
    schema = from_json_schema({"pattern": "^a+$"})
    assert schema("aaa") == "aaa"
    with pytest.raises(Invalid):
        schema("bbb")


def test_base64_round_trips_via_content_encoding() -> None:
    """Base64 encodes to contentEncoding and decodes back into an enforcing Base64."""
    schema = from_json_schema(to_json_schema(Schema(Base64())))
    assert schema("aGVsbG8=") == "aGVsbG8="
    with pytest.raises(Invalid):
        schema("!!! not base64 @@@")


def test_boolean_schema_true_accepts_anything() -> None:
    """A ``true`` schema accepts any value."""
    assert from_json_schema(True)({"any": "thing"}) == {"any": "thing"}


def test_boolean_schema_false_rejects_everything() -> None:
    """A ``false`` schema rejects every value."""
    with pytest.raises(Invalid):
        from_json_schema(False)(1)


def test_forbidden_property_round_trips() -> None:
    """A Forbidden key encodes to a ``false`` property and decodes back to Forbidden."""
    schema = from_json_schema(
        to_json_schema(Schema({Forbidden("x"): object, "y": int})),
    )
    assert schema({"y": 1}) == {"y": 1}
    with pytest.raises(Invalid):
        schema({"x": 1, "y": 1})


def test_positional_items_list_is_a_clean_schema_error() -> None:
    """The Draft-4 positional ``items`` list form is refused with a clean SchemaError."""
    with pytest.raises(SchemaError, match="prefixItems"):
        from_json_schema({"type": "array", "items": [{"type": "integer"}]})


def test_non_integer_item_count_is_a_clean_schema_error() -> None:
    """A non-integer minItems/maxItems is refused at decode, not leaked at validation."""
    with pytest.raises(SchemaError, match="minItems"):
        from_json_schema({"type": "array", "minItems": "3"})


@pytest.mark.parametrize("keyword", ["anyOf", "allOf", "enum"])
def test_non_array_combinator_is_a_clean_schema_error(keyword: str) -> None:
    """A non-array anyOf/allOf/enum is refused with a clean SchemaError."""
    with pytest.raises(SchemaError, match=keyword):
        from_json_schema({keyword: {"not": "an array"}})


def test_const_non_scalar_is_an_equality_check() -> None:
    """A const list or dict matches only that exact value, not a sub-schema."""
    list_schema = from_json_schema({"const": [1, 2]})
    assert list_schema([1, 2]) == [1, 2]
    for bad in ([2, 1], [1], []):
        with pytest.raises(Invalid):
            list_schema(bad)

    dict_schema = from_json_schema({"const": {"a": 1}})
    assert dict_schema({"a": 1}) == {"a": 1}
    with pytest.raises(Invalid):
        dict_schema({})


def test_one_of_decodes_with_exact_one_semantics() -> None:
    """oneOf accepts a value matching exactly one branch, not zero and not several."""
    schema = from_json_schema({"oneOf": [{"type": "integer"}, {"type": "string"}]})
    assert schema(1) == 1
    assert schema("a") == "a"
    with pytest.raises(Invalid):
        schema(1.5)  # matches neither branch


def test_one_of_rejects_a_value_matching_multiple_branches() -> None:
    """A value matching two oneOf branches is rejected, where anyOf would accept it."""
    schema = from_json_schema(
        {"oneOf": [{"type": "number", "minimum": 0}, {"type": "number", "maximum": 10}]}
    )
    assert schema(-1) == -1  # only the maximum branch
    assert schema(11) == 11  # only the minimum branch
    with pytest.raises(Invalid):
        schema(5)  # matches both branches


def test_one_of_must_be_an_array() -> None:
    """A non-array oneOf is a schema definition error."""
    from probatio import SchemaError  # noqa: PLC0415

    with pytest.raises(SchemaError, match="oneOf"):
        from_json_schema({"oneOf": {"type": "integer"}})


def test_unevaluated_keywords_fail_closed() -> None:
    """unevaluatedProperties/Items are restrictive and unhandled, so refused."""
    from probatio import SchemaError  # noqa: PLC0415

    for keyword in ("unevaluatedProperties", "unevaluatedItems"):
        with pytest.raises(SchemaError, match="not supported"):
            from_json_schema({"type": "object", keyword: False})


def test_not_decodes_to_a_negation() -> None:
    """not accepts a value only when the inner schema rejects it."""
    schema = from_json_schema({"not": {"type": "string"}})
    assert schema(1) == 1
    with pytest.raises(Invalid):
        schema("x")


def test_format_byte_decodes_to_base64() -> None:
    """The OpenAPI 'byte' format maps to Base64, like contentEncoding base64."""
    schema = from_json_schema({"type": "string", "format": "byte"})
    assert schema("aGVsbG8=") == "aGVsbG8="
    with pytest.raises(Invalid):
        schema("!!! not base64 !!!")


@pytest.mark.parametrize(
    "node",
    [
        {"patternProperties": {"^x": {"type": "integer"}}},
        {"propertyNames": {"maxLength": 3}},
        {"dependentRequired": {"a": ["b"]}},
        {"dependentSchemas": {"a": {"type": "object"}}},
        {"if": {"type": "string"}, "then": {"minLength": 1}},
    ],
)
def test_unsupported_keyword_fails_closed(node: dict[str, object]) -> None:
    """A restrictive keyword probatio cannot honor is refused, not silently dropped."""
    with pytest.raises(SchemaError, match="not supported"):
        from_json_schema(node)


def test_exclusive_and_inclusive_bounds_keep_the_tighter_one() -> None:
    """When minimum and exclusiveMinimum are both present, the tighter bound wins."""
    schema = from_json_schema(
        {"type": "integer", "minimum": 1, "exclusiveMinimum": 5},
    )
    assert schema(6) == 6
    for bad in (3, 5, 1):
        with pytest.raises(Invalid):
            schema(bad)


def test_draft4_exclusive_minimum_boolean() -> None:
    """The Draft-04 boolean exclusiveMinimum flips minimum to exclusive."""
    schema = from_json_schema(
        {"type": "integer", "minimum": 5, "exclusiveMinimum": True},
    )
    assert schema(6) == 6
    with pytest.raises(Invalid):
        schema(5)


def test_bare_object_accepts_any_object() -> None:
    """{"type": "object"} with no properties accepts any object, not only an empty one."""
    schema = from_json_schema({"type": "object"})
    assert schema({"a": 1}) == {"a": 1}
    assert schema({}) == {}
    with pytest.raises(Invalid):
        schema([1])


def test_explicit_closed_empty_object() -> None:
    """additionalProperties:false with no properties stays a closed (empty-only) object."""
    schema = from_json_schema({"type": "object", "additionalProperties": False})
    assert schema({}) == {}
    with pytest.raises(Invalid):
        schema({"a": 1})


def test_min_and_max_properties() -> None:
    """minProperties/maxProperties bound the number of keys."""
    schema = from_json_schema(
        {
            "type": "object",
            "minProperties": 1,
            "maxProperties": 2,
            "additionalProperties": True,
        },
    )

    assert schema({"a": 1}) == {"a": 1}
    with pytest.raises(Invalid):
        schema({})
    with pytest.raises(Invalid):
        schema({"a": 1, "b": 2, "c": 3})


def test_contains_under_array_type() -> None:
    """contains is honored under an explicit array type, not only typeless."""
    schema = from_json_schema({"type": "array", "contains": {"const": 5}})
    assert schema([1, 5, 2]) == [1, 5, 2]
    with pytest.raises(Invalid):
        schema([1, 2])


def test_min_and_max_contains() -> None:
    """minContains/maxContains bound how many items must match contains."""
    schema = from_json_schema(
        {"type": "array", "contains": {"const": 5}, "minContains": 2, "maxContains": 3},
    )

    assert schema([5, 5]) == [5, 5]
    assert schema([5, 5, 5, 1]) == [5, 5, 5, 1]
    with pytest.raises(Invalid):
        schema([5, 1])  # only one match, below minContains
    with pytest.raises(Invalid):
        schema([5, 5, 5, 5])  # four matches, above maxContains


def test_contains_count_on_a_non_collection() -> None:
    """A counted contains on a non-iterable is refused cleanly, not leaked."""
    # Typeless so the count validator (not a list-type guard) sees the raw value.
    schema = from_json_schema({"contains": {"const": 5}, "minContains": 1})
    with pytest.raises(Invalid):
        schema(5)


def test_max_and_exclusive_maximum_keep_the_tighter_one() -> None:
    """When maximum and exclusiveMaximum are both present, the tighter bound wins."""
    schema = from_json_schema(
        {"type": "integer", "maximum": 10, "exclusiveMaximum": 5},
    )
    assert schema(4) == 4
    for bad in (5, 6, 10):
        with pytest.raises(Invalid):
            schema(bad)


def test_not_and_contains_count_repr_readably() -> None:
    """The internal not/contains-count validators repr readably for error paths."""
    not_schema = from_json_schema({"not": {"type": "string"}})
    assert "Not(" in repr(not_schema.schema)
    count_schema = from_json_schema({"contains": {"const": 5}, "minContains": 2})
    assert "ContainsCount(" in repr(count_schema.schema)


@pytest.mark.parametrize(
    "node",
    [
        {"type": {"a": 1}},  # an unhashable type value
        {"type": 5},  # a non-string, non-array type
        {"$ref": 269},  # a non-string $ref
        {"type": "integer", "minimum": {"a": 1}},  # a non-numeric bound
        {"type": "integer", "minimum": 1, "exclusiveMinimum": {"a": 1}},
        {"multipleOf": {"a": 1}},  # a non-numeric multipleOf
        {"type": "string", "minLength": {"a": 1}},  # a non-integer length bound
        {"pattern": "?]["},  # not a valid regular expression
    ],
)
def test_malformed_keyword_values_fail_closed(node: dict[str, object]) -> None:
    """A keyword carrying a wrong-typed or malformed value is refused, not leaked.

    These cases were found by the fuzz harness: each previously leaked a raw
    TypeError, AttributeError, or re.error out of the untrusted decode path.
    """
    with pytest.raises(SchemaError):
        from_json_schema(node)


def test_non_string_format_is_ignored_not_a_leak() -> None:
    """A malformed (non-string) ``format`` is treated as absent, not a TypeError.

    ``_FROM_FORMATS.get(<dict>)`` would raise ``unhashable type``; the decoder
    treats the bad hint as no format and still decodes a plain string. Found by the
    atheris fuzz harness.
    """
    schema = from_json_schema({"type": "string", "format": {}})
    assert schema("hello") == "hello"


def test_structurally_malformed_schema_fails_closed() -> None:
    """A malformed untrusted schema raises SchemaError, never a leaked TypeError.

    Exhaustively type-checking every field is impractical, so the decoder fails
    closed: a structural mismatch a specific check did not catch (a bool where an
    array is expected) becomes a clean SchemaError. Found by the atheris fuzz
    harness.
    """
    with pytest.raises(SchemaError, match="malformed"):
        from_json_schema({"type": "array", "items": {"anyOf": True}})


def test_plain_contains_matches_a_subschema_not_membership() -> None:
    """Plain ``contains`` requires an element matching the subschema, not equality.

    JSON Schema ``contains`` is satisfied when at least one element validates
    against the subschema, so ``{"contains": {"type": "integer"}}`` accepts a list
    that holds any integer. Decoding it to probatio's ``Contains`` (a literal
    membership test) would wrongly reject such a list.
    """
    schema = from_json_schema({"contains": {"type": "integer"}})
    assert schema(["a", 1]) == ["a", 1]
    with pytest.raises(Invalid):
        schema(["a", "b"])


def test_allof_keeps_a_sibling_constraint() -> None:
    """A keyword beside ``allOf`` is enforced too, not dropped (fail closed)."""
    schema = from_json_schema({"allOf": [{"type": "integer"}], "minimum": 5})
    assert schema(7) == 7
    with pytest.raises(Invalid):
        schema(3)  # below the sibling minimum


def test_not_keeps_a_sibling_constraint() -> None:
    """A keyword beside ``not`` is enforced too, not dropped (fail closed)."""
    schema = from_json_schema({"not": {"type": "string"}, "minimum": 5})
    assert schema(7) == 7
    with pytest.raises(Invalid):
        schema(3)  # below the sibling minimum


def test_anyof_keeps_a_sibling_type() -> None:
    """A ``type`` beside ``anyOf`` is enforced too, not dropped (fail closed)."""
    schema = from_json_schema(
        {"anyOf": [{"minimum": 0}, {"minimum": 100}], "type": "integer"},
    )
    assert schema(5) == 5
    with pytest.raises(Invalid):
        schema("5")  # the sibling type rejects a string


def test_unique_items_under_array_type() -> None:
    """uniqueItems is honored under an explicit array type, not only typeless."""
    schema = from_json_schema({"type": "array", "uniqueItems": True})
    assert schema([1, 2]) == [1, 2]
    with pytest.raises(Invalid):
        schema([1, 1])


def test_unique_array_round_trips_through_the_codec() -> None:
    """All([int], Unique()) survives encode then decode and still rejects duplicates."""
    schema = from_json_schema(to_json_schema(Schema(All([int], Unique()))))
    assert schema([1, 2]) == [1, 2]
    with pytest.raises(Invalid):
        schema([1, 1])


def test_array_length_round_trips_as_item_count() -> None:
    """An array length encodes as minItems/maxItems and decodes back enforcing it."""
    schema = from_json_schema(to_json_schema(Schema(All([int], Length(min=2)))))
    assert schema([1, 2]) == [1, 2]
    with pytest.raises(Invalid):
        schema([1])  # below the array length


def test_unrecognized_type_accepts_anything() -> None:
    """An unknown ``type`` value is ignored, leaving an accept-anything schema."""
    schema = from_json_schema({"type": "nonsense"})
    assert schema("x") == "x"
    assert schema(5) == 5


def test_unrecognized_type_still_honors_a_constraint() -> None:
    """An unknown ``type`` does not swallow a sibling constraint keyword."""
    schema = from_json_schema({"type": "nonsense", "minimum": 5})
    assert schema(7) == 7
    with pytest.raises(Invalid):
        schema(3)  # the sibling minimum still applies


def test_object_length_round_trips_as_property_count() -> None:
    """An object length encodes as min/maxProperties and decodes back enforcing it."""
    source = {"type": "object", "additionalProperties": True, "minProperties": 2}
    schema = from_json_schema(to_json_schema(from_json_schema(source)))
    assert schema({"a": 1, "b": 2}) == {"a": 1, "b": 2}
    with pytest.raises(Invalid):
        schema({"a": 1})  # below the property count
