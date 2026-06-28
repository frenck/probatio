"""Tests for to_openapi(): the voluptuous-openapi convert() shape.

These are differential: the same schema is built in both libraries, converted by
each (in both OpenAPI 3.0 and 3.1 modes), and the output compared. to_openapi must
match voluptuous-openapi so LLM tool calling and MCP consumers work on probatio
schemas unchanged.
"""

from __future__ import annotations

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
    Epoch,
    Fqdn,
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
    assert actual == expected


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
    """A fixed multi-item array lists a schema per position.

    voluptuous-openapi 0.3.0 crashes on this input (it calls ``.items()`` on a
    list), so this is asserted directly rather than differentially.
    """
    assert to_openapi(Schema([int, str])) == {
        "type": "array",
        "items": [{"type": "integer"}, {"type": "string"}],
    }


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
    assert p == v


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
        (Epoch(), {"type": "integer"}),
        (Secret(str), {"type": "string", "writeOnly": True}),
    ],
)
def test_new_validators_to_openapi(validator: object, expected: dict) -> None:
    """The probatio-only validators render their OpenAPI fragment (no oracle)."""
    assert to_openapi(Schema(validator)) == expected


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
