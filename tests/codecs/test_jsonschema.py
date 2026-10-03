"""Tests for JSON Schema export."""

from __future__ import annotations

import itertools
import re
from decimal import Decimal

import jsonschema
import pytest

from probatio import (
    ALLOW_EXTRA,
    ASCII,
    REMOVE_EXTRA,
    UUID,
    Alias,
    All,
    AllOrNone,
    Alpha,
    Any,
    AsDate,
    AsDatetime,
    AsTime,
    AtLeastOne,
    AtMostOne,
    Base64,
    Boolean,
    ByteLength,
    Coerce,
    Contains,
    Date,
    Datetime,
    Email,
    EnsureList,
    Equal,
    ExactlyOne,
    ExactSequence,
    Exclusive,
    Extra,
    Fqdn,
    FqdnUrl,
    FromEpoch,
    Hostname,
    In,
    Inclusive,
    Invalid,
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
    RequiredIf,
    RequiredWith,
    RequiredWithout,
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
from probatio.codecs.openapi import to_openapi


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


def test_a_single_branch_any_renders_as_its_branch() -> None:
    """One branch is exactly that branch, so no anyOf wraps it.

    The wrapper also unsettled a round trip: ``items: {"anyOf": [x]}`` decodes to
    the sequence ``[x]``, which renders as ``items: x``, one level flatter per
    trip until flat.
    """
    from probatio.validators import Union  # noqa: PLC0415

    assert to_json_schema(Schema(Any(int))) == {"type": "integer"}
    assert to_json_schema(Schema(Union(int))) == {"type": "integer"}

    document = to_json_schema(Schema([Any(Union(True))]))
    assert document == {"type": "array", "items": {"const": True}}
    assert to_json_schema(from_json_schema(document)) == document


def test_an_empty_any_renders_as_a_rejection() -> None:
    """``Any()`` accepts nothing; ``not: {}`` says so and is a valid schema.

    An empty ``anyOf`` would say the same, but the metaschema requires at least
    one branch, so a document carrying it is not a JSON Schema at all.
    """
    document = to_json_schema(Schema(Any()))
    assert document == {"not": {}}
    jsonschema.Draft202012Validator.check_schema(document)
    validator = jsonschema.Draft202012Validator(document)
    for value in (1, "x", None, [], {}):
        assert not validator.is_valid(value)


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


def test_null_has_one_spelling() -> None:
    """Every validator that accepts only None renders as ``{"type": "null"}``."""
    # ``{"const": null}`` says the same thing, but a round trip has to settle on
    # one document, and ``type: null`` is what ``None`` and ``Maybe`` already emit.
    for schema in (None, type(None), Literal(None), Equal(None)):
        assert to_json_schema(Schema(schema)) == {"type": "null"}


def test_a_null_round_trip_is_a_structural_fixpoint() -> None:
    """A null anywhere in a document decodes and re-encodes to the same document."""
    # Both spellings decode to the same validator, so the re-encoded document does
    # not flip between ``type: null`` and ``const: null`` on alternate trips.
    for schema in (
        Schema(Maybe(int)),
        Schema({"a": None, Optional("b"): Literal(None)}),
        Schema({Extra: None}),
        Schema([None]),
    ):
        document = to_json_schema(schema)
        assert to_json_schema(from_json_schema(document)) == document
    for document in (
        {"const": None},
        {"anyOf": [{"const": None}, {"type": "integer"}]},
    ):
        settled = to_json_schema(from_json_schema(document))
        assert settled == to_json_schema(from_json_schema(settled))


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
    """Two validators disagreeing on a keyword fall back to allOf, not last-writer-wins."""
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


def test_all_with_agreeing_keywords_merges() -> None:
    """Two validators saying the same thing about a keyword merge, not allOf."""
    assert to_json_schema(Schema(All(str, Match("^x")))) == {
        "type": "string",
        "pattern": "^x",
    }


def test_all_with_disagreeing_values_for_a_keyword_uses_all_of() -> None:
    """Two validators that disagree on a keyword's value each keep their branch."""
    assert to_json_schema(Schema(All(Match("^a"), Match("b$")))) == {
        "allOf": [
            {"type": "string", "pattern": "^a"},
            {"type": "string", "pattern": "^(?:b$)"},
        ],
    }


def test_all_agreeing_only_under_python_equality_keeps_both_branches() -> None:
    """``1`` and ``true`` are different JSON values, however Python compares them.

    A decoded conjunction of the two rejects every value. Merged under Python
    equality it would render as a satisfiable ``{"const": true}``.
    """
    for document in (
        {"allOf": [{"const": 1}, {"const": True}]},
        {"allOf": [{"enum": [1]}, {"enum": [True]}]},
    ):
        assert to_json_schema(from_json_schema(document)) == document


def test_a_typed_pattern_round_trip_is_a_structural_fixpoint() -> None:
    """The document a decoded pattern renders to is the one it was decoded from.

    ``{"type": "string", "pattern": ...}`` decodes to ``All(str, pattern)``. Were
    that rendered as an ``allOf``, the document would nest one level deeper on
    every trip, forever, while staying behaviorally the same.
    """
    for schema in (
        Schema(Match("^a")),
        Schema({"x": All(str, Match("^x"), Length(max=3))}),
        Schema(All(Match("^a"), Match("b$"))),
    ):
        document = to_json_schema(schema)
        assert to_json_schema(from_json_schema(document)) == document


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
    """An Inclusive group renders a dependentRequired sibling, all-or-none members."""
    from probatio.markers import Inclusive  # noqa: PLC0415

    schema = Schema({Inclusive("a", "g"): int, Inclusive("b", "g"): int})
    assert to_json_schema(schema)["dependentRequired"] == {"a": ["b"], "b": ["a"]}


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

    assert "dependentRequired" not in to_json_schema(Schema({Inclusive("a", "g"): int}))
    assert "allOf" not in to_json_schema(Schema({Exclusive("a", "g"): int}))


def test_required_alias_with_default_adds_no_constraint() -> None:
    """A required Alias with a default fills the empty case, so it demands no name."""
    from probatio.markers import Alias  # noqa: PLC0415

    schema = Schema({Alias("name", "userName", required=True, default=5): int})
    result = to_json_schema(schema)
    assert "allOf" not in result
    assert result["properties"]["name"]["default"] == 5


def test_any_key_emits_every_listed_name() -> None:
    """An Any key over literal names renders each name as a property, not a variable key."""
    result = to_json_schema(Schema({Any("hours", "minutes"): int}))
    assert result["properties"] == {
        "hours": {"type": "integer"},
        "minutes": {"type": "integer"},
    }
    assert result["additionalProperties"] is False
    assert "allOf" not in result


def test_required_any_key_demands_one_name() -> None:
    """A required Any key adds an anyOf requiring at least one of its names."""
    result = to_json_schema(
        Schema(
            {Required(Any("hours", "minutes", "seconds")): int, Optional("name"): str}
        )
    )
    assert sorted(result["properties"]) == ["hours", "minutes", "name", "seconds"]
    assert "required" not in result
    assert result["allOf"] == [
        {
            "anyOf": [
                {"required": ["hours"]},
                {"required": ["minutes"]},
                {"required": ["seconds"]},
            ],
        },
    ]


def test_required_any_key_follows_the_schema_required_default() -> None:
    """A bare Any key on a required=True schema demands a name like a bare literal key."""
    result = to_json_schema(Schema({Any("a", "b"): int}, required=True))
    assert result["allOf"] == [{"anyOf": [{"required": ["a"]}, {"required": ["b"]}]}]


def test_required_any_key_with_default_adds_no_constraint() -> None:
    """A required Any key with a default fills the empty case, so it demands no name."""
    result = to_json_schema(Schema({Required(Any("a", "b"), default=1): int}))
    assert "allOf" not in result
    assert result["properties"]["a"]["default"] == 1
    assert result["properties"]["b"]["default"] == 1


def test_any_key_with_a_description_decorates_every_name() -> None:
    """A description on an Any key lands on each of its properties."""
    result = to_json_schema(Schema({Optional(Any("a", "b"), description="d"): int}))
    assert result["properties"]["a"]["description"] == "d"
    assert result["properties"]["b"]["description"] == "d"


def test_any_key_over_validators_stays_a_variable_key() -> None:
    """An Any key holding a type or validator is a variable key, not a set of names."""
    result = to_json_schema(Schema({Required(Any("a", str)): int}))
    assert result["properties"] == {}
    assert result["additionalProperties"] == {"type": "integer"}
    assert "allOf" not in result


@pytest.mark.parametrize(
    "schema",
    [
        Schema({"hours": str, Any("hours", "minutes"): int}),
        Schema({Any("hours", "minutes"): int, "hours": str}),
    ],
    ids=["literal_first", "any_first"],
)
def test_literal_key_wins_over_an_any_key_listing_the_same_name(schema: Schema) -> None:
    """A literal key is matched ahead of an Any key, so its value schema is the one emitted."""
    result = to_json_schema(schema)
    assert result["properties"] == {
        "hours": {"type": "string"},
        "minutes": {"type": "integer"},
    }
    schema({"hours": "text"})
    assert jsonschema.Draft202012Validator(result).is_valid({"hours": "text"})


def test_any_key_names_a_repeated_name_once() -> None:
    """A name listed twice in an Any key is one property and one required branch."""
    result = to_json_schema(Schema({Required(Any("a", "a", "b")): int}))
    assert sorted(result["properties"]) == ["a", "b"]
    assert result["allOf"] == [
        {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]},
    ]


def test_any_key_gives_each_name_its_own_property() -> None:
    """Editing one emitted property does not reach the others the key expanded into."""
    result = to_json_schema(Schema({Any("a", "b"): int}))
    assert result["properties"]["a"] is not result["properties"]["b"]

    result["properties"]["a"]["description"] = "only a"
    assert "description" not in result["properties"]["b"]


def test_any_key_never_narrows() -> None:
    """The emitted document accepts exactly what the mapping accepts."""
    schema = Schema({Required(Any("hours", "minutes")): int, Optional("name"): str})
    validator = jsonschema.Draft202012Validator(to_json_schema(schema))
    for value in (
        {"hours": 1},
        {"minutes": 2, "name": "tea"},
        {"hours": 1, "minutes": 2},
    ):
        schema(value)
        assert validator.is_valid(value)
    for value in ({}, {"name": "tea"}, {"hours": "x"}):
        with pytest.raises(Invalid):
            schema(value)
        assert not validator.is_valid(value)


# Home Assistant's intent slot schemas, as they key a duration or a target on an
# ``Any`` over literal slot names. ``cv.positive_int`` is
# ``All(Coerce(int), Range(min=0))``; the string validators render as ``str``.
_POSITIVE_INT = All(Coerce(int), Range(min=0))
_HA_START_TIMER = {
    Required(Any("hours", "minutes", "seconds")): _POSITIVE_INT,
    Optional("name"): str,
    Optional("conversation_command"): str,
}
_HA_CANCEL_TIMER = {
    Any("start_hours", "start_minutes", "start_seconds"): _POSITIVE_INT,
    Optional("name"): str,
    Optional("area"): str,
}
_HA_INCREASE_TIMER = {
    Any("hours", "minutes", "seconds"): _POSITIVE_INT,
    Any("start_hours", "start_minutes", "start_seconds"): _POSITIVE_INT,
    Optional("name"): str,
    Optional("area"): str,
}
_HA_SERVICE_INTENT = {
    Any("name", "area", "floor"): str,
    Optional("domain"): [In(["light"])],
    Optional("preferred_area_id"): str,
    Optional("preferred_floor_id"): str,
}


def test_home_assistant_start_timer_lists_every_duration_slot() -> None:
    """HassStartTimer names hours, minutes, and seconds and demands one of them."""
    duration = {"type": "integer", "minimum": 0}
    assert to_json_schema(Schema(_HA_START_TIMER)) == {
        "type": "object",
        "properties": {
            "hours": duration,
            "minutes": duration,
            "seconds": duration,
            "name": {"type": "string"},
            "conversation_command": {"type": "string"},
        },
        "additionalProperties": False,
        "allOf": [
            {
                "anyOf": [
                    {"required": ["hours"]},
                    {"required": ["minutes"]},
                    {"required": ["seconds"]},
                ],
            },
        ],
    }


def test_home_assistant_start_timer_document_agrees_with_the_schema() -> None:
    """The HassStartTimer document accepts and rejects exactly what the schema does."""
    schema = Schema(_HA_START_TIMER)
    validator = jsonschema.Draft202012Validator(to_json_schema(schema))
    for value in ({"minutes": 5}, {"hours": 1, "seconds": 2, "name": "tea"}):
        schema(value)
        assert validator.is_valid(value)
    for value in ({}, {"name": "tea"}, {"minutes": -1}):
        with pytest.raises(Invalid):
            schema(value)
        assert not validator.is_valid(value)


def test_home_assistant_optional_duration_slots_add_no_constraint() -> None:
    """HassCancelTimer's bare Any key lists its slots without demanding one."""
    result = to_json_schema(Schema(_HA_CANCEL_TIMER))
    assert sorted(result["properties"]) == [
        "area",
        "name",
        "start_hours",
        "start_minutes",
        "start_seconds",
    ]
    assert "allOf" not in result


def test_home_assistant_increase_timer_keeps_both_any_keys() -> None:
    """HassIncreaseTimer's two Any keys each expand into their own slots."""
    result = to_json_schema(Schema(_HA_INCREASE_TIMER))
    assert sorted(result["properties"]) == [
        "area",
        "hours",
        "minutes",
        "name",
        "seconds",
        "start_hours",
        "start_minutes",
        "start_seconds",
    ]


def test_home_assistant_service_intent_lists_every_target_slot() -> None:
    """A service intent's name, area, and floor slots are properties, not a variable key."""
    result = to_json_schema(Schema(_HA_SERVICE_INTENT))
    assert result["properties"]["floor"] == {"type": "string"}
    assert result["additionalProperties"] is False


@pytest.mark.parametrize(
    "slots",
    [_HA_START_TIMER, _HA_CANCEL_TIMER, _HA_INCREASE_TIMER, _HA_SERVICE_INTENT],
    ids=["start_timer", "cancel_timer", "increase_timer", "service_intent"],
)
def test_home_assistant_slots_name_the_same_properties_as_openapi(slots: dict) -> None:
    """Both codecs list the same slot names, so a tool schema reads the same either way."""
    schema = Schema(slots)
    assert set(to_json_schema(schema)["properties"]) == set(
        to_openapi(schema)["properties"]
    )


# A group member is usually a literal key, but it can be an ``Any`` over literal
# names, which the engine counts as one member satisfied by any of those names
# (a documented deviation from voluptuous). Both codecs used to expand the names
# into properties and then drop the group constraint, so the emitted document
# accepted input the schema rejects.
_ANY_GROUP_SCHEMAS = {
    "inclusive": {Inclusive(Any("a", "b"), "g"): int, Inclusive("c", "g"): int},
    "exclusive": {Exclusive(Any("a", "b"), "g"): int, Exclusive("c", "g"): int},
    "exclusive_required": {
        Exclusive(Any("a", "b"), "g", required=True): int,
        Exclusive("c", "g", required=True): int,
    },
    "inclusive_three_members": {
        Inclusive(Any("a", "b"), "g"): int,
        Inclusive("c", "g"): int,
        Inclusive("d", "g"): int,
    },
    "inclusive_lone_member": {Inclusive(Any("a", "b"), "g"): int},
}


@pytest.mark.parametrize("slots", _ANY_GROUP_SCHEMAS.values(), ids=_ANY_GROUP_SCHEMAS)
def test_a_group_keyed_on_an_any_agrees_with_the_schema(slots: dict) -> None:
    """The emitted document accepts and rejects exactly what the mapping does."""
    schema = Schema(slots)
    validator = jsonschema.Draft202012Validator(to_json_schema(schema))

    names = ["a", "b", "c", "d"]
    for size in range(len(names) + 1):
        for combination in itertools.combinations(names, size):
            value = dict.fromkeys(combination, 1)
            try:
                schema(dict(value))
                accepts = True
            except Invalid:
                accepts = False
            assert validator.is_valid(value) is accepts, value


@pytest.mark.parametrize(
    ("validator", "expected"),
    [
        pytest.param(
            AtLeastOne("a", "b"),
            {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]},
            id="at_least_one",
        ),
        pytest.param(
            ExactlyOne("a", "b"),
            {"oneOf": [{"required": ["a"]}, {"required": ["b"]}]},
            id="exactly_one",
        ),
        pytest.param(
            AtMostOne("a", "b"),
            {"not": {"anyOf": [{"required": ["a", "b"]}]}},
            id="at_most_one",
        ),
        pytest.param(
            AllOrNone("a", "b"),
            {"dependentRequired": {"a": ["b"], "b": ["a"]}},
            id="all_or_none",
        ),
        pytest.param(AtMostOne("a"), {}, id="at_most_one_constrains_nothing_alone"),
        pytest.param(AllOrNone("a"), {}, id="all_or_none_constrains_nothing_alone"),
    ],
)
def test_key_presence_rules_reach_the_document(
    validator: object, expected: dict[str, object]
) -> None:
    """A rule beside the mapping is rendered, not dropped.

    Losing one leaves a document that accepts combinations the schema rejects,
    which is the wrong direction for a constraint to go missing in.
    """
    base = Schema({Optional("a"): str, Optional("b"): str})
    rendered = to_json_schema(Schema(All(validator, base)))

    assert {key: rendered[key] for key in expected} == expected


@pytest.mark.parametrize(
    ("validator", "expected"),
    [
        pytest.param(
            RequiredWith("a", "b"),
            {"dependentRequired": {"a": ["b"]}},
            id="required_with_one_trigger",
        ),
        pytest.param(
            RequiredWith(["a", "b"], "c", mode="all"),
            {
                "anyOf": [
                    {"not": {"required": ["a", "b"]}},
                    {"required": ["c"]},
                ],
            },
            id="required_with_every_trigger",
        ),
        pytest.param(
            RequiredWithout("a", "b"),
            {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]},
            id="required_without",
        ),
        pytest.param(
            RequiredIf({"a": "x"}, "b"),
            {
                "anyOf": [
                    {"not": {"properties": {"a": {"const": "x"}}, "required": ["a"]}},
                    {"required": ["b"]},
                ],
            },
            id="required_if",
        ),
    ],
)
def test_conditional_required_rules_reach_the_document(
    validator: object, expected: dict[str, object]
) -> None:
    """A rule that makes one key depend on another is rendered, not dropped.

    An implication is spelled with ``anyOf``/``not`` rather than ``if``/``then``
    so the same shape serves OpenAPI 3.0, which has the first and not the second.
    """
    base = Schema({Optional(name): str for name in ("a", "b", "c")})
    rendered = to_json_schema(Schema(All(validator, base)))

    assert {key: rendered[key] for key in expected} == expected


@pytest.mark.parametrize(
    ("validator", "expected"),
    [
        pytest.param(
            All(EnsureList(), [int]),
            {
                "anyOf": [
                    {"type": "integer"},
                    {"type": "null"},
                    {"type": "array", "items": {"type": "integer"}},
                ],
            },
            id="scalar_and_null_beside_the_list",
        ),
        pytest.param(
            All(EnsureList(), [int], Length(min=1)),
            {
                "anyOf": [
                    {"type": "integer"},
                    {"type": "array", "items": {"type": "integer"}, "minItems": 1},
                ],
            },
            id="a_non_empty_list_takes_no_null",
        ),
        pytest.param(
            All(EnsureList(), [int], Length(min=2)),
            {"type": "array", "items": {"type": "integer"}, "minItems": 2},
            id="no_unwrapped_value_fits",
        ),
        pytest.param(
            All(EnsureList(), [int], Length(max=0)),
            {
                "anyOf": [
                    {"type": "null"},
                    {"type": "array", "items": {"type": "integer"}, "maxItems": 0},
                ],
            },
            id="only_null_fits",
        ),
        pytest.param(
            All(int, EnsureList()),
            {"type": "integer"},
            id="a_trailing_ensure_list_wraps_the_output",
        ),
        pytest.param(
            All(EnsureList(), list),
            {
                "anyOf": [
                    {"allOf": [{"not": {"type": "array"}}, {"not": {"type": "null"}}]},
                    {"type": "null"},
                    {"type": "array"},
                ],
            },
            id="a_list_of_no_particular_thing_rules_out_what_it_must",
        ),
        pytest.param(
            All(EnsureList(), [int, str]),
            {
                "anyOf": [
                    {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                    {"type": "null"},
                    {
                        "type": "array",
                        "items": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                    },
                ],
            },
            id="a_union_item_is_read_branch_by_branch",
        ),
        pytest.param(
            All(EnsureList(), [[int], int]),
            {
                "anyOf": [
                    {
                        "allOf": [
                            {
                                "anyOf": [
                                    {"type": "array", "items": {"type": "integer"}},
                                    {"type": "integer"},
                                ],
                            },
                            {"not": {"type": "array"}},
                            {"not": {"type": "null"}},
                        ],
                    },
                    {"type": "null"},
                    {
                        "type": "array",
                        "items": {
                            "anyOf": [
                                {"type": "array", "items": {"type": "integer"}},
                                {"type": "integer"},
                            ],
                        },
                    },
                ],
            },
            id="a_union_item_that_may_be_a_list_rules_it_out",
        ),
        pytest.param(
            All(EnsureList(), [[int]]),
            {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "integer"}},
                    },
                ],
            },
            id="a_list_of_lists_has_no_scalar_form",
        ),
        pytest.param(
            All(EnsureList(), [int], Contains(5)),
            {
                "anyOf": [
                    {"allOf": [{"type": "integer"}, {"const": 5}]},
                    {
                        "type": "array",
                        "items": {"type": "integer"},
                        "contains": {"const": 5},
                    },
                ],
            },
            id="contains_constrains_the_scalar_and_drops_null",
        ),
    ],
)
def test_a_leading_ensure_list_offers_what_it_wraps(
    validator: object, expected: dict[str, object]
) -> None:
    """EnsureList takes a scalar or None, so the document has to say so.

    Offering only the array is narrower than the schema and rejects input it
    accepts. A trailing EnsureList is a different schema: the members before it
    judge the value unwrapped, so only that form is on offer.

    A list is passed through rather than wrapped and None becomes the empty
    list, so the scalar branch rules both out, spelled only where the item does
    not rule them out already. A list of lists has no scalar form at all. Under
    ``contains`` the one-item list has to carry the sought item itself, so the
    scalar branch takes that on and the empty list is no longer allowed.
    """
    assert to_json_schema(Schema(validator)) == expected


def test_a_leading_ensure_list_is_not_a_loss_when_it_renders() -> None:
    """Its meaning is the extra branches, so strict has nothing to report.

    Converting it as an ordinary part would call it unrepresentable and refuse
    a document the codec can in fact produce.
    """
    schema = Schema(All(EnsureList(), [int]))

    assert to_json_schema(schema, strict=True) == {
        "anyOf": [
            {"type": "integer"},
            {"type": "null"},
            {"type": "array", "items": {"type": "integer"}},
        ],
    }


def test_an_unconstrained_ensure_list_loses_nothing() -> None:
    """An open document already accepts everything the wrapping takes."""
    assert to_json_schema(Schema(All(EnsureList())), strict=True) == {}


def test_a_leading_ensure_list_under_a_whole_list_assertion_is_a_loss() -> None:
    """An assertion about the list as a whole is not a rule a branch can carry.

    ``Equal([1])`` pins the list itself, so a scalar branch read off the items
    alone would accept a value the schema rejects.
    """
    from probatio.error import SchemaError  # noqa: PLC0415

    schema = Schema(All(EnsureList(), [int], Equal([1])))

    assert to_json_schema(schema) == {}
    with pytest.raises(SchemaError, match="cannot represent"):
        to_json_schema(schema, strict=True)


def test_a_leading_ensure_list_over_a_counted_contains_is_a_loss() -> None:
    """How many items must match is a sum over the list, not a per-branch rule."""
    from probatio import UNSUPPORTED  # noqa: PLC0415
    from probatio.error import SchemaError  # noqa: PLC0415

    inner = [int]

    def hook(node: object) -> object:
        if node is not inner:
            return UNSUPPORTED
        return {
            "type": "array",
            "items": {"type": "integer"},
            "contains": {"const": 9},
            "minContains": 0,
        }

    schema = Schema(All(EnsureList(), inner))

    assert to_json_schema(schema, custom_serializer=hook) == {}
    with pytest.raises(SchemaError, match="cannot represent"):
        to_json_schema(schema, strict=True, custom_serializer=hook)


def test_a_leading_ensure_list_over_an_unreadable_items_is_a_loss() -> None:
    """A hook may render items as something this cannot read, and that is a loss too."""
    from probatio import UNSUPPORTED  # noqa: PLC0415
    from probatio.error import SchemaError  # noqa: PLC0415

    inner = [int]

    def hook(node: object) -> object:
        return {"type": "array", "items": "anything"} if node is inner else UNSUPPORTED

    schema = Schema(All(EnsureList(), inner))

    assert "anyOf" not in to_json_schema(schema, custom_serializer=hook)
    with pytest.raises(SchemaError, match="cannot represent"):
        to_json_schema(schema, strict=True, custom_serializer=hook)


def test_a_leading_ensure_list_over_a_sequence_is_a_loss() -> None:
    """Positional items are a shape the branches cannot be read off, so strict says so.

    Bounds that leave no room are a different answer: the array then says
    everything on its own and nothing is lost, so strict stays quiet.
    """
    from probatio.error import SchemaError  # noqa: PLC0415

    unreadable = Schema(All(EnsureList(), ExactSequence([int])))
    assert "anyOf" not in to_json_schema(unreadable)
    with pytest.raises(SchemaError, match="cannot represent"):
        to_json_schema(unreadable, strict=True)

    exact = Schema(All(EnsureList(), [int], Length(min=2)))
    assert to_json_schema(exact, strict=True) == {
        "type": "array",
        "items": {"type": "integer"},
        "minItems": 2,
    }


def test_a_conditional_rule_names_each_key_once() -> None:
    """A ``required`` array holds unique names, so a repeated key is folded."""
    base = Schema({Optional(name): str for name in ("a", "b")})

    rendered = to_json_schema(Schema(All(RequiredWith(["a", "a"], "b", "b"), base)))

    assert rendered["dependentRequired"] == {"a": ["b"]}


def test_one_trigger_collapses_whatever_the_mode() -> None:
    """With a single trigger the two modes say the same thing, so both collapse."""
    base = Schema({Optional(name): str for name in ("a", "b")})

    for mode in ("any", "all"):
        rendered = to_json_schema(
            Schema(All(RequiredWith("a", "b", mode=mode), base)),
        )
        assert rendered["dependentRequired"] == {"a": ["b"]}


@pytest.mark.parametrize(
    "validator",
    [
        pytest.param(RequiredIf({"a": object()}, "b"), id="compared_value"),
        pytest.param(RequiredIf({"a": (1, 2)}, "b"), id="value_json_cannot_match"),
        pytest.param(RequiredIf({1: "x"}, "b"), id="condition_key"),
        pytest.param(RequiredWith("a", 1), id="required_key"),
        pytest.param(RequiredWith(1, "b"), id="trigger_key"),
        pytest.param(RequiredWith("a"), id="no_required_keys"),
    ],
)
def test_a_conditional_rule_without_a_json_spelling_still_widens(
    validator: object,
) -> None:
    """A rule with no faithful JSON form is left out of the document.

    That covers a key JSON cannot name, a value it cannot hold, a value whose
    JSON form compares unequal to the original (``(1, 2)`` renders as
    ``[1, 2]``, which the tuple never equals, so emitting it would make the
    document fire where Probatio does not), and a rule requiring no keys at all.
    Widening is the documented default for all of them, and ``strict=True`` is
    what turns it into an error.
    """
    from probatio.error import SchemaError  # noqa: PLC0415

    schema = Schema(All(validator, Schema({Optional("a"): str})))
    rendered = to_json_schema(schema)

    assert "anyOf" not in rendered
    assert "dependentRequired" not in rendered
    with pytest.raises(SchemaError, match="cannot represent"):
        to_json_schema(schema, strict=True)


def test_a_key_presence_rule_on_unnameable_keys_still_widens() -> None:
    """A key that is not a plain string has no spelling here, so strict reports it."""
    from probatio.error import SchemaError  # noqa: PLC0415

    schema = Schema(All(AtLeastOne(1, 2), Schema({Optional("a"): str})))

    assert "anyOf" not in to_json_schema(schema)
    with pytest.raises(SchemaError, match="cannot represent"):
        to_json_schema(schema, strict=True)


def test_inclusive_group_keyed_on_an_any_renders_an_implication_per_member() -> None:
    """dependentRequired cannot say "one of those", so the group renders as allOf."""
    result = to_json_schema(Schema(_ANY_GROUP_SCHEMAS["inclusive"]))

    either = {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]}
    assert "dependentRequired" not in result
    assert result["allOf"] == [
        {"anyOf": [{"not": either}, {"required": ["c"]}]},
        {"anyOf": [{"not": {"required": ["c"]}}, either]},
    ]


def test_exclusive_group_keyed_on_an_any_excludes_the_other_members() -> None:
    """The Any key is one member, so its own names never collide with each other."""
    result = to_json_schema(Schema(_ANY_GROUP_SCHEMAS["exclusive"]))

    either = {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]}
    assert result["allOf"] == [
        {"not": {"anyOf": [{"allOf": [either, {"required": ["c"]}]}]}},
    ]


def test_required_exclusive_group_keyed_on_an_any_demands_one_member() -> None:
    """Exactly one member, where either of the Any's names satisfies its own."""
    result = to_json_schema(Schema(_ANY_GROUP_SCHEMAS["exclusive_required"]))

    assert result["allOf"] == [
        {
            "oneOf": [
                {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]},
                {"required": ["c"]},
            ],
        },
    ]


def test_a_lone_group_member_adds_no_constraint() -> None:
    """A group of one has nothing to be co-dependent with."""
    result = to_json_schema(Schema(_ANY_GROUP_SCHEMAS["inclusive_lone_member"]))
    assert "allOf" not in result
    assert "dependentRequired" not in result


# A name an ``Any`` key lists can belong to another key: the engine matches a
# literal key first whatever the order, so the ``Any`` never sees that name. A
# presence rule written over it would disagree with validation, so none is written.
_CONTESTED_SCHEMAS = {
    "required_any_over_a_literal": {Required(Any("a", "b")): int, "a": int},
    "group_over_a_literal": {
        Inclusive(Any("a", "b"), "g"): int,
        "a": int,
        Inclusive("c", "g"): int,
    },
    "two_any_keys_sharing_a_name": {
        Inclusive(Any("a", "b"), "g"): int,
        Any("b", "c"): int,
        Inclusive("d", "g"): int,
    },
    # A variable key matches by shape, so it can take any name; whether it gets
    # there first is declaration order, which the codec does not model.
    "a_variable_key_first": {
        str: int,
        Inclusive(Any("a", "b"), "g"): int,
        Inclusive("c", "g"): int,
    },
    "a_variable_key_last": {
        Inclusive(Any("a", "b"), "g"): int,
        Inclusive("c", "g"): int,
        str: int,
    },
    # An Alias accepts its value under any of its names, one of which is "b".
    "an_alias_sharing_a_name": {Required(Any("a", "b")): int, Alias("z", "b"): int},
}


@pytest.mark.parametrize("slots", _CONTESTED_SCHEMAS.values(), ids=_CONTESTED_SCHEMAS)
def test_a_contested_name_never_narrows_the_document(slots: dict) -> None:
    """The document still accepts everything the mapping accepts, constraint or not."""
    schema = Schema(slots)
    validator = jsonschema.Draft202012Validator(to_json_schema(schema))

    names = ["a", "b", "c", "d"]
    for size in range(len(names) + 1):
        for combination in itertools.combinations(names, size):
            value = dict.fromkeys(combination, 1)
            try:
                schema(dict(value))
            except Invalid:
                continue
            # Widening is safe and expected here; rejecting what the mapping takes
            # is not, and is what writing the rule anyway would have caused.
            assert validator.is_valid(value), value


def test_a_contested_any_key_writes_no_presence_rule() -> None:
    """A name a literal key also declares carries no at-least-one constraint."""
    result = to_json_schema(Schema(_CONTESTED_SCHEMAS["required_any_over_a_literal"]))
    assert "allOf" not in result
    assert sorted(result["properties"]) == ["a", "b"]


@pytest.mark.parametrize(
    ("slots", "reason"),
    [
        (
            {
                Exclusive(Any("a", "b"), "g"): int,
                "a": int,
                Exclusive("c", "g", required=True): int,
            },
            "contested",
        ),
        (
            {Exclusive(str, "g"): int, Exclusive("c", "g", required=True): int},
            "variable",
        ),
        (
            {
                Inclusive(Any("a", "b"), "g"): int,
                "a": int,
                Inclusive("c", "g"): int,
                Inclusive("d", "g"): int,
            },
            "inclusive",
        ),
    ],
    ids=["contested_exclusive", "variable_exclusive", "contested_inclusive"],
)
def test_a_group_losing_a_member_renders_nothing(slots: dict, reason: str) -> None:
    """A group is all its members or none, so one it cannot write drops the rule."""
    assert reason  # the id carries why the member is unrenderable
    result = to_json_schema(Schema(slots))

    # Rendering the remaining members would demand one of them, rejecting input
    # the mapping accepts through the member that could not be written.
    assert "allOf" not in result
    assert "dependentRequired" not in result


def test_an_empty_group_name_is_still_a_group() -> None:
    """An empty string names a group like any other, so a lost member abandons it."""
    result = to_json_schema(
        Schema(
            {
                Inclusive(Any("a", "b"), ""): int,
                "a": int,
                Inclusive("c", ""): int,
                Inclusive("d", ""): int,
            }
        )
    )
    assert "dependentRequired" not in result
    assert "allOf" not in result


def test_a_non_string_literal_key_contests_nothing() -> None:
    """An int key matches no JSON property name, so it takes none from an Any."""
    result = to_json_schema(Schema({Required(Any("a", "b")): int, 1: int}))
    assert result["allOf"] == [
        {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]},
    ]


def test_an_alias_contests_its_canonical_name() -> None:
    """A strict Alias still takes its canonical name, then refuses it."""
    result = to_json_schema(
        Schema(
            {
                Required(Any("a", "z")): int,
                Alias("z", "b", accept_canonical=False): int,
            }
        )
    )
    assert "allOf" not in result


def test_extra_never_contests_a_name() -> None:
    """Extra catches only what nothing else matched, so it takes no name first."""
    result = to_json_schema(Schema({Required(Any("a", "b")): int, Extra: object}))
    assert result["allOf"] == [
        {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]},
    ]


@pytest.mark.parametrize(
    "slots",
    [
        _CONTESTED_SCHEMAS["required_any_over_a_literal"],
        _CONTESTED_SCHEMAS["group_over_a_literal"],
        _CONTESTED_SCHEMAS["a_variable_key_first"],
    ],
    ids=["required", "grouped", "variable_key"],
)
def test_strict_refuses_to_drop_a_contested_rule(slots: dict) -> None:
    """Dropping the rule widens the document, which strict mode exists to refuse."""
    from probatio.error import SchemaError  # noqa: PLC0415

    assert to_json_schema(Schema(slots)) is not None
    with pytest.raises(SchemaError, match="another key can also match"):
        to_json_schema(Schema(slots), strict=True)


def test_a_contested_group_member_writes_no_group_rule() -> None:
    """A group member sharing a name with another key adds no object-level rule."""
    result = to_json_schema(Schema(_CONTESTED_SCHEMAS["group_over_a_literal"]))
    assert "allOf" not in result
    assert "dependentRequired" not in result


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


def test_default_to_exports_a_callable_default() -> None:
    """A callable default is called, so the annotation carries the value it makes."""
    from probatio.validators import DefaultTo  # noqa: PLC0415

    assert to_json_schema(Schema(DefaultTo(list))) == {"default": []}


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


def test_type_key_emits_no_property_names() -> None:
    """A plain str key accepts every JSON key, so it adds no propertyNames noise."""
    assert "propertyNames" not in to_json_schema(Schema({str: int}))


def test_restrictive_key_validator_becomes_property_names() -> None:
    """A key validator is a real constraint; dropping it would widen the schema."""
    encoded = to_json_schema(Schema({In(["a", "b"]): str}))
    assert encoded["propertyNames"] == {"enum": ["a", "b"]}


def test_several_restrictive_key_validators_merge_into_any_of() -> None:
    """The engine accepts a key matching any variable key, so they merge as anyOf."""
    encoded = to_json_schema(Schema({In(["a"]): str, Match(r"^x"): int}))
    assert encoded["propertyNames"] == {
        "anyOf": [{"enum": ["a"]}, {"type": "string", "pattern": "^x"}],
    }


def test_one_open_key_validator_drops_property_names() -> None:
    """A str key alongside a restrictive one accepts everything, so nothing is emitted."""
    assert "propertyNames" not in to_json_schema(Schema({In(["a"]): str, str: int}))


def test_property_names_is_dropped_beside_a_declared_property() -> None:
    """Emitting it there would narrow: JSON Schema applies it to declared names too.

    A probatio literal key is matched ahead of the variable keys and never sees
    them, so ``{In(["a"]): str, "x": int}`` accepts ``{"x": 1}``. A document
    carrying propertyNames would reject it, which is a narrowing; dropping the
    keyword widens instead.
    """
    encoded = to_json_schema(Schema({In(["a"]): str, "x": int}))
    assert "propertyNames" not in encoded
    assert encoded["properties"] == {"x": {"type": "integer"}}


def test_coercing_key_validator_emits_no_property_names() -> None:
    """A key rendering as a non-string type would reject every JSON property name."""
    encoded = to_json_schema(Schema({Coerce(int): str}))
    assert "propertyNames" not in encoded


def test_non_string_enum_key_emits_no_property_names() -> None:
    """An enum key of non-strings cannot match a property name, so it is dropped."""
    assert "propertyNames" not in to_json_schema(Schema({In([1, 2]): str}))


def test_non_string_const_key_emits_no_property_names() -> None:
    """A const key of a non-string cannot match a property name either."""
    assert "propertyNames" not in to_json_schema(Schema({Equal(1): str}))


def test_string_const_key_becomes_property_names() -> None:
    """A const key of a string does match a property name, so it is emitted."""
    assert to_json_schema(Schema({Equal("a"): str}))["propertyNames"] == {"const": "a"}


def test_strict_refuses_a_key_validator_beside_a_declared_property() -> None:
    """Dropping the key constraint widens, and strict mode exists to refuse that."""
    from probatio.error import SchemaError  # noqa: PLC0415

    schema = Schema({In(["a"]): str, "x": int})
    assert "propertyNames" not in to_json_schema(schema)
    with pytest.raises(SchemaError, match="key validator"):
        to_json_schema(schema, strict=True)


def test_strict_refuses_a_key_validator_that_cannot_match_a_name() -> None:
    """A coercing key has no property-name form, so strict mode refuses the drop."""
    from probatio.error import SchemaError  # noqa: PLC0415

    schema = Schema({Coerce(int): str})
    assert "propertyNames" not in to_json_schema(schema)
    with pytest.raises(SchemaError, match="key validator"):
        to_json_schema(schema, strict=True)


def test_strict_still_allows_an_open_string_key() -> None:
    """A plain str key constrains nothing, so there is no constraint to refuse."""
    assert "propertyNames" not in to_json_schema(Schema({str: int}), strict=True)


def test_conjunction_key_needs_every_branch_to_match_a_name() -> None:
    """allOf holds every branch at once, so one string branch is not enough.

    ``All(str, Coerce(int))`` accepts the key "1" by coercing it, and renders as an
    ``allOf`` of a string and an integer. Emitting that as propertyNames would
    describe a key nothing can be, rejecting every object the mapping accepts.
    """
    encoded = to_json_schema(Schema({All(str, Coerce(int)): str}))
    assert "propertyNames" not in encoded


def test_union_key_needs_only_one_branch_to_match_a_name() -> None:
    """anyOf is satisfied by a single branch, so one string branch is enough."""
    encoded = to_json_schema(Schema({Any(In(["a"]), In(["b"])): str}))
    assert encoded["propertyNames"] == {"anyOf": [{"enum": ["a"]}, {"enum": ["b"]}]}


def test_open_mapping_with_a_partial_key_renders_open() -> None:
    """A name the key misses falls through to the policy and may take any value."""
    encoded = to_json_schema(Schema({int: int}, extra=ALLOW_EXTRA))
    assert encoded["additionalProperties"] is True


def test_open_mapping_with_a_str_key_keeps_its_value_schema() -> None:
    """A str key covers every property name, so the policy never comes into play."""
    encoded = to_json_schema(Schema({str: int}, extra=ALLOW_EXTRA))
    assert encoded["additionalProperties"] == {"type": "integer"}


def test_open_mapping_emits_no_property_names() -> None:
    """An open mapping accepts a key the validator rejects, so it cannot constrain."""
    assert "propertyNames" not in to_json_schema(
        Schema({In(["a"]): int}, extra=ALLOW_EXTRA)
    )


def test_one_universal_key_covers_every_name_for_an_open_mapping() -> None:
    """A str key beside a partial one still catches every name, so values stand."""
    encoded = to_json_schema(Schema({str: int, int: str}, extra=ALLOW_EXTRA))
    assert encoded["additionalProperties"] == {
        "anyOf": [{"type": "integer"}, {"type": "string"}]
    }


def test_unrepresentable_key_is_not_mistaken_for_a_universal_one() -> None:
    """A key with no JSON Schema form renders {} exactly as ``object`` does.

    So the rendering cannot answer whether the key covers every property name,
    and reading it as universal would keep a value schema the extra policy makes
    wrong: this mapping accepts ``{"b": None}`` through ALLOW_EXTRA.
    """

    from probatio import Invalid  # noqa: PLC0415

    def only_a(value: object) -> object:
        if value != "a":
            message = "only the key 'a'"
            raise Invalid(message)
        return value

    encoded = to_json_schema(Schema({only_a: int}, extra=ALLOW_EXTRA))
    assert encoded["additionalProperties"] is True


def test_extra_marker_key_is_universal() -> None:
    """Extra catches every unmatched key, so its value schema covers them all."""
    encoded = to_json_schema(Schema({Extra: int}, extra=ALLOW_EXTRA))
    assert encoded["additionalProperties"] == {"type": "integer"}


def test_strict_refuses_a_key_validator_on_an_open_mapping() -> None:
    """An open mapping cannot constrain its keys, and strict refuses the drop."""
    from probatio.error import SchemaError  # noqa: PLC0415

    schema = Schema({In(["a"]): int}, extra=ALLOW_EXTRA)
    assert "propertyNames" not in to_json_schema(schema)
    # Both the key constraint and the value schema are dropped here; the value
    # side is reported first, and either is a correct refusal.
    with pytest.raises(SchemaError, match="open mapping"):
        to_json_schema(schema, strict=True)


def test_transparent_wrapper_key_is_still_universal() -> None:
    """Msg only swaps the error message, so Msg(str, ...) matches every name."""
    from probatio import Msg  # noqa: PLC0415

    encoded = to_json_schema(Schema({Msg(str, "key"): int}, extra=ALLOW_EXTRA))
    assert encoded["additionalProperties"] == {"type": "integer"}


def test_a_schema_wrapped_key_is_still_universal() -> None:
    """Schema only compiles what it wraps, so Schema(str) matches every name.

    A bare Schema cannot be a mapping key (it is unhashable), but one inside a
    Msg can, which is the route that reaches this.
    """
    from probatio import Msg  # noqa: PLC0415

    encoded = to_json_schema(Schema({Msg(Schema(str), "key"): int}, extra=ALLOW_EXTRA))
    assert encoded["additionalProperties"] == {"type": "integer"}


def test_strict_refuses_a_dropped_value_schema_on_an_open_mapping() -> None:
    """A key that renders vacuous is still partial, and its values are dropped.

    ``All(object)`` matches every name but is not universal by identity, so the
    key schema reports nothing and only this path can report the value drop.
    """
    from probatio.error import SchemaError  # noqa: PLC0415

    schema = Schema({All(object): int}, extra=ALLOW_EXTRA)
    assert to_json_schema(schema)["additionalProperties"] is True
    with pytest.raises(SchemaError, match="value schema"):
        to_json_schema(schema, strict=True)


def test_strict_allows_a_drop_that_loses_nothing() -> None:
    """An accept-anything value is what additionalProperties true already says."""
    schema = Schema({All(object): object}, extra=ALLOW_EXTRA)
    assert to_json_schema(schema, strict=True)["additionalProperties"] is True


def test_a_wrapper_subclass_is_not_assumed_transparent() -> None:
    """A subclass can override __call__ to match far less than what it wraps.

    Unwrapping it would call the key universal and keep a value schema that
    rejects the keys the extra policy lets through.
    """
    from probatio import Invalid, Msg  # noqa: PLC0415

    class OnlyA(Msg):
        def __call__(self, value: object) -> object:
            if value != "a":
                message = "only the key 'a'"
                raise Invalid(message)
            return value

    encoded = to_json_schema(Schema({OnlyA(str, "only a"): int}, extra=ALLOW_EXTRA))
    assert encoded["additionalProperties"] is True


def test_strict_allows_a_universal_key_with_no_leaf_rendering() -> None:
    """Extra has no leaf form, but the mapping renders exactly as its values."""
    encoded = to_json_schema(Schema({Extra: int}), strict=True)
    assert encoded["additionalProperties"] == {"type": "integer"}
