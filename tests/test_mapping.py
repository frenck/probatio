"""Tests for mapping (dict) schemas."""

from __future__ import annotations

import types

import pytest

from probatio import (
    ALLOW_EXTRA,
    REMOVE_EXTRA,
    UNDEFINED,
    Alias,
    Any,
    Coerce,
    Exclusive,
    Extra,
    ExtraKeysInvalid,
    Invalid,
    MultipleInvalid,
    Optional,
    Remove,
    Required,
    Schema,
)
from probatio.error import DictInvalid


def test_validates_a_matching_mapping() -> None:
    """A mapping whose values match is returned (here unchanged)."""
    schema = Schema({"name": str, "port": int})
    assert schema({"name": "app", "port": 80}) == {"name": "app", "port": 80}


def test_rejects_non_mapping() -> None:
    """Anything that is not a dict raises DictInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema({"x": int})(5)
    assert isinstance(caught.value.errors[0], DictInvalid)


def test_accepts_any_mapping() -> None:
    """A non-dict Mapping validates and yields a plain dict (issue #299)."""
    proxy = types.MappingProxyType({"name": "app", "port": 80})
    result = Schema({"name": str, "port": int})(proxy)
    assert result == {"name": "app", "port": 80}
    assert type(result) is dict


def test_dict_subclass_is_preserved() -> None:
    """A dict subclass comes back as that subclass, matching voluptuous."""

    class NodeDict(dict):
        pass

    result = Schema({"a": int})(NodeDict({"a": 1}))
    assert result == {"a": 1}
    assert type(result) is NodeDict


def test_dict_subclass_is_preserved_with_aliases() -> None:
    """The subclass survives even when alias resolution rebuilds the input."""

    class NodeDict(dict):
        pass

    result = Schema({Alias("a", "A"): int})(NodeDict({"A": 1}))
    assert result == {"a": 1}
    assert type(result) is NodeDict


def test_nested_dict_subclasses_are_preserved() -> None:
    """A subclass is preserved at every level of a nested mapping."""

    class NodeDict(dict):
        pass

    result = Schema({"outer": {"a": int}})(NodeDict({"outer": NodeDict({"a": 1})}))
    assert type(result) is NodeDict
    assert type(result["outer"]) is NodeDict


def test_mapping_value_errors_are_reported() -> None:
    """A bad value in a non-dict Mapping is reported like any dict value."""
    proxy = types.MappingProxyType({"port": "nope"})
    with pytest.raises(MultipleInvalid) as caught:
        Schema({"port": int})(proxy)
    assert caught.value.errors[0].path == ["port"]


def test_value_error_carries_the_key_path() -> None:
    """A bad value reports the key in its path."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema({"port": int})({"port": "nope"})
    error = caught.value.errors[0]
    assert error.path == ["port"]
    assert error.error_message == "expected int"


def test_nested_mapping_path() -> None:
    """A nested mapping reports the full path to the offending value."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema({"outer": {"inner": int}})({"outer": {"inner": "x"}})
    assert caught.value.errors[0].path == ["outer", "inner"]


def test_collects_every_error() -> None:
    """Validation gathers all errors, not just the first."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema({"a": int, "b": int})({"a": "x", "b": "y"})
    assert len(caught.value.errors) == 2


def test_bare_keys_are_optional_by_default() -> None:
    """A bare key may be absent without error."""
    assert Schema({"x": int})({}) == {}


def test_schema_required_makes_bare_keys_required() -> None:
    """Schema(required=True) flips bare keys to required."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema({"x": int}, required=True)({})
    assert caught.value.errors[0].error_message == "required key not provided"


def test_required_marker_reports_missing_key() -> None:
    """A missing Required key reports the contract message and path."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema({Required("name"): str})({})
    error = caught.value.errors[0]
    assert error.error_message == "required key not provided"
    assert error.path == ["name"]


def test_optional_default_is_applied_when_absent() -> None:
    """An absent Optional key with a default fills that default."""
    schema = Schema({Optional("port", default=8080): int})
    assert schema({}) == {"port": 8080}


def test_required_default_is_applied_without_error() -> None:
    """A Required key with a default fills in rather than failing."""
    schema = Schema({Required("port", default=80): int})
    assert schema({}) == {"port": 80}


def test_default_factory_returning_undefined_leaves_key_absent() -> None:
    """A default callable returning UNDEFINED declines, so the key stays absent."""
    schema = Schema({Optional("speed", default=lambda: UNDEFINED): int})
    assert schema({}) == {}


def test_default_factory_returning_value_still_applies() -> None:
    """A default callable returning a value still fills that value in."""
    schema = Schema({Optional("speed", default=lambda: 80): int})
    assert schema({}) == {"speed": 80}


def test_default_factory_decline_does_not_affect_a_provided_value() -> None:
    """A provided value is validated normally, even when the default would decline."""
    schema = Schema({Optional("speed", default=lambda: UNDEFINED): int})
    assert schema({"speed": 5}) == {"speed": 5}


def test_required_default_factory_that_declines_reports_missing() -> None:
    """A Required default that declines leaves the key missing, so it is reported."""
    schema = Schema({Required("speed", default=lambda: UNDEFINED): int})
    with pytest.raises(MultipleInvalid) as caught:
        schema({})
    assert caught.value.errors[0].path == ["speed"]


def test_exclusive_group_default_factory_that_declines_falls_through() -> None:
    """An exclusive member whose default declines lets the next member's apply."""
    schema = Schema(
        {
            Exclusive("a", "group", default=lambda: UNDEFINED): int,
            Exclusive("b", "group", default=lambda: 7): int,
        },
    )
    assert schema({}) == {"b": 7}


def test_prevent_extra_is_the_default() -> None:
    """Unknown keys are rejected by default with the contract message."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema({"x": int})({"x": 1, "y": 2})
    error = caught.value.errors[0]
    assert error.error_message == "not a valid option"
    assert error.path == ["y"]


def test_unknown_key_suggests_a_close_schema_key() -> None:
    """A near-miss key gets a single 'did you mean' suggestion and candidates."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema({Required("name"): str})({"nmae": "x"})
    error = caught.value.errors[0]
    assert isinstance(error, ExtraKeysInvalid)
    assert error.error_message == "not a valid option, did you mean 'name'?"
    assert error.candidates == ["name"]
    assert error.code == "extra_keys_not_allowed"


def test_unknown_key_suggests_multiple_close_keys() -> None:
    """Several near-miss keys are joined with a trailing 'or'."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema({Optional("name"): str, Optional("names"): str})({"nme": "x"})
    error = caught.value.errors[0]
    assert error.error_message == "not a valid option, did you mean 'name' or 'names'?"
    assert error.candidates == ["name", "names"]


def test_unknown_key_without_a_close_match_has_no_suggestion() -> None:
    """A key unlike any schema key reports the bare message and no candidates."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema({Required("name"): str})({"zzzzz": "x"})
    error = caught.value.errors[0]
    assert isinstance(error, ExtraKeysInvalid)
    assert error.error_message == "not a valid option"
    assert error.candidates == []


def test_unknown_non_string_key_is_never_suggested() -> None:
    """A non-string unknown key cannot match close strings, so no suggestion."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema({Required("name"): str})({42: "x"})
    assert caught.value.errors[0].candidates == []


def test_remove_and_forbidden_keys_are_not_suggested() -> None:
    """Keys that get removed or are forbidden are not offered as suggestions."""
    schema = Schema(
        {Optional("keep"): str, Remove("dropme"): str},
        extra=REMOVE_EXTRA,
    )

    # Sanity: the Remove key works under REMOVE_EXTRA.
    assert schema({"dropme": "x"}) == {}

    # A near-miss for the Remove key must not suggest it back.
    with pytest.raises(MultipleInvalid) as caught:
        Schema({Optional("keep"): str, Remove("dropme"): str})({"dropme": 1})
    assert caught.value.errors[0].candidates == []


def test_allow_extra_keeps_unknown_keys() -> None:
    """ALLOW_EXTRA passes unknown keys through unchanged."""
    schema = Schema({"x": int}, extra=ALLOW_EXTRA)
    assert schema({"x": 1, "y": 2}) == {"x": 1, "y": 2}


def test_remove_extra_drops_unknown_keys() -> None:
    """REMOVE_EXTRA drops unknown keys from the result."""
    schema = Schema({"x": int}, extra=REMOVE_EXTRA)
    assert schema({"x": 1, "y": 2}) == {"x": 1}


def test_remove_marker_drops_its_key() -> None:
    """A Remove marker drops the matched key from the output."""
    schema = Schema({"x": int, Remove("debug"): bool})
    assert schema({"x": 1, "debug": True}) == {"x": 1}


def test_type_keys_validate_every_matching_key() -> None:
    """A type key validates the value of every key of that type."""
    schema = Schema({str: int})
    assert schema({"a": 1, "b": 2}) == {"a": 1, "b": 2}
    with pytest.raises(MultipleInvalid) as caught:
        schema({"a": "x"})
    assert caught.value.errors[0].path == ["a"]


def test_literal_keys_take_precedence_over_type_keys() -> None:
    """A literal key wins over a type key that would also match."""
    schema = Schema({"name": str, str: int})
    assert schema({"name": "bob", "age": 5}) == {"name": "bob", "age": 5}


def test_multiple_type_keys_fall_through() -> None:
    """A key not matching the first type key is tried against the next."""
    schema = Schema({int: str, str: int})
    assert schema({1: "x", "y": 2}) == {1: "x", "y": 2}


def test_type_key_alongside_a_required_key() -> None:
    """A type key matches while the mapping also tracks a required key."""
    schema = Schema({Required("id"): int, str: int})
    assert schema({"id": 1, "other": 2}) == {"id": 1, "other": 2}


def test_remove_with_a_type_key() -> None:
    """A Remove marker with a type key drops every matching key."""
    schema = Schema({"name": str, Remove(int): object})
    assert schema({"name": "a", 5: "x", 6: "y"}) == {"name": "a"}


def test_remove_type_key_falls_through_when_its_value_does_not_match() -> None:
    """A Remove(str): int drops str keys with int values, but a str value falls
    through to a following str: str key instead of being rejected (voluptuous)."""
    schema = Schema({"amount": int, Remove(str): int, str: str})
    out = schema({"amount": 5, "drop": 3, "keep": "text"})
    # "drop" (str key, int value) is removed; "keep" (str value) falls through.
    assert out == {"amount": 5, "keep": "text"}


def test_remove_literal_key_falls_through_when_its_value_does_not_match() -> None:
    """A literal Remove behaves like a type Remove: a failing value falls through."""
    schema = Schema({Remove("id"): int, str: str})
    assert schema({"id": "text"}) == {"id": "text"}  # str value: kept by str: str
    assert schema({"id": 5}) == {}  # int value: removed


def test_remove_callable_key_falls_through_when_its_value_does_not_match() -> None:
    """The fall-through also works when the Remove key is a validator, not a type."""
    schema = Schema({Remove(Any("a", "b")): int, str: str})
    assert schema({"a": "text"}) == {"a": "text"}  # value not int: kept by str: str
    assert schema({"a": 7}) == {}  # value int: removed


def test_remove_validates_its_value_before_dropping() -> None:
    """A Remove key still validates its value; only a valid value is dropped.

    Matches voluptuous: a value that fails the Remove key's schema leaves the key
    unmatched, so the extra-key policy applies (rejected under PREVENT_EXTRA).
    """
    schema = Schema({Required("id"): int, Remove("note"): str})
    assert schema({"id": 1, "note": "drop me"}) == {"id": 1}

    with pytest.raises(MultipleInvalid) as caught:
        schema({"id": 1, "note": 42})
    assert caught.value.errors[0].path == ["note"]
    assert "not a valid option" in str(caught.value.errors[0])


def test_remove_invalid_value_passes_through_with_allow_extra() -> None:
    """Under ALLOW_EXTRA, a Remove value that fails its schema passes through."""
    schema = Schema({Remove("note"): str}, extra=ALLOW_EXTRA)
    assert schema({"note": 42}) == {"note": 42}
    assert schema({"note": "text"}) == {}


def test_dict_value_error_keeps_error_type_out_of_rendering() -> None:
    """A failed mapping value carries error_type but does not render it (ADR-015)."""
    schema = Schema({"data": int})
    with pytest.raises(MultipleInvalid) as caught:
        schema({"data": "x"})
    error = caught.value.errors[0]
    assert error.error_type == "dictionary value"
    assert str(error) == "expected int at 'data'"


def test_dict_value_error_type_is_not_overwritten() -> None:
    """A value error that already names its type keeps it, not "dictionary value"."""

    def picky(_value: object) -> object:
        error = Invalid("nope")
        error.error_type = "special thing"
        raise error

    schema = Schema({"a": picky})

    with pytest.raises(MultipleInvalid) as caught:
        schema({"a": 1})
    assert caught.value.errors[0].error_type == "special thing"


def test_empty_mapping_schema() -> None:
    """An empty schema accepts an empty dict, and any dict with ALLOW_EXTRA."""
    assert Schema({})({}) == {}
    assert Schema({}, extra=ALLOW_EXTRA)({"a": 1}) == {"a": 1}


def test_extra_key_validates_and_allows_unmatched_keys() -> None:
    """An Extra key validates every otherwise-unmatched key and allows it through."""
    schema = Schema({"a": int, Extra: str})
    assert schema({"a": 1, "b": "x", "c": "y"}) == {"a": 1, "b": "x", "c": "y"}
    with pytest.raises(MultipleInvalid) as caught:
        schema({"a": 1, "b": 2})
    assert caught.value.errors[0].path == ["b"]


def test_extra_object_allows_anything_extra() -> None:
    """Extra mapped to object allows any extra value (the common allow-all form)."""
    schema = Schema({"a": int, Extra: object})
    assert schema({"a": 1, "b": [1, 2], "c": None}) == {"a": 1, "b": [1, 2], "c": None}


def test_literal_key_wins_over_extra() -> None:
    """A named key matches before the Extra catch-all, wherever Extra sits."""
    schema = Schema({Extra: str, "n": int})
    assert schema({"n": 5, "other": "x"}) == {"n": 5, "other": "x"}


def test_extra_is_tried_after_a_type_key() -> None:
    """A type key matches its keys before Extra catches the rest."""
    schema = Schema({str: int, Extra: object})
    assert schema({"count": 3, 7: "anything"}) == {"count": 3, 7: "anything"}


def test_default_is_validated_through_the_value_schema() -> None:
    """An Optional default is coerced by its value schema, matching voluptuous."""
    schema = Schema({Optional("port", default="8080"): Coerce(int)})
    assert schema({}) == {"port": 8080}


def test_a_default_that_fails_its_schema_is_rejected() -> None:
    """A default value that does not satisfy its schema is reported, not stored raw."""
    schema = Schema({Optional("x", default="bad"): int})
    with pytest.raises(MultipleInvalid) as caught:
        schema({})
    assert caught.value.errors[0].path == ["x"]


def test_required_marker_uses_its_custom_message() -> None:
    """A Required marker's msg is used for the missing-key error."""
    schema = Schema({Required("name", msg="name is required"): str})
    with pytest.raises(MultipleInvalid) as caught:
        schema({})
    assert caught.value.errors[0].error_message == "name is required"
