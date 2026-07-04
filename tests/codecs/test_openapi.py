"""Tests for to_openapi(): the voluptuous-openapi convert() shape.

These are differential: the same schema is built in both libraries, converted by
each (in both OpenAPI 3.0 and 3.1 modes), and the output compared. to_openapi must
match voluptuous-openapi so LLM tool calling and MCP consumers work on probatio
schemas unchanged.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, TypeVar

import pytest
import voluptuous
import voluptuous_openapi
from voluptuous_openapi import OpenApiVersion

import probatio
from probatio import (
    UNSUPPORTED,
    UUID,
    Alpha,
    AsDate,
    AsDatetime,
    AsTime,
    Base64,
    Date,
    Fqdn,
    FromEpoch,
    Hostname,
    IPAddress,
    IPv4Address,
    IPv6Address,
    MultipleOf,
    Percentage,
    Port,
    Schema,
    Secret,
    Slug,
    Time,
    to_openapi,
)
from tests.strategies import canonical_openapi

_ORACLE_VERSION = {"3.0": OpenApiVersion.V3, "3.1.0": OpenApiVersion.V3_1}


class Color(Enum):
    """A string-valued enum, exercised by both libraries identically."""

    RED = "red"
    BLUE = "blue"


def build(lib: Any) -> dict[str, Any]:
    """Build a matrix of equivalent schemas, keyed by case name, in one library."""
    return {
        "str": lib.Schema(str),
        "int": lib.Schema(int),
        "float": lib.Schema(float),
        "bool": lib.Schema(bool),
        "none": lib.Schema(None),
        "datetime": lib.Schema(lib.Datetime()),
        "email": lib.Schema(lib.Email),
        "url": lib.Schema(lib.Url),
        "fqdnurl": lib.Schema(lib.FqdnUrl),
        "in_str": lib.Schema(lib.In(["a", "b"])),
        "in_int": lib.Schema(lib.In([1, 2])),
        "range": lib.Schema(lib.All(int, lib.Range(min=1, max=10))),
        "range_excl": lib.Schema(
            lib.All(
                int, lib.Range(min=1, max=10, min_included=False, max_included=False)
            ),
        ),
        "clamp": lib.Schema(lib.All(int, lib.Clamp(min=0, max=9))),
        "length": lib.Schema(lib.All(str, lib.Length(min=1, max=5))),
        "match": lib.Schema(lib.Match(r"^\d+$")),
        "coerce_int": lib.Schema(lib.Coerce(int)),
        "coerce_float": lib.Schema(lib.Coerce(float)),
        "any": lib.Schema(lib.Any(int, str)),
        "any_none": lib.Schema(lib.Any(int, None)),
        "any_three": lib.Schema(lib.Any(int, str, None)),
        "maybe": lib.Schema(lib.Maybe(int)),
        "range_min_only": lib.Schema(lib.All(int, lib.Range(min=1))),
        "range_max_only": lib.Schema(lib.All(int, lib.Range(max=10))),
        "length_min_only": lib.Schema(lib.All(str, lib.Length(min=1))),
        "length_max_only": lib.Schema(lib.All(str, lib.Length(max=5))),
        "all_merge": lib.Schema(lib.All(str, lib.Length(min=1))),
        "all_conflict": lib.Schema(lib.All(lib.Range(min=1), lib.Length(min=2))),
        "all_dup": lib.Schema(lib.All(int, int)),
        "all_open": lib.Schema(lib.All(dict, int)),
        "all_fallback": lib.Schema(lib.All(lib.Range(min=1), lib.Range(min=2))),
        "any_nested": lib.Schema(lib.Any(lib.Any(int, str), float)),
        "any_open": lib.Schema(lib.Any(dict, int)),
        "any_open_nullable": lib.Schema(lib.Any(dict, int, None)),
        "any_dup": lib.Schema(lib.Any(int, int)),
        "any_type_then_maybe": lib.Schema(lib.Any(int, lib.Maybe(int))),
        "any_maybe_then_type": lib.Schema(lib.Any(lib.Maybe(int), int)),
        "any_nested_nullable": lib.Schema(lib.Any(lib.Any(int, str, None), bool)),
        "any_enum_nullable_merge": lib.Schema(
            lib.Any(lib.In([0]), lib.Maybe(lib.In([1])))
        ),
        "in_none": lib.Schema(lib.In(["a", None])),
        "literal_str": lib.Schema("on"),
        "literal_int": lib.Schema(5),
        "list": lib.Schema([int]),
        "bare_dict": lib.Schema(dict),
        "bare_list": lib.Schema(list),
        "generic_list": lib.Schema(list[int]),
        "generic_set": lib.Schema(set[str]),
        "generic_tuple": lib.Schema(tuple[int, str]),
        "generic_dict": lib.Schema(dict[str, int]),
        "generic_dict_open": lib.Schema(dict[str, Any]),
        "generic_nested": lib.Schema(list[dict[str, int]]),
        "generic_dict_value": lib.Schema(dict[str, list[int]]),
        "generic_field": lib.Schema({lib.Required("xs"): list[int]}),
        "generic_frozenset_open": lib.Schema(frozenset[int]),
        "enum": lib.Schema(Color),
        "nonetype": lib.Schema(type(None)),
        "bare_object": lib.Schema(object),
        "mapping": lib.Schema(
            {lib.Required("name"): str, lib.Optional("age"): int},
        ),
        "mapping_meta": lib.Schema(
            {lib.Optional("port", default=8080, description="the port"): int},
        ),
        "extra_allow": lib.Schema({"a": int}, extra=lib.ALLOW_EXTRA),
        "type_key": lib.Schema({str: int}),
        "type_key_open": lib.Schema({str: dict}),
        "nested": lib.Schema({lib.Required("o"): {lib.Required("x"): int}}),
        "required_any": lib.Schema({lib.Required(lib.Any("a", "b")): str}),
        "required_any_object": lib.Schema({lib.Required(lib.Any("a", "b")): object}),
        "optional_any": lib.Schema({lib.Optional(lib.Any("a", "b")): str}),
    }


_CASES = list(build(voluptuous))


@pytest.mark.parametrize("version", ["3.0", "3.1.0"])
@pytest.mark.parametrize("case", _CASES)
def test_matches_voluptuous_openapi(case: str, version: str) -> None:
    """to_openapi matches convert() for every case, in both OpenAPI versions."""
    expected = voluptuous_openapi.convert(
        build(voluptuous)[case],
        openapi_version=_ORACLE_VERSION[version],
    )
    actual = to_openapi(build(probatio)[case], openapi_version=version)

    # ``to_openapi`` renders a closed mapping's ``additionalProperties`` and a
    # null enum member more correctly than the oracle; compare the rest.
    assert canonical_openapi(actual) == canonical_openapi(expected)


def test_unrecognized_value_is_open() -> None:
    """An unrecognized, non-callable value renders as an open schema."""
    assert to_openapi(Schema(object())) == {}


def test_signatureless_builtin_type_does_not_leak() -> None:
    """A builtin type with no introspectable signature falls back, not crashes.

    ``inspect.signature(bytes)`` raises ValueError; voluptuous-openapi leaks it.
    Probatio must keep the codec leak-free and render an open schema instead. Found
    by the atheris fuzz harness.
    """
    assert to_openapi(Schema(bytes)) == {}


def test_merging_enums_with_unhashable_members_does_not_leak() -> None:
    """Same-typed enum branches with list members merge and dedup without a TypeError."""
    schema = Schema(probatio.Any(probatio.In([[1, 2]]), probatio.In([[1, 2], [3, 4]])))
    # The duplicate [1, 2] is dropped; order is preserved (no set involved).
    assert to_openapi(schema) == {"type": "string", "enum": [[1, 2], [3, 4]]}


def test_merging_hashable_enums_dedups() -> None:
    """Merged hashable enum branches drop duplicates, matching the oracle's set merge."""
    schema = Schema(probatio.Any(probatio.In(["a", "b"]), probatio.In(["b", "c"])))
    result = to_openapi(schema)
    assert result["type"] == "string"
    assert sorted(result["enum"]) == ["a", "b", "c"]


def test_multi_item_array() -> None:
    """A multi-element list means each item matches any of the element schemas.

    ``Schema([int, str])`` accepts a list whose elements are each an int or a
    string, so it renders as an ``anyOf`` item schema, not a positional ``items``
    array (which would constrain by position and reject ``[1, 2]``).
    voluptuous-openapi 0.3.0 crashes on this input, so it is asserted directly.
    """
    assert to_openapi(Schema([int, str])) == {
        "type": "array",
        "items": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
    }


def test_empty_array_accepts_only_empty() -> None:
    """An empty list schema accepts only the empty array, not any array."""
    assert to_openapi(Schema([])) == {"type": "array", "maxItems": 0}


def test_default_version_is_3_0() -> None:
    """The default version emits the OpenAPI 3.0 nullable shape, like the oracle."""
    assert to_openapi(Schema(None)) == voluptuous_openapi.convert(
        voluptuous.Schema(None),
    )


def test_custom_serializer_overrides_and_defers() -> None:
    """A custom serializer can override a node or defer with UNSUPPORTED, as oracle."""
    sentinel = object()

    def custom_probatio(node: Any) -> Any:
        return {"type": "custom"} if node is sentinel else UNSUPPORTED

    def custom_voluptuous(node: Any) -> Any:
        if node is sentinel:
            return {"type": "custom"}
        return voluptuous_openapi.UNSUPPORTED

    p = to_openapi(
        Schema({probatio.Optional("a"): sentinel, probatio.Optional("b"): int}),
        custom_serializer=custom_probatio,
    )
    v = voluptuous_openapi.convert(
        voluptuous.Schema(
            {voluptuous.Optional("a"): sentinel, voluptuous.Optional("b"): int},
        ),
        custom_serializer=custom_voluptuous,
    )

    assert canonical_openapi(p) == canonical_openapi(v)


_T = TypeVar("_T")


def _typed_callable(value: int) -> int:
    """A bare callable whose first parameter is annotated, for the oracle test."""
    return value


def _untyped_callable(value):
    """A bare callable with no annotation: renders as the open schema."""
    return value


def _union_callable(value: int | str) -> int | str:
    """A callable annotated with a union: renders as an anyOf, like the oracle."""
    return value


def _typevar_union_callable(value: int | _T) -> Any:  # noqa: UP047
    """A union with a TypeVar member: the TypeVar drops, leaving the bare type."""
    return value


def _optional_typevar_callable(value: _T | None) -> Any:  # noqa: UP047
    """A union of only None and a TypeVar: collapses to the open schema."""
    return value


class _CallableInstance:
    """A callable instance whose __call__ first parameter is annotated."""

    def __call__(self, value: str) -> str:
        """Return the value unchanged."""
        return value


@pytest.mark.parametrize(
    "schema",
    [
        _typed_callable,
        _untyped_callable,
        _union_callable,
        _typevar_union_callable,
        _optional_typevar_callable,
        _CallableInstance(),
        str.strip,
    ],
)
def test_bare_callable_uses_first_param_hint_like_oracle(schema: Any) -> None:
    """A bare callable renders from its first parameter's type hint, matching the oracle."""
    assert to_openapi(Schema(schema)) == voluptuous_openapi.convert(
        voluptuous.Schema(schema),
    )


def test_bare_callable_with_unresolvable_annotation_is_open_schema() -> None:
    """A callable whose annotation cannot be resolved falls back to {} without leaking."""

    def broken(value: DoesNotExist) -> None:  # type: ignore[name-defined]  # noqa: F821
        return value

    assert to_openapi(Schema(broken)) == {}


@pytest.mark.parametrize(
    ("validator", "expected"),
    [
        (IPv4Address(), {"type": "string", "format": "ipv4"}),
        (IPv6Address(), {"type": "string", "format": "ipv6"}),
        (UUID(), {"type": "string", "format": "uuid"}),
        (Hostname(), {"type": "string", "format": "hostname"}),
        (Fqdn(), {"type": "string", "format": "hostname"}),
        (IPAddress(), {"type": "string"}),
        (Slug(), {"type": "string"}),
        (Time(), {"type": "string", "format": "time"}),
        (Date(), {"type": "string", "format": "date"}),
        (AsDate(), {"type": "string", "format": "date"}),
        (AsTime(), {"type": "string", "format": "time"}),
        (AsDatetime(), {"type": "string", "format": "date-time"}),
        (Port(), {"type": "integer", "minimum": 1, "maximum": 65535}),
        (Percentage(), {"type": "number", "minimum": 0, "maximum": 100}),
        (MultipleOf(5), {"type": "number", "multipleOf": 5}),
        (FromEpoch(), {"type": "number"}),
    ],
)
def test_new_validators_to_openapi(validator: object, expected: dict) -> None:
    """The probatio-only validators render their OpenAPI fragment (no oracle)."""
    assert to_openapi(Schema(validator)) == expected


def test_secret_key_to_openapi_write_only() -> None:
    """A Secret key marks its property writeOnly in the OpenAPI object."""
    schema = Schema({probatio.Required(Secret("password")): str})
    assert to_openapi(schema) == {
        "type": "object",
        "properties": {"password": {"type": "string", "writeOnly": True}},
        "required": ["password"],
        "additionalProperties": False,
    }


def test_secret_layer_description_to_openapi_is_kept() -> None:
    """A description carried on the Secret layer survives into the OpenAPI property."""
    schema = Schema(
        {probatio.Required(Secret("password", description="the token")): str}
    )
    prop = to_openapi(schema)["properties"]["password"]
    assert prop["description"] == "the token"
    assert prop["writeOnly"] is True


def test_date_is_not_exported_as_datetime() -> None:
    """Date (a Datetime subclass) exports format date, not date-time."""
    assert to_openapi(Schema(Date())) == {"type": "string", "format": "date"}


def test_new_string_validators_to_openapi() -> None:
    """A character-class validator renders as a string; Base64 adds contentEncoding."""
    assert to_openapi(Schema(Alpha())) == {"type": "string"}
    assert to_openapi(Schema(Base64())) == {
        "type": "string",
        "contentEncoding": "base64",
    }


def test_datetime_enum_stays_serializable() -> None:
    """An In holding a datetime renders ISO strings, not raw datetimes."""
    from datetime import date  # noqa: PLC0415

    from probatio import In  # noqa: PLC0415

    result = to_openapi(Schema(In([date(2020, 1, 1)])))
    assert result == {"type": "string", "enum": ["2020-01-01"]}
    json.dumps(result)


def test_enum_members_render_their_values() -> None:
    """An In holding Enum members renders the member values."""
    from probatio import In  # noqa: PLC0415

    assert to_openapi(Schema(In([Color.RED, Color.BLUE]))) == {
        "type": "string",
        "enum": ["red", "blue"],
    }


def test_unrepresentable_enum_member_widens_to_open() -> None:
    """A member with no JSON form drops the enum to open, not a crash."""
    from probatio import In  # noqa: PLC0415

    assert to_openapi(Schema(In([b"raw"]))) == {}


def test_non_json_default_is_json_safe() -> None:
    """A datetime default renders its ISO string rather than a raw datetime."""
    from datetime import date  # noqa: PLC0415

    from probatio import Optional  # noqa: PLC0415

    schema = Schema({Optional("t", default=date(2020, 1, 1)): object})
    result = to_openapi(schema)
    assert result["properties"]["t"]["default"] == "2020-01-01"
    json.dumps(result)


def test_bytes_match_renders_a_plain_string() -> None:
    """A bytes Match pattern has no OpenAPI form, so it renders a string."""
    import re  # noqa: PLC0415

    from probatio import Match  # noqa: PLC0415

    assert to_openapi(Schema(Match(re.compile(rb"\d+")))) == {"type": "string"}


def test_self_renders_a_recursive_ref() -> None:
    """A Self reference renders a recursive $ref, not a plain string."""
    from probatio import Optional, Self  # noqa: PLC0415

    schema = Schema({"name": str, Optional("children"): [Self]})
    result = to_openapi(schema)
    assert result["properties"]["children"]["items"] == {"$ref": "#"}


def test_cyclic_raw_schema_is_a_clean_error() -> None:
    """A raw dict that references itself is refused, not a bare RecursionError."""
    from probatio.error import SchemaError  # noqa: PLC0415

    node: dict[object, object] = {"v": int}
    node["next"] = node
    with pytest.raises(SchemaError, match="references itself"):
        to_openapi(node)


def test_unrepresentable_default_is_omitted() -> None:
    """A mapping default with no JSON form is dropped rather than emitted raw."""
    from probatio import Optional  # noqa: PLC0415

    schema = Schema({Optional("t", default=b"raw"): object})
    assert "default" not in to_openapi(schema)["properties"]["t"]


def test_exclusive_bounds_use_the_version_form() -> None:
    """3.0 spells an exclusive bound as a boolean flag; 3.1 uses the numeric form."""
    from probatio import All, Range  # noqa: PLC0415

    schema = Schema(All(int, Range(min=0, min_included=False)))
    assert to_openapi(schema, openapi_version="3.0") == {
        "type": "integer",
        "minimum": 0,
        "exclusiveMinimum": True,
    }
    assert to_openapi(schema, openapi_version="3.1.0") == {
        "type": "integer",
        "exclusiveMinimum": 0,
    }


def test_array_length_retargets_to_item_counts() -> None:
    """A Length on an array renders minItems/maxItems, not minLength/maxLength."""
    from probatio import All, Length  # noqa: PLC0415

    assert to_openapi(Schema(All([int], Length(min=1, max=3)))) == {
        "type": "array",
        "items": {"type": "integer"},
        "minItems": 1,
        "maxItems": 3,
    }


def test_closed_mapping_forbids_extra_keys() -> None:
    """A strict (PREVENT_EXTRA) mapping renders additionalProperties: false."""
    result = to_openapi(Schema({"a": int}))
    assert result["additionalProperties"] is False


def test_remove_extra_renders_open() -> None:
    """REMOVE_EXTRA accepts extra keys, so it leaves additionalProperties open (absent)."""
    from probatio import REMOVE_EXTRA  # noqa: PLC0415

    result = to_openapi(Schema({"a": int}, extra=REMOVE_EXTRA))
    assert "additionalProperties" not in result


def test_array_length_retargets_min_only() -> None:
    """An array Length with only a minimum retargets to minItems alone."""
    from probatio import All, Length  # noqa: PLC0415

    result = to_openapi(Schema(All([int], Length(min=2))))
    assert result["minItems"] == 2
    assert "maxItems" not in result
    assert "minLength" not in result


def test_array_length_retargets_max_only() -> None:
    """An array Length with only a maximum retargets to maxItems alone."""
    from probatio import All, Length  # noqa: PLC0415

    result = to_openapi(Schema(All([int], Length(max=5))))
    assert result["maxItems"] == 5
    assert "minItems" not in result
