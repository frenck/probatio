"""Tests for the All and Any combinators."""

from __future__ import annotations

import pytest

from probatio import (
    ALLOW_EXTRA,
    PREVENT_EXTRA,
    REMOVE_EXTRA,
    All,
    And,
    Any,
    Coerce,
    Invalid,
    MultipleInvalid,
    Or,
    Range,
    Required,
    Schema,
    SomeOf,
    Switch,
    Union,
)
from probatio.error import (
    AnyInvalid,
    NotEnoughValid,
    RequiredFieldInvalid,
    TooManyValid,
)


def test_all_chains_validators() -> None:
    """All runs validators in order, feeding each result into the next."""
    assert Schema(All(str, str.strip))("  hi  ") == "hi"


def test_all_fails_when_a_validator_fails() -> None:
    """If any validator in All fails, the whole thing fails."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(All(int))("x")
    assert caught.value.errors[0].error_message == "expected int"


def test_all_custom_message_replaces_the_failure() -> None:
    """A msg on All replaces the underlying failure message."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(All(int, msg="must be a number"))("x")
    assert caught.value.errors[0].error_message == "must be a number"


def test_all_applies_inside_a_mapping_with_a_path() -> None:
    """All works as a value validator and keeps the key path."""
    schema = Schema({"name": All(str, str.strip)})
    assert schema({"name": "  bob  "}) == {"name": "bob"}


def test_any_returns_the_first_match() -> None:
    """Any returns the first validator that accepts the value."""
    assert Schema(Any(int, str))(5) == 5
    assert Schema(Any(int, str))("a") == "a"


def test_any_of_types_lists_the_expected_types() -> None:
    """An all-type Any reports every expected type, not just the first (issue #412)."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Any(int, str))(1.5)

    error = caught.value.errors[0]
    assert isinstance(error, AnyInvalid)
    assert error.error_message == "expected int or str"


def test_any_surfaces_a_validator_branch_error() -> None:
    """With a validator branch (no clean label), the branch error still surfaces."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Any(Range(min=0, max=5), Range(min=10, max=15)))(7)
    # No branch is labelable, so the nearest branch error speaks, like voluptuous.
    assert caught.value.errors[0].error_message == "value must be at most 5"


def test_any_picks_the_deepest_path_error() -> None:
    """Any raises the error from the branch that reached the deepest path."""
    schema = Schema(Any({"a": int}, int))

    with pytest.raises(MultipleInvalid) as caught:
        schema({"a": "x"})

    error = caught.value.errors[0]
    assert error.path == ["a"]
    assert error.error_message == "expected int"


def test_any_with_no_validators_reports_no_valid_value() -> None:
    """An Any with no branches falls back to the generic AnyInvalid message."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Any())("x")

    error = caught.value.errors[0]
    assert isinstance(error, AnyInvalid)
    assert error.error_message == "no valid value found"


def test_any_custom_message() -> None:
    """A msg on Any is used (as a bare AnyInvalid) when nothing matches."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Any(int, msg="not acceptable"))("x")

    error = caught.value.errors[0]
    assert isinstance(error, AnyInvalid)
    assert error.error_message == "not acceptable"


def test_all_custom_message() -> None:
    """A msg on All surfaces as a bare AllInvalid when a step fails."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(All(int, msg="must be int-ish"))("x")
    assert caught.value.errors[0].error_message == "must be int-ish"


def test_all_custom_message_for_a_sub_schema_step() -> None:
    """A msg on All also replaces a sub-schema step's MultipleInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(All({"a": int}, msg="bad shape"))({"a": "x"})
    assert caught.value.errors[0].error_message == "bad shape"


def test_combinators_expose_their_validators() -> None:
    """All and Any keep their raw validators for introspection."""
    assert All(int, str).validators == [int, str]
    assert Any(int).validators == [int]


def test_aliases() -> None:
    """And aliases All and Or aliases Any."""
    assert And is All
    assert Or is Any


def test_union_without_discriminant_behaves_like_any() -> None:
    """Union with no discriminant tries every validator, like Any."""
    schema = Schema(Union(int, str))

    assert schema(5) == 5
    assert schema("a") == "a"
    with pytest.raises(MultipleInvalid):
        schema(1.5)


def test_union_with_discriminant_narrows_candidates() -> None:
    """A discriminant selects which validators Union attempts."""
    int_schema = {"kind": "int", "value": int}
    str_schema = {"kind": "str", "value": str}

    def by_kind(value: dict, alternatives: list) -> list:
        return [alt for alt in alternatives if alt["kind"] == value.get("kind")]

    schema = Schema(Union(int_schema, str_schema, discriminant=by_kind))

    assert schema({"kind": "int", "value": 1}) == {"kind": "int", "value": 1}
    # The discriminant routes to the str branch, where value must be a str.
    with pytest.raises(MultipleInvalid):
        schema({"kind": "str", "value": 9})


def test_union_discriminant_branch_keeps_the_required_policy() -> None:
    """A fresh mapping a discriminant returns is compiled under the Union's required.

    The originals are compiled with the Union's ``required`` intent; a branch the
    discriminant builds fresh (not one of the originals) must be too, or it would
    silently drop the policy and treat its keys as optional.
    """

    def make_branch(_value: object, _alternatives: list) -> list:
        return [{"b": int}]  # a fresh mapping each call, never one of the originals

    schema = Schema(Union({"a": int}, discriminant=make_branch, required=True))
    assert schema({"b": 1}) == {"b": 1}
    with pytest.raises(MultipleInvalid):
        schema({})  # 'b' is required under required=True


def test_required_propagates_into_a_nested_mapping() -> None:
    """Any(..., required=True) makes its nested mapping keys required."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Any({"a": int}, required=True))({})
    assert isinstance(caught.value.errors[0], RequiredFieldInvalid)


def test_combinators_ignore_unknown_kwargs() -> None:
    """Unknown keyword arguments are accepted and ignored, like voluptuous."""
    assert Schema(Any(int, str, bogus=1))(5) == 5
    assert Schema(All(int, also=2))(5) == 5


def test_someof_passes_within_bounds() -> None:
    """SomeOf returns the value when enough validators pass."""
    schema = Schema(SomeOf(min_valid=2, validators=[Range(1, 5), Any(float, int), 6.6]))
    assert schema(6.6) == 6.6


def test_someof_not_enough_valid() -> None:
    """Too few passing validators raises NotEnoughValid."""
    schema = Schema(SomeOf(min_valid=2, validators=[Range(1, 5), Any(float, int), 6.6]))

    with pytest.raises(MultipleInvalid) as caught:
        schema(6.2)
    assert isinstance(caught.value.errors[0], NotEnoughValid)


def test_someof_too_many_valid() -> None:
    """More passing validators than allowed raises TooManyValid."""
    schema = Schema(SomeOf(max_valid=1, validators=[int, Range(0, 10)]))

    with pytest.raises(MultipleInvalid) as caught:
        schema(5)
    assert isinstance(caught.value.errors[0], TooManyValid)


def test_someof_requires_a_bound() -> None:
    """Building a SomeOf with neither bound is a programming error."""
    with pytest.raises(ValueError, match="min_valid"):
        SomeOf(validators=[int])


def test_switch_is_union() -> None:
    """Switch is exposed as an alias of Union."""
    assert Switch is Union


def test_any_custom_message_with_a_non_type_branch() -> None:
    """A non-type Any with msg surfaces AnyInvalid(msg) on a miss (general path)."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Any(Coerce(int), msg="not acceptable"))("x")

    error = caught.value.errors[0]
    assert isinstance(error, AnyInvalid)
    assert error.error_message == "not acceptable"


def test_any_with_none_branch_lists_none() -> None:
    """An Any whose branches include None reports 'None' among the expected (issue #412)."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Any(str, None))(10)
    assert caught.value.errors[0].error_message == "expected str or None"


def test_any_of_literals_lists_the_values() -> None:
    """An Any of scalar literals lists them, instead of 'not a valid value'."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Any("a", "b"))("c")

    error = caught.value.errors[0]
    assert isinstance(error, AnyInvalid)
    assert error.error_message == "expected 'a' or 'b'"


def test_allow_extra_propagates_into_any_branch_dicts() -> None:
    """A Schema's ALLOW_EXTRA reaches dict branches nested in Any (voluptuous parity)."""
    schema = Schema(
        Any(
            {Required("write"): int},
            {Required("state"): int},
            msg="at least one",
        ),
        extra=ALLOW_EXTRA,
    )

    data = {"write": 1, "state": 2, "passive": []}
    assert schema(data) == data


def test_allow_extra_propagates_into_all_branch_dicts() -> None:
    """ALLOW_EXTRA reaches dict schemas nested in All too."""
    schema = Schema(All({Required("a"): int}), extra=ALLOW_EXTRA)
    assert schema({"a": 1, "extra": 9}) == {"a": 1, "extra": 9}


def test_allow_extra_propagates_into_someof_and_union() -> None:
    """ALLOW_EXTRA reaches dict schemas nested in SomeOf and Union."""
    some = Schema(SomeOf([{Required("a"): int}], min_valid=1), extra=ALLOW_EXTRA)
    assert some({"a": 1, "x": 2}) == {"a": 1, "x": 2}

    union = Schema(Union({"kind": "a", "v": int}), extra=ALLOW_EXTRA)
    assert union({"kind": "a", "v": 1, "x": 2}) == {"kind": "a", "v": 1, "x": 2}


def test_remove_extra_propagates_into_any_branch_dicts() -> None:
    """REMOVE_EXTRA reaches dict branches nested in Any, dropping unknown keys."""
    schema = Schema(Any({Required("a"): int}), extra=REMOVE_EXTRA)
    assert schema({"a": 1, "junk": 9}) == {"a": 1}


def test_default_still_rejects_extra_in_a_combinator_branch() -> None:
    """With the default PREVENT_EXTRA, an unknown key in an Any branch still rejects."""
    schema = Schema(Any({Required("a"): int}))
    with pytest.raises(MultipleInvalid):
        schema({"a": 1, "junk": 9})


def test_extra_rebind_does_not_mutate_a_shared_combinator() -> None:
    """Wrapping a combinator with ALLOW_EXTRA must not change it for another schema."""
    shared = Any({Required("a"): int})
    assert Schema(shared, extra=ALLOW_EXTRA)({"a": 1, "x": 2}) == {"a": 1, "x": 2}

    # The same instance, used strictly elsewhere, still rejects the extra key.
    with pytest.raises(Invalid):
        Schema(shared, extra=PREVENT_EXTRA)({"a": 1, "x": 2})
