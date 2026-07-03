"""Tests for JSON Schema export."""

from __future__ import annotations

import pytest

from probatio import (
    ALLOW_EXTRA,
    ASCII,
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
    """An ECMA-compatible pattern, including ones that resemble Python-only, is kept."""
    assert to_json_schema(Schema(Match(pattern))) == {
        "type": "string",
        "pattern": pattern,
    }


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


def test_remove_keys_are_skipped() -> None:
    """A Remove key does not appear in the exported properties."""
    schema = Schema({"a": int, Remove("debug"): bool})
    assert to_json_schema(schema)["properties"] == {"a": {"type": "integer"}}


def test_extra_key_becomes_additional_properties() -> None:
    """An Extra catch-all key exports as additionalProperties (a callable key)."""
    result = to_json_schema(Schema({"a": int, Extra: str}))
    assert result["properties"] == {"a": {"type": "integer"}}
    assert result["additionalProperties"] == {"type": "string"}


def test_empty_list_schema() -> None:
    """An empty list schema exports an array with no item constraint."""
    assert to_json_schema(Schema([])) == {"type": "array"}


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
