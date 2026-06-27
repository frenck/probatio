"""Tests for the cross-field validators (RequiredWith/Without, RequiredIf, Check)."""

from __future__ import annotations

import pytest

from probatio import (
    All,
    Check,
    Invalid,
    MultipleInvalid,
    Optional,
    RequiredIf,
    RequiredWith,
    RequiredWithout,
    Schema,
)
from probatio.error import RequiredFieldInvalid, SchemaError


def _with_schema() -> Schema:
    """A schema requiring cert and key whenever tls is present."""
    return Schema(
        All(
            {"tls": bool, Optional("cert"): str, Optional("key"): str},
            RequiredWith("tls", "cert", "key"),
        ),
    )


def test_required_with_passes_when_dependencies_present() -> None:
    """All required keys present alongside the trigger validates."""
    data = {"tls": True, "cert": "c", "key": "k"}
    assert _with_schema()(data) == data


def test_required_with_rejects_a_missing_dependency() -> None:
    """A missing required key under a present trigger is reported with its path."""
    with pytest.raises(MultipleInvalid) as caught:
        _with_schema()({"tls": True, "cert": "c"})
    error = caught.value.errors[0]
    assert isinstance(error, RequiredFieldInvalid)
    assert error.path == ["key"]


def test_required_with_no_op_when_trigger_absent() -> None:
    """When the trigger key is absent, nothing is required."""
    assert _with_schema()({}) == {}


def test_required_with_ignores_a_non_mapping() -> None:
    """Used on a non-mapping, the rule does not apply (and does not crash)."""
    assert Schema(RequiredWith("a", "b"))("x") == "x"


def test_required_with_custom_message() -> None:
    """A custom message replaces the default."""
    schema = Schema(
        All(
            {"a": int, Optional("b"): int}, RequiredWith("a", "b", msg="need b with a")
        ),
    )
    with pytest.raises(MultipleInvalid) as caught:
        schema({"a": 1})
    assert caught.value.errors[0].error_message == "need b with a"


def _if_schema() -> Schema:
    """A schema requiring token when auth equals 'token'."""
    return Schema(
        All(
            {"auth": str, Optional("token"): str},
            RequiredIf({"auth": "token"}, "token"),
        ),
    )


def test_required_if_passes_when_condition_met_and_present() -> None:
    """The required key present when the trigger matches validates."""
    data = {"auth": "token", "token": "t"}
    assert _if_schema()(data) == data


def test_required_if_rejects_when_condition_met_and_missing() -> None:
    """A missing required key when the trigger matches is reported."""
    with pytest.raises(MultipleInvalid) as caught:
        _if_schema()({"auth": "token"})
    assert caught.value.errors[0].path == ["token"]


def test_required_if_no_op_on_other_value_or_absent() -> None:
    """A different trigger value, or an absent trigger, requires nothing."""
    assert _if_schema()({"auth": "none"}) == {"auth": "none"}
    assert _if_schema()({}) == {}


def test_required_if_ignores_a_non_mapping() -> None:
    """Used on a non-mapping, the rule does not apply."""
    assert Schema(RequiredIf({"a": 1}, "b"))("x") == "x"


def test_required_with_any_of_several_triggers() -> None:
    """A list of triggers with mode='any' fires when any one is present."""
    rule = RequiredWith(["a", "b"], "x", mode="any")
    assert Schema(rule)({"b": 1, "x": 1}) == {"b": 1, "x": 1}
    with pytest.raises(MultipleInvalid) as caught:
        Schema(rule)({"a": 1})
    assert caught.value.errors[0].path == ["x"]


def test_required_with_all_of_several_triggers() -> None:
    """With mode='all', the rule fires only when every trigger is present."""
    rule = RequiredWith(["a", "b"], "x", mode="all")
    assert Schema(rule)({"a": 1}) == {"a": 1}  # not all triggers, no requirement
    with pytest.raises(MultipleInvalid) as caught:
        Schema(rule)({"a": 1, "b": 1})
    assert caught.value.errors[0].path == ["x"]


def test_required_without_requires_when_trigger_absent() -> None:
    """RequiredWithout requires a key when the trigger key is absent."""
    rule = RequiredWithout("cert", "cert_path")
    assert Schema(rule)({"cert": "c"}) == {"cert": "c"}  # trigger present, no-op
    assert Schema(rule)({"cert_path": "/x"}) == {"cert_path": "/x"}  # supplied
    with pytest.raises(MultipleInvalid) as caught:
        Schema(rule)({})
    assert caught.value.errors[0].path == ["cert_path"]


def test_required_without_ignores_a_non_mapping() -> None:
    """Used on a non-mapping, RequiredWithout does not apply (and does not crash)."""
    assert Schema(RequiredWithout("a", "b"))("x") == "x"


def test_required_without_all_of_several_triggers() -> None:
    """With mode='all', RequiredWithout fires only when every trigger is absent."""
    rule = RequiredWithout(["a", "b"], "x", mode="all")
    assert Schema(rule)({"a": 1}) == {"a": 1}  # one present, not all absent
    with pytest.raises(MultipleInvalid) as caught:
        Schema(rule)({})
    assert caught.value.errors[0].path == ["x"]


def test_required_if_all_conditions_must_match() -> None:
    """With several conditions and mode='all', every condition must hold to fire."""
    rule = RequiredIf({"a": 1, "b": 2}, "x", mode="all")
    assert Schema(rule)({"a": 1, "b": 9}) == {"a": 1, "b": 9}  # not all match
    with pytest.raises(MultipleInvalid) as caught:
        Schema(rule)({"a": 1, "b": 2})
    assert caught.value.errors[0].path == ["x"]


def test_required_if_any_condition_matches() -> None:
    """With mode='any', a single matching condition fires the requirement."""
    rule = RequiredIf({"a": 1, "b": 2}, "x", mode="any")
    with pytest.raises(MultipleInvalid) as caught:
        Schema(rule)({"a": 1})
    assert caught.value.errors[0].path == ["x"]


def test_cross_field_rejects_an_unknown_mode() -> None:
    """A mode other than 'any' or 'all' is a schema definition error."""
    with pytest.raises(SchemaError, match=r"any.*all"):
        RequiredWith("a", "b", mode="some")


def test_required_with_rejects_an_empty_trigger_list() -> None:
    """An empty trigger list has no meaningful behavior, so it is refused."""
    with pytest.raises(SchemaError, match="at least one trigger"):
        RequiredWith([], "b")


def test_required_if_rejects_empty_conditions() -> None:
    """RequiredIf needs at least one condition."""
    with pytest.raises(SchemaError, match="at least one condition"):
        RequiredIf({}, "x")


def test_required_if_non_matching_comparison_does_not_fire() -> None:
    """A condition value that cannot compare cleanly counts as not matching."""
    from decimal import Decimal  # noqa: PLC0415

    # A signaling NaN raises on ==, which the rule treats as no match, not a leak.
    # Assert by identity, since == on the sNaN would raise in the assertion itself.
    data = {"a": Decimal("sNaN")}
    assert Schema(RequiredIf({"a": Decimal("sNaN")}, "x"))(data) is data


def test_check_passes_when_predicate_holds() -> None:
    """Check returns the value when its predicate is truthy."""
    schema = Schema(
        All({"a": int, "b": int}, Check(lambda d: d["a"] < d["b"], "a < b"))
    )
    assert schema({"a": 1, "b": 2}) == {"a": 1, "b": 2}


def test_check_fails_when_predicate_is_falsy() -> None:
    """A falsy predicate raises Invalid with the message."""
    schema = Schema(
        All({"a": int, "b": int}, Check(lambda d: d["a"] < d["b"], "a < b"))
    )
    with pytest.raises(MultipleInvalid) as caught:
        schema({"a": 5, "b": 1})
    assert caught.value.errors[0].error_message == "a < b"


def test_check_reports_the_message_when_the_predicate_raises() -> None:
    """A predicate that raises (a missing key) is reported with the message."""
    schema = Schema(Check(lambda d: d["missing"] > 0, "needs the key"))
    with pytest.raises(MultipleInvalid) as caught:
        schema({})
    assert caught.value.errors[0].error_message == "needs the key"


def test_check_propagates_an_invalid_from_the_predicate() -> None:
    """A predicate may raise its own Invalid, which propagates."""

    def predicate(_value: object) -> bool:
        message = "from the predicate"
        raise Invalid(message)

    with pytest.raises(MultipleInvalid) as caught:
        Schema(Check(predicate, "unused"))("x")
    assert caught.value.errors[0].error_message == "from the predicate"
