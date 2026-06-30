"""Tests for Schema.extend."""

from __future__ import annotations

import pytest

from probatio import (
    ALLOW_EXTRA,
    MultipleInvalid,
    Optional,
    Required,
    Schema,
    SchemaError,
)
from probatio.markers import Marker


def test_extend_adds_keys() -> None:
    """Extending merges new keys into the mapping schema."""
    base = Schema({"a": int})
    extended = base.extend({"b": str})
    assert extended({"a": 1, "b": "x"}) == {"a": 1, "b": "x"}


def test_extend_overrides_a_key() -> None:
    """A key in the extension replaces the base key and its marker."""
    base = Schema({Required("a"): int})
    extended = base.extend({Optional("a"): int})
    # 'a' is now optional, so an empty mapping validates.
    assert extended({}) == {}


def test_extend_overrides_extra_policy() -> None:
    """Extending with a new extra policy relaxes the original."""
    base = Schema({"a": int})
    relaxed = base.extend({}, extra=ALLOW_EXTRA)
    assert relaxed({"a": 1, "b": 2}) == {"a": 1, "b": 2}


def test_extend_inherits_settings_when_unset() -> None:
    """When extra/required are not given, the base settings carry over."""
    base = Schema({"a": int}, extra=ALLOW_EXTRA)
    extended = base.extend({"b": int})
    assert extended({"a": 1, "b": 2, "c": 3}) == {"a": 1, "b": 2, "c": 3}


def test_extend_requires_a_mapping_base() -> None:
    """Extending a non-mapping schema is a schema definition error."""
    with pytest.raises(SchemaError):
        Schema(int).extend({"a": int})


def test_extend_requires_a_mapping_argument() -> None:
    """Extending with a non-mapping argument is a schema definition error."""
    with pytest.raises(SchemaError):
        Schema({"a": int}).extend(int)


def test_extend_on_a_dataclass_schema_is_a_clear_error() -> None:
    """A DataclassSchema is built from a type, so extend refuses with a clear message."""
    import dataclasses  # noqa: PLC0415

    from probatio import DataclassSchema  # noqa: PLC0415

    @dataclasses.dataclass
    class User:
        name: str

    with pytest.raises(SchemaError, match="DataclassSchema"):
        DataclassSchema(User).extend({"extra": int})


def test_extend_on_a_typeddict_schema_is_a_clear_error() -> None:
    """A TypedDictSchema is built from a type, so extend refuses with a clear message."""
    from typing import TypedDict  # noqa: PLC0415

    from probatio import TypedDictSchema  # noqa: PLC0415

    class Movie(TypedDict):
        title: str

    with pytest.raises(SchemaError, match="TypedDictSchema"):
        TypedDictSchema(Movie).extend({"extra": int})


def test_extend_can_make_keys_required() -> None:
    """Passing required=True flips bare keys of the merged schema to required."""
    extended = Schema({"a": int}).extend({"b": int}, required=True)
    with pytest.raises(MultipleInvalid):
        extended({})


def test_extend_accepts_a_schema() -> None:
    """Extending with another Schema merges its keys (voluptuous PR #538)."""
    extended = Schema({"a": int}).extend(Schema({"b": str}))
    assert extended({"a": 1, "b": "x"}) == {"a": 1, "b": "x"}


def test_extend_with_required_schema_pins_keys_required() -> None:
    """A required=True extension Schema makes its bare keys Required in the merge."""
    extended = Schema({"a": int}).extend(Schema({"b": str}, required=True))
    with pytest.raises(MultipleInvalid) as caught:
        extended({"a": 1})
    assert caught.value.errors[0].path == ["b"]


def test_extend_keeps_extension_keys_optional_under_required_result() -> None:
    """A non-required extension stays Optional even when the result is required."""
    extended = Schema({Optional("a"): int}).extend(
        Schema({"b": str}),
        required=True,
    )
    # 'b' came from a non-required Schema, so it stays optional despite required=True.
    assert extended({}) == {}


def test_extend_normalizes_nested_required() -> None:
    """Required intent is normalized recursively into nested mappings."""
    extension = Schema({"outer": {"inner": int}}, required=True)
    extended = Schema({"a": int}).extend(extension)

    with pytest.raises(MultipleInvalid) as caught:
        extended({"a": 1, "outer": {}})

    assert caught.value.errors[0].path == ["outer", "inner"]


def test_extend_preserves_explicit_markers_from_a_schema() -> None:
    """An explicit Optional in a required extension Schema is not re-wrapped."""
    extended = Schema({"a": int}).extend(Schema({Optional("b"): str}, required=True))
    markers = [key for key in extended.schema if isinstance(key, Marker)]
    assert all(isinstance(key, Optional) for key in markers)


def test_extend_rejects_a_schema_with_conflicting_extra() -> None:
    """A Schema whose extra differs from the result's extra is refused."""
    with pytest.raises(SchemaError):
        Schema({"a": int}).extend(Schema({"b": int}, extra=ALLOW_EXTRA))


def test_extend_accepts_a_schema_with_matching_extra() -> None:
    """A Schema with the same extra as the result merges cleanly."""
    extended = Schema({"a": int}, extra=ALLOW_EXTRA).extend(
        Schema({"b": int}, extra=ALLOW_EXTRA),
    )
    assert extended({"a": 1, "b": 2, "c": 3}) == {"a": 1, "b": 2, "c": 3}


def test_extend_merges_nested_mappings_recursively() -> None:
    """Extending a nested key keeps the base's other nested keys (deep merge)."""
    base = Schema({"a": {"b": int, "c": float}})
    extended = base.extend({"d": str, "a": {"b": str, "e": int}})
    assert extended.schema == {"a": {"b": str, "c": float, "e": int}, "d": str}


def test_extend_returns_the_same_schema_subclass() -> None:
    """Extending a Schema subclass returns an instance of that subclass."""

    class StrictSchema(Schema):
        pass

    extended = StrictSchema({Required("a"): int}).extend({Optional("b"): str})

    assert isinstance(extended, StrictSchema)
    assert extended.schema == {Required("a"): int, Optional("b"): str}
