"""Tests for to_field_list(): the voluptuous-serialize field-list shape.

The structural cases are differential-tested: the same schema is built in both
libraries, serialized by each, and the output compared. probatio.to_field_list must
match voluptuous-serialize so config-flow frontends and tool exporters work on
probatio schemas unchanged.
"""

from __future__ import annotations

import enum
from typing import Any

import pytest
import voluptuous
import voluptuous_serialize

import probatio
from probatio import (
    UNSUPPORTED,
    Alpha,
    AsDate,
    AsDatetime,
    AsTime,
    Base64,
    Duration,
    EnsureList,
    FromEpoch,
    HexInt,
    IPAddress,
    MultipleOf,
    NonEmpty,
    Optional,
    Percentage,
    Port,
    Required,
    Schema,
    Secret,
    to_field_list,
)
from probatio import Any as ProbAny


def mapping(lib: Any) -> Any:
    """A mapping exercising types, defaults, descriptions, In, All, and bounds."""
    return lib.Schema(
        {
            lib.Required("name"): str,
            lib.Optional("port", default=8080): lib.All(
                lib.Coerce(int),
                lib.Range(min=1, max=65535),
            ),
            lib.Optional("mode"): lib.In(["auto", "manual"]),
            lib.Optional("note", description="a note"): str,
            lib.Optional("count"): int,
            lib.Optional("label"): lib.All(str, lib.Length(min=1, max=20)),
        },
    )


def test_mapping_matches_voluptuous_serialize() -> None:
    """The field list matches voluptuous-serialize for a realistic mapping."""
    assert to_field_list(mapping(probatio)) == voluptuous_serialize.convert(
        mapping(voluptuous),
    )


def test_single_type_matches() -> None:
    """A bare type serializes to the same value dict as voluptuous-serialize."""
    assert to_field_list(Schema(str)) == voluptuous_serialize.convert(
        voluptuous.Schema(str),
    )


def test_datetime_matches() -> None:
    """A Datetime value serializes with type and format like the oracle."""
    assert to_field_list(Schema(probatio.Datetime())) == voluptuous_serialize.convert(
        voluptuous.Schema(voluptuous.Datetime()),
    )


def test_as_parsers_serialize_as_datetime_fields() -> None:
    """The As* parsers serialize as a datetime field; ISO carries no strptime format."""
    assert to_field_list(Schema(AsDate())) == {"type": "datetime"}
    assert to_field_list(Schema(AsTime())) == {"type": "datetime"}
    assert to_field_list(Schema(AsDatetime())) == {"type": "datetime"}


def test_as_parser_with_format_serializes_the_format() -> None:
    """An explicit strptime format is carried into the serialized datetime field."""
    assert to_field_list(Schema(AsDate(format="%d-%m-%Y"))) == {
        "type": "datetime",
        "format": "%d-%m-%Y",
    }


def test_epoch_serializes_as_a_float_field() -> None:
    """FromEpoch takes an int or fractional-second float, so it serializes as float."""
    assert to_field_list(Schema(FromEpoch())) == {"type": "float"}


def test_bare_key_is_not_optional() -> None:
    """A bare key is required:false with no optional flag, matching the oracle."""
    assert to_field_list(Schema({"x": int})) == voluptuous_serialize.convert(
        voluptuous.Schema({"x": int}),
    )


def test_any_value_serializes_first_option() -> None:
    """An Any value serializes using its first usable alternative."""
    assert to_field_list(Schema(ProbAny(int, str))) == {"type": "integer"}


def test_coerce_of_non_type_is_open() -> None:
    """Coerce of a non-type callable serializes to an open dict."""
    assert to_field_list(Schema(probatio.Coerce(str.strip))) == {}


@pytest.mark.parametrize("value", [5, "abc", 3.14, True])
def test_literal_value_serializes_as_a_constant(value: object) -> None:
    """A literal mapping value renders as a constant field, like the oracle."""
    assert to_field_list(
        Schema({Required("n"): value})
    ) == voluptuous_serialize.convert(
        voluptuous.Schema({voluptuous.Required("n"): value}),
    )


def test_bare_literal_serializes_as_a_constant() -> None:
    """A bare literal schema renders as a constant value, like the oracle."""
    assert to_field_list(Schema(5)) == voluptuous_serialize.convert(
        voluptuous.Schema(5)
    )


def test_unsupported_value_raises() -> None:
    """An un-serializable value raises, matching voluptuous-serialize."""
    with pytest.raises(ValueError, match="unable to serialize"):
        to_field_list(Schema([str]))


def test_unhashable_callable_value_raises_cleanly() -> None:
    """An unhashable callable value raises ValueError, not a leaked TypeError."""

    class _Unhashable:
        __hash__ = None

        def __call__(self, value: Any) -> Any:
            return value

    with pytest.raises(ValueError, match="unable to serialize"):
        to_field_list(Schema({Required("k"): _Unhashable()}))


def test_custom_serializer_overrides_and_defers() -> None:
    """A custom serializer can override a node or defer with UNSUPPORTED."""
    sentinel = object()

    def custom(node: Any) -> Any:
        if node is sentinel:
            return {"type": "custom"}
        return UNSUPPORTED

    schema = Schema({Optional("a"): sentinel, Optional("b"): int})
    result = to_field_list(schema, custom_serializer=custom)

    by_name = {field["name"]: field for field in result}
    assert by_name["a"]["type"] == "custom"
    assert by_name["b"]["type"] == "integer"


def test_unsupported_repr() -> None:
    """The UNSUPPORTED sentinel renders clearly in debug output."""
    assert repr(UNSUPPORTED) == "UNSUPPORTED"


def test_serialize_accepts_a_raw_schema_node() -> None:
    """serialize works on a bare schema node, not only on a Schema instance."""
    assert to_field_list({"x": int}) == voluptuous_serialize.convert(
        voluptuous.Schema({"x": int}),
    )


def test_unsupported_type_raises() -> None:
    """A type with no serialize mapping raises, like an unknown value."""
    with pytest.raises(ValueError, match="unable to serialize"):
        to_field_list(Schema(dict))


def test_any_skips_empty_alternatives() -> None:
    """Any skips alternatives that serialize to an empty dict, using the next."""
    schema = Schema(ProbAny(probatio.Coerce(str.strip), int))
    assert to_field_list(schema) == {"type": "integer"}


def test_any_of_only_open_alternatives_is_open() -> None:
    """Any of only open alternatives serializes to an open dict."""
    assert to_field_list(Schema(ProbAny(probatio.Coerce(str.strip)))) == {}


def test_range_one_sided_bounds() -> None:
    """Range with a single bound emits only that bound."""
    assert to_field_list(Schema(probatio.Range(min=1))) == {"valueMin": 1}
    assert to_field_list(Schema(probatio.Range(max=9))) == {"valueMax": 9}


def test_clamp_serializes_like_voluptuous_serialize() -> None:
    """Clamp emits valueMin/valueMax, matching voluptuous-serialize."""
    schema = Schema(probatio.Clamp(min=0, max=5))
    assert to_field_list(schema) == {"valueMin": 0, "valueMax": 5}
    assert to_field_list(schema) == voluptuous_serialize.convert(
        voluptuous.Schema(voluptuous.Clamp(min=0, max=5)),
    )


def test_length_one_sided_bounds() -> None:
    """Length with a single bound emits only that bound."""
    assert to_field_list(Schema(probatio.Length(min=1))) == {"lengthMin": 1}
    assert to_field_list(Schema(probatio.Length(max=9))) == {"lengthMax": 9}


def test_new_validators_serialize_to_fields() -> None:
    """The probatio-only validators serialize to frontend fields instead of raising."""
    fields = to_field_list(
        Schema(
            {
                Required("ip"): IPAddress(),
                Required("port"): Port(),
                Required(Secret("pw")): str,
                Required("pct"): Percentage(),
            },
        ),
    )

    by_name = {field["name"]: field for field in fields}
    assert by_name["ip"]["type"] == "string"
    assert by_name["port"] == {
        "type": "integer",
        "valueMin": 1,
        "valueMax": 65535,
        "name": "port",
        "required": True,
    }
    assert by_name["pw"]["type"] == "string"
    assert by_name["pw"]["secret"] is True
    assert by_name["pct"]["type"] == "float"


@pytest.mark.parametrize(
    "validator", [MultipleOf(5), Duration(), EnsureList(), HexInt()]
)
def test_validators_without_a_frontend_shape_serialize_empty(validator: object) -> None:
    """A validator with no field-list equivalent serializes to an empty value, not an error."""
    field = to_field_list(Schema({Optional("v"): validator}))[0]
    assert field["name"] == "v"


def test_string_and_no_shape_validators_serialize() -> None:
    """The new string validators serialize to a string field, and NonEmpty to empty."""
    fields = to_field_list(
        Schema(
            {Required("a"): Alpha(), Required("b"): Base64(), Required("c"): NonEmpty()}
        ),
    )

    by_name = {field["name"]: field for field in fields}
    assert by_name["a"]["type"] == "string"
    assert by_name["b"]["type"] == "string"
    assert "type" not in by_name["c"]


class _Color(enum.Enum):
    """A small enum shared by both libraries in the parity cases.

    The member values differ from the lowercased names on purpose, so the select
    options pin ``member.value`` and not ``member.name.lower()``.
    """

    RED = "r"
    GREEN = "green"


def _parity_build(lib: Any) -> dict[str, Any]:
    """Schemas exercising the constructs serialize must match the oracle on."""
    req, opt = lib.Required, lib.Optional
    return {
        "in_dict": {req("k"): lib.In({"x": "X", "y": "Y"})},
        "in_list": {req("k"): lib.In(["a", "b"])},
        "email": {req("k"): lib.Email},
        "url": {req("k"): lib.Url},
        "fqdnurl": {req("k"): lib.FqdnUrl},
        "lower": {req("k"): lib.Lower},
        "upper": {req("k"): lib.Upper},
        "capitalize": {req("k"): lib.Capitalize},
        "title": {req("k"): lib.Title},
        "strip": {req("k"): lib.Strip},
        "maybe": {req("k"): lib.Maybe(int)},
        "any_none_first": {req("k"): lib.Any(None, str)},
        "enum_class": {req("k"): _Color},
        "coerce_enum": {req("k"): lib.Coerce(_Color)},
        "coerce_int": {req("k"): lib.Coerce(int)},
        "empty_description": {opt("k", description=""): int},
        "none_description": {opt("k", description=None): int},
    }


@pytest.mark.parametrize("case", list(_parity_build(voluptuous)))
def test_serialize_matches_voluptuous_serialize(case: str) -> None:
    """serialize matches voluptuous-serialize byte for byte across these constructs."""
    got = to_field_list(Schema(_parity_build(probatio)[case]))
    want = voluptuous_serialize.convert(
        voluptuous.Schema(_parity_build(voluptuous)[case])
    )

    assert got == want


def test_serialize_marks_allow_none_for_either_any_order() -> None:
    """A nullable ``Any`` serializes to allow_none whether None is first or last.

    voluptuous-serialize only handled ``Any(None, X)``; probatio also recognizes
    ``Any(X, None)`` as the same nullable shape rather than dropping the None.
    """
    assert to_field_list(Schema(ProbAny(None, str))) == {
        "type": "string",
        "allow_none": True,
    }
    assert to_field_list(Schema(ProbAny(str, None))) == {
        "type": "string",
        "allow_none": True,
    }
