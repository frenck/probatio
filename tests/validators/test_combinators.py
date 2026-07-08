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
    SchemaError,
    SomeOf,
    Switch,
    TaggedUnion,
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


def test_some_of_too_many_valid_keeps_branch_errors_in_the_message() -> None:
    """Too many matches with a failing branch still reports that branch's error."""
    schema = Schema(SomeOf([int, int, str], min_valid=0, max_valid=1))
    with pytest.raises(MultipleInvalid) as caught:
        schema(3)
    assert "expected str" in str(caught.value)


def test_some_of_too_many_valid_without_branch_errors_says_so() -> None:
    """When every branch matches, the error says too many matched, not ''."""
    schema = Schema(SomeOf([int, int], min_valid=0, max_valid=1))
    with pytest.raises(MultipleInvalid) as caught:
        schema(3)
    assert "matched 2 alternatives, expected at most 1" in str(caught.value)


def test_tagged_union_routes_on_the_key() -> None:
    """TaggedUnion validates against the schema listed for the discriminator value."""
    schema = Schema(
        TaggedUnion(
            "type",
            {
                "grid": {Required("type"): "grid", Required("stat"): str},
                "solar": {Required("type"): "solar"},
            },
        )
    )
    assert schema({"type": "grid", "stat": "sensor.x"}) == {
        "type": "grid",
        "stat": "sensor.x",
    }
    assert schema({"type": "solar"}) == {"type": "solar"}


def test_tagged_union_reports_the_chosen_branch_error() -> None:
    """A failure is reported against the branch the value selected, not 'no match'."""
    schema = Schema(
        TaggedUnion("type", {"grid": {Required("type"): "grid", Required("stat"): str}})
    )
    with pytest.raises(MultipleInvalid) as caught:
        schema({"type": "grid"})
    assert caught.value.errors[0].path == ["stat"]


def test_tagged_union_names_the_alternatives_on_an_unknown_value() -> None:
    """An unlisted tag is rejected with the valid values named, anchored at the key."""
    schema = Schema(TaggedUnion("type", {"grid": dict, "solar": dict}))
    with pytest.raises(MultipleInvalid) as caught:
        schema({"type": "wind"})
    error = caught.value.errors[0]
    assert "one of ['grid', 'solar']" in error.error_message
    assert error.path == ["type"]  # anchored at the discriminator key


def test_tagged_union_falls_back_to_a_default() -> None:
    """With a default, an unlisted value validates against the default schema."""
    schema = Schema(
        TaggedUnion("type", {"grid": {Required("type"): "grid"}}, default={"type": str})
    )
    assert schema({"type": "other"}) == {"type": "other"}


def test_tagged_union_rejects_a_non_mapping() -> None:
    """A non-mapping cannot carry the discriminator key; it is rejected as a mapping."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(TaggedUnion("type", {"a": dict}))(5)
    assert caught.value.errors[0].error_message == "expected a mapping"


def test_tagged_union_accepts_any_mapping() -> None:
    """Any Mapping routes, not only a plain dict, matching the rest of the engine."""
    from types import MappingProxyType  # noqa: PLC0415

    schema = Schema(TaggedUnion("type", {"grid": {Required("type"): "grid"}}))
    assert schema(MappingProxyType({"type": "grid"})) == {"type": "grid"}


def test_tagged_union_treats_an_unhashable_discriminator_as_a_miss() -> None:
    """An unhashable discriminator value cannot be a case key: a miss, then default."""
    schema = Schema(TaggedUnion("type", {"a": {"type": "a"}}, default=dict))
    # The 'type' value is a list (unhashable), so no case matches; the default takes it.
    assert schema({"type": [1, 2]}) == {"type": [1, 2]}
    # Without a default, the same unhashable discriminator is rejected.
    with pytest.raises(MultipleInvalid):
        Schema(TaggedUnion("type", {"a": {"type": "a"}}))({"type": [1, 2]})


def test_tagged_union_rejects_cases_that_are_neither_mapping_nor_list() -> None:
    """The cases must be a mapping or a list of branches, not some other value."""
    with pytest.raises(SchemaError):
        TaggedUnion("type", 5)  # type: ignore[arg-type]


def test_tagged_union_repr() -> None:
    """TaggedUnion renders as a constructor call showing the key and cases."""
    assert (
        repr(TaggedUnion("type", {"a": int}))
        == "TaggedUnion('type', {'a': <class 'int'>})"
    )


def test_tagged_union_list_form_reads_the_tag_from_each_branch() -> None:
    """The list form routes by the literal each branch pins at the discriminator key."""
    point = Schema({Required("type"): "point", Required("x"): int, Required("y"): int})
    label = Schema({Required("type"): "label", Required("text"): str})
    schema = Schema(TaggedUnion("type", [point, label]))

    assert schema({"type": "point", "x": 1, "y": 2}) == {
        "type": "point",
        "x": 1,
        "y": 2,
    }
    assert schema({"type": "label", "text": "hi"}) == {"type": "label", "text": "hi"}
    # Routing to the wrong branch is impossible: the tag comes from the branch itself.
    with pytest.raises(MultipleInvalid) as caught:
        schema({"type": "point", "x": "no", "y": 2})
    assert caught.value.errors[0].path == ["x"]


def test_tagged_union_list_form_accepts_plain_dict_branches() -> None:
    """A branch can be a plain dict, marker or literal key, not only a Schema."""
    schema = Schema(
        TaggedUnion("type", [{Required("type"): "a", "v": int}, {"type": "b"}])
    )
    assert schema({"type": "a", "v": 5}) == {"type": "a", "v": 5}


def test_tagged_union_list_form_rejects_a_branch_without_the_literal() -> None:
    """A branch that never pins the discriminator literal cannot be auto-routed."""
    with pytest.raises(SchemaError):
        TaggedUnion("type", [Schema({Required("x"): int})])
    # A non-mapping branch (a bare type) has no key to read a tag from either.
    with pytest.raises(SchemaError):
        TaggedUnion("type", [int])


def test_tagged_union_list_form_rejects_duplicate_tags() -> None:
    """Two branches pinning the same tag is a build-time error."""
    branch = {Required("type"): "a"}
    with pytest.raises(SchemaError):
        TaggedUnion("type", [branch, branch])


@pytest.mark.parametrize("bad_tag", [int, str.strip, [1, 2]])
def test_tagged_union_list_form_needs_a_plain_literal_tag(bad_tag: object) -> None:
    """A discriminator mapping to a type, a validator, or an unhashable is not a tag."""
    with pytest.raises(SchemaError):
        TaggedUnion("type", [{Required("type"): bad_tag, "v": int}])
