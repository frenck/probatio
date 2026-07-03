"""Tests for JSON Schema export."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from probatio import (
    ALLOW_EXTRA,
    ASCII,
    REMOVE_EXTRA,
    UUID,
    All,
    Alpha,
    Any,
    AsDate,
    AsDatetime,
    AsTime,
    Base64,
    Boolean,
    ByteLength,
    Coerce,
    Contains,
    Date,
    Datetime,
    Email,
    Equal,
    ExactSequence,
    Extra,
    Fqdn,
    FqdnUrl,
    FromEpoch,
    Hostname,
    In,
    IPAddress,
    IPNetwork,
    IPv4Address,
    IPv6Address,
    Length,
    Literal,
    Lower,
    MacAddress,
    Match,
    Maybe,
    MultipleOf,
    NotIn,
    Optional,
    Percentage,
    Port,
    Range,
    Remove,
    Required,
    Schema,
    Secret,
    Slug,
    Time,
    TimeZone,
    TimeZoneInfo,
    Unique,
    Url,
)
from probatio.codecs.jsonschema import from_json_schema, to_json_schema


def test_primitive_types() -> None:
    """Python types map to JSON Schema types."""
    assert to_json_schema(Schema(int)) == {"type": "integer"}
    assert to_json_schema(Schema(str)) == {"type": "string"}
    assert to_json_schema(Schema(float)) == {"type": "number"}
    assert to_json_schema(Schema(bool)) == {"type": "boolean"}


def test_mapping_with_markers() -> None:
    """A mapping exports properties, required, defaults, and additionalProperties."""
    schema = Schema(
        {
            Required("name"): str,
            Optional("port", default=8080): int,
        },
    )
    assert to_json_schema(schema) == {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "port": {"type": "integer", "default": 8080},
        },
        "required": ["name"],
        "additionalProperties": False,
    }


def test_description_is_exported() -> None:
    """A marker description becomes the property description."""
    schema = Schema({Optional("name", description="the name"): str})
    assert to_json_schema(schema)["properties"]["name"]["description"] == "the name"


def test_allow_extra_sets_additional_properties() -> None:
    """ALLOW_EXTRA maps to additionalProperties true."""
    schema = Schema({"a": int}, extra=ALLOW_EXTRA)
    assert to_json_schema(schema)["additionalProperties"] is True


def test_type_key_becomes_additional_properties() -> None:
    """A type key maps to an additionalProperties schema."""
    schema = Schema({str: int})
    assert to_json_schema(schema)["additionalProperties"] == {"type": "integer"}


def test_list_export() -> None:
    """A single-element list exports an array with one items schema."""
    assert to_json_schema(Schema([int])) == {
        "type": "array",
        "items": {"type": "integer"},
    }


def test_list_of_several_types() -> None:
    """A multi-element list exports anyOf items."""
    result = to_json_schema(Schema([int, str]))
    assert result["items"] == {"anyOf": [{"type": "integer"}, {"type": "string"}]}


def test_in_becomes_enum() -> None:
    """In exports an enum, keeping the author's order for an ordered container."""
    assert to_json_schema(Schema(In(["b", "a"]))) == {"enum": ["b", "a"]}


def test_unordered_containers_emit_a_stable_order() -> None:
    """A set has no order, so its emitted enum/items are sorted for deterministic output."""
    assert to_json_schema(Schema(In({"c", "a", "b"}))) == {"enum": ["a", "b", "c"]}
    assert to_json_schema(Schema(NotIn(frozenset({3, 1, 2})))) == {
        "not": {"enum": [1, 2, 3]},
    }
    # A set of element schemas renders a stable anyOf regardless of iteration order.
    assert to_json_schema(Schema({Range(min=1), Range(min=2)}))["items"] == {
        "anyOf": [{"minimum": 1}, {"minimum": 2}],
    }


def test_range_bounds() -> None:
    """Range exports minimum/maximum, with exclusive variants."""
    assert to_json_schema(Schema(Range(min=0, max=10))) == {"minimum": 0, "maximum": 10}
    assert to_json_schema(Schema(Range(min=0, min_included=False))) == {
        "exclusiveMinimum": 0,
    }


def test_length_bounds() -> None:
    """Length exports minLength/maxLength."""
    assert to_json_schema(Schema(Length(min=1, max=3))) == {
        "minLength": 1,
        "maxLength": 3,
    }


def test_all_merges_subschemas() -> None:
    """All merges its validators into one schema."""
    assert to_json_schema(Schema(All(Coerce(int), Range(min=0)))) == {
        "type": "integer",
        "minimum": 0,
    }


def test_any_becomes_any_of() -> None:
    """Any exports anyOf."""
    assert to_json_schema(Schema(Any(int, str))) == {
        "anyOf": [{"type": "integer"}, {"type": "string"}],
    }


def test_match_exports_pattern() -> None:
    """Match exports an ECMA-compatible pattern unchanged."""
    assert to_json_schema(Schema(Match(r"^\d+$"))) == {
        "type": "string",
        "pattern": r"^\d+$",
    }


@pytest.mark.parametrize(
    "pattern",
    [
        r"(?P<year>\d{4})",  # named group
        r"\A\d+\Z",  # Python-only anchors
        r"(?i)abc",  # global inline flag
        r"(?i:abc)",  # scoped inline flags
        r"(?-i:abc)",  # negated scoped flag
        r"(?i-s:abc)",  # mixed scoped flags
        r"(?#a comment)x",  # inline comment
        r"(?>\d+)",  # atomic group
        r"(\d)(?(1)a|b)",  # conditional
        r"a*+",  # possessive quantifier
    ],
)
def test_match_drops_a_python_only_pattern(pattern: str) -> None:
    """A pattern using Python-only regex syntax is dropped, leaving a valid string."""
    assert to_json_schema(Schema(Match(pattern))) == {"type": "string"}


@pytest.mark.parametrize(
    "pattern",
    [
        r"(?:ab)+c",  # non-capturing group (valid ECMA, must not be dropped)
        r"a(?=b)",  # lookahead
        r"\}+",  # an escaped brace with a quantifier is not a possessive
    ],
)
def test_match_keeps_an_ecma_compatible_pattern(pattern: str) -> None:
    """An ECMA-compatible pattern is kept, anchored at the start like re.match."""
    assert to_json_schema(Schema(Match(pattern))) == {
        "type": "string",
        "pattern": f"^(?:{pattern})",
    }


def test_match_anchors_an_unanchored_pattern() -> None:
    """Match validates with re.match (start-anchored); the emitted pattern matches."""
    assert to_json_schema(Schema(Match(r"\d+"))) == {
        "type": "string",
        "pattern": r"^(?:\d+)",
    }


def test_match_leaves_an_already_anchored_pattern() -> None:
    """A pattern already anchored at the start is emitted unchanged."""
    assert to_json_schema(Schema(Match(r"^\d+$"))) == {
        "type": "string",
        "pattern": r"^\d+$",
    }


def test_match_bytes_pattern_renders_a_plain_string() -> None:
    """A bytes pattern has no JSON Schema, so it renders a string, not a crash."""
    assert to_json_schema(Schema(Match(re.compile(rb"\d+")))) == {"type": "string"}


def test_maybe_is_nullable() -> None:
    """Maybe exports anyOf with null."""
    assert to_json_schema(Schema(Maybe(int))) == {
        "anyOf": [{"type": "null"}, {"type": "integer"}],
    }


def test_named_validators() -> None:
    """Named string/bool validators export sensible JSON Schema."""
    assert to_json_schema(Schema(Boolean())) == {"type": "boolean"}
    assert to_json_schema(Schema(Lower)) == {"type": "string"}
    assert to_json_schema(Schema(Email)) == {"type": "string", "format": "email"}


def test_literal_const() -> None:
    """A literal exports as a const."""
    assert to_json_schema(Schema("on")) == {"const": "on"}


def test_none_is_null() -> None:
    """None exports as the null type."""
    assert to_json_schema(Schema(None)) == {"type": "null"}


def test_unknown_callable_is_open() -> None:
    """An arbitrary callable validator exports as an open schema."""
    assert to_json_schema(Schema(str.strip)) == {}


def test_container_types() -> None:
    """The dict and list types map to object and array."""
    assert to_json_schema(Schema(dict)) == {"type": "object"}
    assert to_json_schema(Schema(list)) == {"type": "array"}


def test_unknown_type_is_open() -> None:
    """A type with no JSON Schema mapping exports as an open schema."""

    class Custom:
        """A type with no JSON Schema equivalent."""

    assert to_json_schema(Schema(Custom)) == {}


def test_url_uses_uri_format() -> None:
    """Url and FqdnUrl export the uri format."""
    assert to_json_schema(Schema(Url)) == {"type": "string", "format": "uri"}
    assert to_json_schema(Schema(FqdnUrl)) == {"type": "string", "format": "uri"}


def test_one_sided_bounds() -> None:
    """Range and Length export only the bound that is set."""
    assert to_json_schema(Schema(Range(max=10))) == {"maximum": 10}
    assert to_json_schema(Schema(Range(max=5, max_included=False))) == {
        "exclusiveMaximum": 5,
    }
    assert to_json_schema(Schema(Length(min=1))) == {"minLength": 1}
    assert to_json_schema(Schema(Length(max=3))) == {"maxLength": 3}


def test_remove_key_stays_an_accepted_property() -> None:
    """A Remove key is stripped from output, but a present value is validated first.

    So input carrying it is valid, and the emitted schema must accept it rather
    than reject it as an extra key: it renders as an optional property with the
    value schema Remove would have checked.
    """
    schema = Schema({"a": int, Remove("debug"): bool})
    assert to_json_schema(schema)["properties"] == {
        "a": {"type": "integer"},
        "debug": {"type": "boolean"},
    }


def test_extra_key_becomes_additional_properties() -> None:
    """An Extra catch-all key exports as additionalProperties (a callable key)."""
    result = to_json_schema(Schema({"a": int, Extra: str}))
    assert result["properties"] == {"a": {"type": "integer"}}
    assert result["additionalProperties"] == {"type": "string"}


def test_empty_list_schema() -> None:
    """An empty list schema accepts only the empty array, not any array."""
    assert to_json_schema(Schema([])) == {"type": "array", "maxItems": 0}


def test_raw_schema_input() -> None:
    """A raw (uncompiled) schema can be converted directly."""
    assert to_json_schema({"a": int})["properties"]["a"] == {"type": "integer"}


def test_exact_sequence_uses_prefix_items() -> None:
    """ExactSequence exports a fixed-length prefixItems array."""
    assert to_json_schema(Schema(ExactSequence([int, str]))) == {
        "type": "array",
        "prefixItems": [{"type": "integer"}, {"type": "string"}],
        "items": False,
        "minItems": 2,
        "maxItems": 2,
    }


def test_unique_sets_unique_items() -> None:
    """Unique exports uniqueItems, merged into the array it guards."""
    assert to_json_schema(Schema(All([int], Unique()))) == {
        "type": "array",
        "items": {"type": "integer"},
        "uniqueItems": True,
    }


def test_contains_exports_contains() -> None:
    """Contains exports the JSON Schema contains keyword."""
    assert to_json_schema(Schema(Contains(5))) == {"contains": {"const": 5}}


def test_array_length_exports_item_count() -> None:
    """A Length guarding an array exports minItems/maxItems, not the string form."""
    assert to_json_schema(Schema(All([int], Length(min=1, max=2)))) == {
        "type": "array",
        "items": {"type": "integer"},
        "minItems": 1,
        "maxItems": 2,
    }


def test_object_length_exports_property_count() -> None:
    """A Length guarding an object exports minProperties/maxProperties."""
    assert to_json_schema(Schema(All({Required("a"): int}, Length(min=2)))) == {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "additionalProperties": False,
        "required": ["a"],
        "minProperties": 2,
    }


def test_string_length_keeps_the_string_form() -> None:
    """A Length guarding a string still exports minLength/maxLength."""
    assert to_json_schema(Schema(All(str, Length(min=1, max=5)))) == {
        "type": "string",
        "minLength": 1,
        "maxLength": 5,
    }


def test_date_exports_date_format() -> None:
    """Date with the default ISO format exports format date."""
    assert to_json_schema(Schema(Date())) == {"type": "string", "format": "date"}


def test_datetime_exports_date_time_format() -> None:
    """Datetime with the default ISO format exports format date-time."""
    assert to_json_schema(Schema(Datetime())) == {
        "type": "string",
        "format": "date-time",
    }


def test_temporal_custom_format_drops_the_format() -> None:
    """A custom strptime format has no JSON Schema equivalent, so it is a string."""
    assert to_json_schema(Schema(Datetime("%Y/%m/%d"))) == {"type": "string"}
    assert to_json_schema(Schema(Date("%d-%m-%Y"))) == {"type": "string"}


def test_datetime_round_trips_through_the_decoder() -> None:
    """to_json_schema(Datetime()) decodes into an RFC 3339 validator that re-encodes."""
    document = to_json_schema(Schema(Datetime()))
    decoded = from_json_schema(document)
    assert decoded("2024-01-01T00:00:00Z") == "2024-01-01T00:00:00Z"
    assert to_json_schema(decoded) == document


@pytest.mark.parametrize(
    ("validator", "expected"),
    [
        (AsDate(), {"type": "string", "format": "date"}),
        (AsTime(), {"type": "string", "format": "time"}),
        (AsDatetime(), {"type": "string", "format": "date-time"}),
    ],
)
def test_as_parsers_export_like_their_string_siblings(
    validator: object, expected: dict
) -> None:
    """The object-returning As* parsers export the same string schema as Date/Time."""
    assert to_json_schema(Schema(validator)) == expected


def test_as_parser_custom_format_drops_the_format() -> None:
    """An As* parser with a custom format has no JSON Schema equivalent: a string."""
    assert to_json_schema(Schema(AsDate(format="%d-%m-%Y"))) == {"type": "string"}


def test_as_datetime_round_trips_to_a_string_validator() -> None:
    """AsDatetime encodes to date-time, which decodes to a string RFC 3339 check."""
    decoded = from_json_schema(to_json_schema(Schema(AsDatetime())))
    assert decoded("2024-01-01T00:00:00+02:00") == "2024-01-01T00:00:00+02:00"


@pytest.mark.parametrize(
    ("validator", "expected"),
    [
        (IPv4Address(), {"type": "string", "format": "ipv4"}),
        (IPv6Address(), {"type": "string", "format": "ipv6"}),
        (UUID(), {"type": "string", "format": "uuid"}),
        (Hostname(), {"type": "string", "format": "hostname"}),
        (Fqdn(), {"type": "string", "format": "hostname"}),
        (IPAddress(), {"type": "string"}),
        (IPNetwork(), {"type": "string"}),
        (MacAddress(), {"type": "string"}),
        (TimeZone(), {"type": "string"}),
        (TimeZoneInfo(), {"type": "string"}),
        (Slug(), {"type": "string"}),
        (Time(), {"type": "string", "format": "time"}),
        (Port(), {"type": "integer", "minimum": 1, "maximum": 65535}),
        (Percentage(), {"type": "number", "minimum": 0, "maximum": 100}),
        (MultipleOf(5), {"multipleOf": 5}),
        (FromEpoch(), {"type": "number"}),
    ],
)
def test_new_validators_export(validator: object, expected: dict) -> None:
    """Each network/identifier/numeric validator exports its JSON Schema fragment."""
    assert to_json_schema(Schema(validator)) == expected


def test_secret_key_exports_write_only() -> None:
    """A Secret key marks its property writeOnly, JSON Schema's secret marker."""
    schema = Schema({Required(Secret("password")): str})
    assert to_json_schema(schema) == {
        "type": "object",
        "properties": {"password": {"type": "string", "writeOnly": True}},
        "additionalProperties": False,
        "required": ["password"],
    }


def test_secret_layer_description_is_kept() -> None:
    """A description carried on the Secret layer survives into the property."""
    schema = Schema({Required(Secret("password", description="the token")): str})
    prop = to_json_schema(schema)["properties"]["password"]
    assert prop["description"] == "the token"
    assert prop["writeOnly"] is True


def test_secret_around_a_type_key_is_rejected_by_the_codec() -> None:
    """A raw mapping with Secret around a type key is refused, like the compiler."""
    from probatio.error import SchemaError  # noqa: PLC0415

    with pytest.raises(SchemaError):
        to_json_schema({Secret(str): int})


def test_time_is_not_exported_as_datetime() -> None:
    """Time (a Datetime subclass) exports format time, not date-time."""
    assert to_json_schema(Schema(Time()))["format"] == "time"


def test_string_class_validators_export_string() -> None:
    """The character-class and affix validators export as a JSON Schema string."""
    assert to_json_schema(Schema(Alpha())) == {"type": "string"}
    assert to_json_schema(Schema(ByteLength(max=5))) == {"type": "string"}
    assert to_json_schema(Schema(ASCII())) == {"type": "string"}


def test_base64_exports_content_encoding() -> None:
    """Base64 exports a string with the contentEncoding keyword."""
    assert to_json_schema(Schema(Base64())) == {
        "type": "string",
        "contentEncoding": "base64",
    }


def test_called_format_factories_encode_to_format() -> None:
    """The called Email()/Url()/FqdnUrl() forms encode to their string format."""
    assert to_json_schema(Schema(Email())) == {"type": "string", "format": "email"}
    assert to_json_schema(Schema(Url())) == {"type": "string", "format": "uri"}
    assert to_json_schema(Schema(FqdnUrl())) == {"type": "string", "format": "uri"}


def test_equal_and_literal_encode_to_const() -> None:
    """Equal and Literal encode to a JSON Schema const."""
    assert to_json_schema(Schema(Equal(5))) == {"const": 5}
    assert to_json_schema(Schema(Literal("on"))) == {"const": "on"}


def test_not_in_encodes_to_not_enum() -> None:
    """NotIn encodes to a JSON Schema not over an enum."""
    assert to_json_schema(Schema(NotIn([1, 2]))) == {"not": {"enum": [1, 2]}}


def test_nested_required_default_propagates() -> None:
    """A schema-wide required default reaches nested dict values, like the engine."""
    schema = Schema({"outer": {"inner": int}}, required=True)
    result = to_json_schema(schema)
    assert result["required"] == ["outer"]
    assert result["properties"]["outer"]["required"] == ["inner"]


def test_nested_allow_extra_propagates() -> None:
    """ALLOW_EXTRA reaches nested dict values, so a nested object stays open."""
    schema = Schema({"outer": {"inner": int}}, extra=ALLOW_EXTRA)
    result = to_json_schema(schema)
    assert result["additionalProperties"] is True
    assert result["properties"]["outer"]["additionalProperties"] is True


def test_required_default_propagates_through_a_list() -> None:
    """The required default reaches a dict nested inside a list value."""
    schema = Schema({"a": [{"b": int}]}, required=True)
    item = to_json_schema(schema)["properties"]["a"]["items"]
    assert item["required"] == ["b"]


def test_required_default_propagates_into_variable_key_values() -> None:
    """The required default reaches a dict nested under a variable (type) key."""
    schema = Schema({str: {"b": int}}, required=True)
    additional = to_json_schema(schema)["additionalProperties"]
    assert additional["required"] == ["b"]


def test_required_with_default_stays_out_of_required() -> None:
    """A Required marker with a default does not demand presence (default fills it)."""
    result = to_json_schema(Schema({Required("n", default=5): int}))
    assert "required" not in result
    assert result["properties"]["n"] == {"type": "integer", "default": 5}


def test_remove_extra_renders_open() -> None:
    """REMOVE_EXTRA accepts extra keys on input, so it renders additionalProperties true."""
    result = to_json_schema(Schema({"a": int}, extra=REMOVE_EXTRA))
    assert result["additionalProperties"] is True


def test_multiple_variable_keys_merge_into_any_of() -> None:
    """Several variable keys merge into an additionalProperties anyOf, none dropped."""
    result = to_json_schema(Schema({str: int, int: str}))
    assert result["additionalProperties"] == {
        "anyOf": [{"type": "integer"}, {"type": "string"}],
    }


def test_non_string_literal_key_is_skipped() -> None:
    """A non-string literal key never matches a JSON key, so it is not emitted."""
    result = to_json_schema(Schema({"a": int, 1: str}))
    assert result["properties"] == {"a": {"type": "integer"}}


def test_empty_description_is_emitted() -> None:
    """An empty-string description is a real description, not dropped as falsy."""
    result = to_json_schema(Schema({Optional("a", description=""): int}))
    assert result["properties"]["a"]["description"] == ""


def test_forbidden_type_key_closes_the_object() -> None:
    """Forbidden(str) rejects every string key at runtime, so the schema closes."""
    from probatio.markers import Forbidden  # noqa: PLC0415

    result = to_json_schema(Schema({"a": int, Forbidden(str): object}))
    assert result["properties"] == {"a": {"type": "integer"}}
    assert result["additionalProperties"] is False


def test_forbidden_type_key_closes_over_allow_extra() -> None:
    """A Forbidden type key closes the object even under ALLOW_EXTRA."""
    from probatio.markers import Forbidden  # noqa: PLC0415

    result = to_json_schema(Schema({Forbidden(str): object}, extra=ALLOW_EXTRA))
    assert result["additionalProperties"] is False


def test_self_exports_a_recursive_ref() -> None:
    """A Self reference exports as a $ref to the document root, not an open schema."""
    from probatio import Self  # noqa: PLC0415

    schema = Schema({"name": str, Optional("children"): [Self]})
    result = to_json_schema(schema)
    assert result["properties"]["children"]["items"] == {"$ref": "#"}


def test_all_with_colliding_keywords_uses_all_of() -> None:
    """Two validators emitting the same keyword merge into allOf, not last-writer-wins."""
    result = to_json_schema(Schema(All(Any(int, str), Any(str, float))))
    assert result == {
        "allOf": [
            {"anyOf": [{"type": "integer"}, {"type": "string"}]},
            {"anyOf": [{"type": "string"}, {"type": "number"}]},
        ],
    }


def test_all_without_collisions_still_merges() -> None:
    """Non-colliding validators keep the compact single-object merge."""
    assert to_json_schema(Schema(All(int, Range(min=0)))) == {
        "type": "integer",
        "minimum": 0,
    }


def test_enum_with_a_datetime_member_stays_serializable() -> None:
    """An In holding a datetime renders ISO strings, not raw datetimes."""
    from datetime import datetime  # noqa: PLC0415

    result = to_json_schema(Schema(In([datetime(2020, 1, 1)])))
    assert result == {"enum": ["2020-01-01T00:00:00"]}


def test_enum_with_enum_members_renders_their_values() -> None:
    """An In holding Enum members renders the member values."""
    from enum import Enum  # noqa: PLC0415

    class Color(Enum):
        RED = "red"
        BLUE = "blue"

    assert to_json_schema(Schema(In([Color.RED, Color.BLUE]))) == {
        "enum": ["red", "blue"],
    }


def test_const_with_a_decimal_renders_a_float() -> None:
    """An Equal holding a Decimal renders a float const, not a raw Decimal."""
    assert to_json_schema(Schema(Equal(Decimal("1.5")))) == {"const": 1.5}


def test_enum_with_tuples_renders_lists() -> None:
    """An In holding tuples renders JSON arrays (the wire form)."""
    assert to_json_schema(Schema(In([(1, 2), (3, 4)]))) == {"enum": [[1, 2], [3, 4]]}


def test_datetime_default_renders_iso() -> None:
    """A datetime default renders its ISO string rather than a raw datetime."""
    from datetime import datetime  # noqa: PLC0415

    schema = Schema({Optional("t", default=datetime(2020, 1, 1)): object})
    assert to_json_schema(schema)["properties"]["t"]["default"] == "2020-01-01T00:00:00"


def test_unrepresentable_default_is_omitted() -> None:
    """A default with no JSON form is dropped rather than emitted raw."""
    schema = Schema({Optional("t", default=b"raw"): object})
    assert "default" not in to_json_schema(schema)["properties"]["t"]


def test_non_numeric_range_bound_is_omitted() -> None:
    """A non-numeric Range bound has no JSON keyword, so it is omitted."""
    from datetime import datetime  # noqa: PLC0415

    assert to_json_schema(Schema(Range(min=datetime(2020, 1, 1)))) == {}


def test_unrepresentable_enum_member_widens_to_open() -> None:
    """A member with no JSON form drops the enum to an open schema, not a crash."""
    assert to_json_schema(Schema(In([b"bytes"]))) == {}


def test_cyclic_raw_schema_is_a_clean_error() -> None:
    """A raw dict that references itself is refused, not a bare RecursionError."""
    from probatio.error import SchemaError  # noqa: PLC0415

    node: dict[object, object] = {"v": int}
    node["next"] = node
    with pytest.raises(SchemaError, match="references itself"):
        to_json_schema(node)


def test_const_with_a_dict_renders_json_safe_values() -> None:
    """A dict const renders with each value made JSON-safe (a datetime to ISO)."""
    from datetime import datetime  # noqa: PLC0415

    result = to_json_schema(Schema(Equal({"when": datetime(2020, 1, 1)})))
    assert result == {"const": {"when": "2020-01-01T00:00:00"}}


def test_const_with_a_non_string_dict_key_widens_to_open() -> None:
    """A dict const with a non-string key has no JSON object form, so it opens."""
    assert to_json_schema(Schema(Equal({1: "a"}))) == {}


def test_const_with_an_unrepresentable_dict_value_widens_to_open() -> None:
    """A dict const holding an unrepresentable value opens rather than crashing."""
    assert to_json_schema(Schema(Equal({"a": b"raw"}))) == {}


def test_alias_emits_every_accepted_name() -> None:
    """An aliased key renders each of its accepted names as a property."""
    from probatio.markers import Alias  # noqa: PLC0415

    result = to_json_schema(Schema({Alias("name", "userName"): str}))
    assert result["properties"] == {
        "name": {"type": "string"},
        "userName": {"type": "string"},
    }
    assert "allOf" not in result


def test_required_alias_demands_one_name() -> None:
    """A required Alias adds an anyOf requiring at least one of its names."""
    from probatio.markers import Alias  # noqa: PLC0415

    result = to_json_schema(Schema({Alias("name", "userName", required=True): str}))
    assert result["allOf"] == [
        {"anyOf": [{"required": ["name"]}, {"required": ["userName"]}]},
    ]


def test_inclusive_group_is_all_or_none() -> None:
    """An Inclusive group renders dependentRequired, so members come all or none."""
    from probatio.markers import Inclusive  # noqa: PLC0415

    schema = Schema({Inclusive("a", "g"): int, Inclusive("b", "g"): int})
    assert to_json_schema(schema)["allOf"] == [
        {"dependentRequired": {"a": ["b"], "b": ["a"]}},
    ]


def test_exclusive_group_is_at_most_one() -> None:
    """An Exclusive group forbids more than one member being present."""
    from probatio.markers import Exclusive  # noqa: PLC0415

    schema = Schema({Exclusive("a", "g"): int, Exclusive("b", "g"): int})
    assert to_json_schema(schema)["allOf"] == [
        {"not": {"anyOf": [{"required": ["a", "b"]}]}},
    ]


def test_required_exclusive_group_is_exactly_one() -> None:
    """A required Exclusive group (no default) demands exactly one member."""
    from probatio.markers import Exclusive  # noqa: PLC0415

    schema = Schema(
        {Exclusive("a", "g", required=True): int, Exclusive("b", "g"): int},
    )
    assert to_json_schema(schema)["allOf"] == [
        {"oneOf": [{"required": ["a"]}, {"required": ["b"]}]},
    ]


def test_required_exclusive_group_with_default_stays_at_most_one() -> None:
    """A default fills the empty group, so a required-with-default group is at-most-one."""
    from probatio.markers import Exclusive  # noqa: PLC0415

    schema = Schema(
        {
            Exclusive("a", "g", required=True, default=1): int,
            Exclusive("b", "g"): int,
        },
    )
    result = to_json_schema(schema)
    assert result["properties"]["a"]["default"] == 1
    assert result["allOf"] == [{"not": {"anyOf": [{"required": ["a", "b"]}]}}]


def test_single_member_groups_add_no_vacuous_constraint() -> None:
    """A one-member Inclusive or at-most-one Exclusive group needs no constraint."""
    from probatio.markers import Exclusive, Inclusive  # noqa: PLC0415

    assert "allOf" not in to_json_schema(Schema({Inclusive("a", "g"): int}))
    assert "allOf" not in to_json_schema(Schema({Exclusive("a", "g"): int}))


def test_required_alias_with_default_adds_no_constraint() -> None:
    """A required Alias with a default fills the empty case, so it demands no name."""
    from probatio.markers import Alias  # noqa: PLC0415

    schema = Schema({Alias("name", "userName", required=True, default=5): int})
    result = to_json_schema(schema)
    assert "allOf" not in result
    assert result["properties"]["name"]["default"] == 5


def test_union_becomes_any_of() -> None:
    """Union accepts any branch, so it exports anyOf like Any."""
    from probatio.validators import Union  # noqa: PLC0415

    assert to_json_schema(Schema(Union(int, str))) == {
        "anyOf": [{"type": "integer"}, {"type": "string"}],
    }


def test_switch_becomes_any_of() -> None:
    """Switch is an alias of Union, so it exports anyOf too."""
    from probatio.validators import Switch  # noqa: PLC0415

    assert to_json_schema(Schema(Switch(int, str))) == {
        "anyOf": [{"type": "integer"}, {"type": "string"}],
    }


def test_some_of_exactly_one_becomes_one_of() -> None:
    """SomeOf(min=max=1) is exactly-one, which exports as oneOf."""
    from probatio.validators import SomeOf  # noqa: PLC0415

    schema = SomeOf([int, str], min_valid=1, max_valid=1)
    assert to_json_schema(Schema(schema)) == {
        "oneOf": [{"type": "integer"}, {"type": "string"}],
    }


def test_some_of_at_least_one_becomes_any_of() -> None:
    """SomeOf(min=1, max=count) is at-least-one, which exports as anyOf."""
    from probatio.validators import SomeOf  # noqa: PLC0415

    schema = SomeOf([int, str], min_valid=1, max_valid=2)
    assert to_json_schema(Schema(schema)) == {
        "anyOf": [{"type": "integer"}, {"type": "string"}],
    }


def test_some_of_all_becomes_all_of() -> None:
    """SomeOf(min=max=count) requires every branch, which exports as allOf."""
    from probatio.validators import SomeOf  # noqa: PLC0415

    schema = SomeOf([int, Range(min=0)], min_valid=2, max_valid=2)
    assert to_json_schema(Schema(schema)) == {
        "allOf": [{"type": "integer"}, {"minimum": 0}],
    }


def test_some_of_uncommon_count_widens_to_open() -> None:
    """A SomeOf count JSON Schema cannot express widens to an open schema."""
    from probatio.validators import SomeOf  # noqa: PLC0415

    schema = SomeOf([int, str, float], min_valid=2, max_valid=2)
    assert to_json_schema(Schema(schema)) == {}


def test_msg_unwraps_to_its_validator() -> None:
    """Msg only swaps the error message, so it exports the wrapped validator's shape."""
    from probatio.validators import Msg  # noqa: PLC0415

    assert to_json_schema(Schema(Msg(int, "nope"))) == {"type": "integer"}


def test_enum_class_becomes_enum_of_values() -> None:
    """An Enum class exports an enum of its member values (the wire form)."""
    from enum import Enum  # noqa: PLC0415

    class Color(Enum):
        RED = "red"
        BLUE = "blue"

    assert to_json_schema(Schema(Color)) == {"enum": ["red", "blue"]}


def test_duration_exports_format_duration() -> None:
    """Duration and AsTimedelta export the standard format: duration."""
    from probatio.validators import AsTimedelta, Duration  # noqa: PLC0415

    assert to_json_schema(Schema(Duration())) == {
        "type": "string",
        "format": "duration",
    }
    assert to_json_schema(Schema(AsTimedelta())) == {
        "type": "string",
        "format": "duration",
    }


def test_non_empty_exports_min_length() -> None:
    """NonEmpty requires a non-empty value, exported as minLength for strings."""
    from probatio.validators import NonEmpty  # noqa: PLC0415

    assert to_json_schema(Schema(NonEmpty())) == {"minLength": 1}


def test_default_to_exports_a_default() -> None:
    """DefaultTo carries only its default value into the schema."""
    from probatio.validators import DefaultTo  # noqa: PLC0415

    assert to_json_schema(Schema(DefaultTo(5))) == {"default": 5}


def test_strict_raises_on_an_unrepresentable_validator() -> None:
    """strict=True refuses a construct that would silently widen to an open schema."""
    from probatio.error import SchemaError  # noqa: PLC0415

    with pytest.raises(SchemaError, match="cannot represent"):
        to_json_schema(Schema(str.strip), strict=True)


def test_strict_raises_on_an_unrepresentable_enum_member() -> None:
    """strict=True refuses an enum member with no JSON form."""
    from probatio.error import SchemaError  # noqa: PLC0415

    with pytest.raises(SchemaError, match="no JSON form"):
        to_json_schema(Schema(In([b"raw"])), strict=True)


def test_strict_allows_a_faithfully_open_schema() -> None:
    """strict=True does not raise for object, which is faithfully an open schema."""
    assert to_json_schema(Schema(object), strict=True) == {}


def test_non_strict_still_widens_by_default() -> None:
    """Without strict, an unrepresentable construct still widens to an open schema."""
    assert to_json_schema(Schema(str.strip)) == {}


def test_custom_serializer_overrides_a_node() -> None:
    """custom_serializer replaces a node's rendering when it returns a dict."""
    from probatio.codecs import UNSUPPORTED  # noqa: PLC0415

    def custom(node: object) -> object:
        if node is str.strip:
            return {"type": "string", "x-trimmed": True}
        return UNSUPPORTED

    result = to_json_schema(Schema({"a": str.strip}), custom_serializer=custom)
    assert result["properties"]["a"] == {"type": "string", "x-trimmed": True}


def test_custom_serializer_defers_with_unsupported() -> None:
    """A custom_serializer that returns UNSUPPORTED falls back to the default."""
    from probatio.codecs import UNSUPPORTED  # noqa: PLC0415

    def custom(_node: object) -> object:
        return UNSUPPORTED

    assert to_json_schema(Schema(int), custom_serializer=custom) == {"type": "integer"}


def test_coerce_with_a_non_type_target_widens() -> None:
    """A Coerce whose target is a callable, not a type, has no shape and widens."""
    assert to_json_schema(Schema(Coerce(str.upper))) == {}


def test_strict_raises_on_a_coerce_with_a_non_type_target() -> None:
    """strict=True refuses a Coerce with a non-type target rather than widening."""
    from probatio.error import SchemaError  # noqa: PLC0415

    with pytest.raises(SchemaError, match="non-type target"):
        to_json_schema(Schema(Coerce(str.upper)), strict=True)
