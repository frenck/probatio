"""Tests for to_openapi(): the OpenAPI Schema object shape.

Most cases are differential: the same schema is built in both libraries, converted
by each (in both OpenAPI 3.0 and 3.1 modes), and the output compared, so probatio
stays a drop-in for voluptuous-openapi where the oracle is correct. Where probatio
deliberately emits correct OpenAPI the oracle gets wrong (an ``anyOf`` with an open
or nullable branch, the widened constraint validators), the expected output is
asserted directly instead, and ``test_openapi_oracle.py`` covers it property-based
against the ``openapi-schema-validator`` reference implementation.
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


# These cases render correct OpenAPI that voluptuous-openapi gets wrong, so a
# comparison against the oracle is meaningless: an ``Any`` with an open-object
# branch keeps that branch (the oracle collapses the whole ``anyOf`` to the open
# object) and a nullable ``Any`` admits null with a dedicated branch (the oracle
# emits an inert top-level ``nullable``). They are asserted directly below, and
# the behavioral oracle in ``test_openapi_oracle.py`` covers them property-based.
_DIVERGING = frozenset(
    {"any_three", "any_open", "any_open_nullable", "any_nested_nullable"},
)
_CASES = [case for case in build(voluptuous) if case not in _DIVERGING]


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


def test_any_with_null_branch_admits_null_directly() -> None:
    """Any(int, str, None) renders a dedicated null branch, not an inert nullable.

    voluptuous-openapi hangs the null on a top-level ``nullable``, which an ``anyOf``
    ignores (each branch decides its own nullability). probatio adds a branch that
    actually accepts null: ``type: null`` on 3.1, the nullable-object idiom on 3.0.
    """
    schema = Schema(probatio.Any(int, str, None))
    assert to_openapi(schema, openapi_version="3.1.0") == {
        "anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}],
    }
    assert to_openapi(schema, openapi_version="3.0") == {
        "anyOf": [
            {"type": "integer"},
            {"type": "string"},
            {"type": "object", "nullable": True, "description": "Must be null"},
        ],
    }


def test_any_with_open_object_keeps_all_branches() -> None:
    """Any(dict, int) keeps both branches instead of collapsing to the open object.

    voluptuous-openapi short-circuits the whole ``anyOf`` to the open object as soon
    as one branch is open, dropping the ``int`` branch. probatio keeps every branch,
    so the ``anyOf`` still documents the alternatives.
    """
    assert to_openapi(Schema(probatio.Any(dict, int))) == {
        "anyOf": [
            {"type": "object", "additionalProperties": True},
            {"type": "integer"},
        ],
    }


def test_any_open_and_nullable_keeps_the_open_branch_and_admits_null() -> None:
    """Any(dict, int, None) keeps the open branch and adds a dedicated null branch."""
    schema = Schema(probatio.Any(dict, int, None))
    assert to_openapi(schema, openapi_version="3.1.0") == {
        "anyOf": [
            {"type": "object", "additionalProperties": True},
            {"type": "integer"},
            {"type": "null"},
        ],
    }
    assert to_openapi(schema, openapi_version="3.0") == {
        "anyOf": [
            {"type": "object", "additionalProperties": True},
            {"type": "integer"},
            {"type": "object", "nullable": True, "description": "Must be null"},
        ],
    }


def test_nested_nullable_any_flattens_and_admits_null_once() -> None:
    """Any(Any(int, str, None), bool) flattens to one anyOf with a single null branch."""
    schema = Schema(probatio.Any(probatio.Any(int, str, None), bool))
    assert to_openapi(schema, openapi_version="3.1.0") == {
        "anyOf": [
            {"type": "integer"},
            {"type": "string"},
            {"type": "null"},
            {"type": "boolean"},
        ],
    }
    assert to_openapi(schema, openapi_version="3.0") == {
        "anyOf": [
            {"type": "integer"},
            {"type": "string"},
            {"type": "boolean"},
            {"type": "object", "nullable": True, "description": "Must be null"},
        ],
    }


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


def test_msg_renders_its_wrapped_validator() -> None:
    """Msg only swaps the error message, so it renders as the wrapped validator."""
    from probatio import Msg, Range  # noqa: PLC0415

    assert to_openapi(Schema(Msg(Range(min=1), "too small"))) == {"minimum": 1}


@pytest.mark.parametrize(
    ("some_of", "expected"),
    [
        ((1, 1), {"oneOf": [{"type": "integer"}, {"type": "string"}]}),
        ((1, 2), {"anyOf": [{"type": "integer"}, {"type": "string"}]}),
        ((2, 2), {"allOf": [{"type": "integer"}, {"type": "string"}]}),
        ((0, 1), {}),
    ],
)
def test_some_of_maps_counts_to_combinators(
    some_of: tuple[int, int],
    expected: dict,
) -> None:
    """SomeOf renders oneOf/anyOf/allOf for the counts OpenAPI expresses, else open."""
    from probatio import SomeOf  # noqa: PLC0415

    min_valid, max_valid = some_of
    schema = Schema(
        SomeOf(validators=[int, str], min_valid=min_valid, max_valid=max_valid),
    )
    assert to_openapi(schema) == expected


def test_unique_renders_a_unique_item_array() -> None:
    """Unique renders an array with uniqueItems set."""
    from probatio import Unique  # noqa: PLC0415

    assert to_openapi(Schema(Unique())) == {"type": "array", "uniqueItems": True}


def test_contains_uses_the_keyword_only_on_3_1() -> None:
    """Contains renders the 3.1 ``contains`` keyword; 3.0 drops it to a plain array.

    OpenAPI 3.0 lacks ``contains`` and misreads it, so on 3.0 the constraint widens
    to a bare array rather than emitting a keyword a 3.0 consumer breaks on.
    """
    from probatio import Contains  # noqa: PLC0415

    schema = Schema(Contains(int))
    assert to_openapi(schema, openapi_version="3.1.0") == {
        "type": "array",
        "contains": {"type": "integer"},
    }
    assert to_openapi(schema, openapi_version="3.0") == {"type": "array"}


def test_exact_sequence_uses_prefix_items_only_on_3_1() -> None:
    """ExactSequence renders 3.1 prefixItems; 3.0 lacks it, so it drops to an array."""
    from probatio import ExactSequence  # noqa: PLC0415

    schema = Schema(ExactSequence([int, str]))
    assert to_openapi(schema, openapi_version="3.1.0") == {
        "type": "array",
        "prefixItems": [{"type": "integer"}, {"type": "string"}],
        "items": False,
    }
    assert to_openapi(schema, openapi_version="3.0") == {"type": "array"}


def test_duration_renders_a_duration_string() -> None:
    """Duration and AsTimedelta both render a string with the duration format."""
    from probatio import AsTimedelta, Duration  # noqa: PLC0415

    expected = {"type": "string", "format": "duration"}
    assert to_openapi(Schema(Duration())) == expected
    assert to_openapi(Schema(AsTimedelta())) == expected


def test_inclusive_group_renders_all_or_none_per_version() -> None:
    """An Inclusive group renders dependentRequired on 3.1 and a oneOf form on 3.0.

    OpenAPI 3.0 lacks dependentRequired (and silently ignores it), so all-or-none
    is spelled with keywords 3.0 has: every member present, or none present.
    """
    from probatio import Inclusive  # noqa: PLC0415

    schema = Schema({Inclusive("a", "g"): int, Inclusive("b", "g"): int})
    assert to_openapi(schema, openapi_version="3.1.0")["dependentRequired"] == {
        "a": ["b"],
        "b": ["a"],
    }
    assert to_openapi(schema, openapi_version="3.0")["allOf"] == [
        {
            "oneOf": [
                {"required": ["a", "b"]},
                {"not": {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]}},
            ],
        },
    ]


def test_exclusive_group_renders_at_most_one() -> None:
    """An Exclusive group renders an at-most-one constraint, the same on both versions."""
    from probatio import Exclusive  # noqa: PLC0415

    schema = Schema({Exclusive("a", "e"): int, Exclusive("b", "e"): int})
    at_most_one = [{"not": {"anyOf": [{"required": ["a", "b"]}]}}]
    assert to_openapi(schema, openapi_version="3.0")["allOf"] == at_most_one
    assert to_openapi(schema, openapi_version="3.1.0")["allOf"] == at_most_one


def test_required_exclusive_group_renders_exactly_one() -> None:
    """A required Exclusive group with no default demands exactly one member."""
    from probatio import Exclusive  # noqa: PLC0415

    schema = Schema(
        {Exclusive("a", "e", required=True): int, Exclusive("b", "e"): int},
    )
    assert to_openapi(schema)["allOf"] == [
        {"oneOf": [{"required": ["a"]}, {"required": ["b"]}]},
    ]


def test_alias_key_expands_to_one_property_per_accepted_name() -> None:
    """An Alias key renders every accepted name as a property with the same schema."""
    from probatio.markers import Alias  # noqa: PLC0415

    result = to_openapi(Schema({Alias("name", "userName"): str}))
    assert result["properties"] == {
        "name": {"type": "string"},
        "userName": {"type": "string"},
    }
    assert "anyOf" not in result


def test_required_alias_demands_at_least_one_name() -> None:
    """A required Alias adds an at-least-one-name constraint over its accepted names."""
    from probatio.markers import Alias  # noqa: PLC0415

    result = to_openapi(Schema({Alias("name", "userName", required=True): str}))
    assert result["anyOf"] == [
        {"required": ["name"]},
        {"required": ["userName"]},
    ]


def test_required_alias_with_a_default_demands_no_name() -> None:
    """A required Alias carrying a default fills the empty case, so it demands no name."""
    from probatio.markers import Alias  # noqa: PLC0415

    result = to_openapi(
        Schema({Alias("name", "userName", required=True, default="x"): str}),
    )
    assert "anyOf" not in result
    assert result["properties"]["name"]["default"] == "x"
    assert result["properties"]["userName"]["default"] == "x"


def test_alias_without_canonical_only_emits_the_alias_names() -> None:
    """With accept_canonical=False the canonical name is not an accepted input name."""
    from probatio.markers import Alias  # noqa: PLC0415

    result = to_openapi(
        Schema({Alias("name", "userName", accept_canonical=False): str}),
    )
    assert result["properties"] == {"userName": {"type": "string"}}


def test_inclusive_group_round_trips_through_openapi_3_1() -> None:
    """A 3.1 Inclusive group decodes back to an Inclusive group via from_openapi."""
    from probatio import Inclusive, from_openapi  # noqa: PLC0415

    document = to_openapi(
        Schema({Inclusive("a", "g"): int, Inclusive("b", "g"): int}),
        openapi_version="3.1.0",
    )
    rebuilt = from_openapi(document)
    assert rebuilt({"a": 1, "b": 2}) == {"a": 1, "b": 2}
    assert rebuilt({}) == {}
    with pytest.raises(probatio.Invalid):
        rebuilt({"a": 1})
