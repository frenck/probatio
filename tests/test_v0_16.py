"""Behavior introduced in voluptuous 0.16.0, the current compatibility target.

Covers the three behavioral changes from 0.15.2 to 0.16.0: generators in ``In``
(#523), the ``Any`` key plus ``REMOVE_EXTRA`` fix (#524), and the
``Required(Any(...))`` "at least one of these keys" feature (#534). voluptuous is
the oracle for the cases where probatio matches it; the one deliberate deviation
is asserted directly.
"""

from __future__ import annotations

from typing import Any as Typ

import pytest
import voluptuous

import probatio
from probatio import All, Any, In, MultipleInvalid, Required, Schema, Union


def _detail(lib: Typ, build: Typ, data: Typ) -> Typ:
    """Run ``build(lib)(data)``, returning the result or each error's detail.

    Errors compare by class, bare message, and path; ``str(error)`` is left out
    because probatio deliberately renders the path differently (ADR-015).
    """
    try:
        return ("ok", build(lib)(data))
    except lib.MultipleInvalid as exc:
        return (
            "err",
            sorted(
                (type(e).__name__, e.error_message, [str(s) for s in e.path])
                for e in exc.errors
            ),
        )


# --- #523: In accepts a generator -------------------------------------------


def test_in_accepts_a_generator() -> None:
    """In works with a generator container, like voluptuous 0.16.0."""
    assert Schema(In(value for value in [1, 2, 3]))(2) == 2


# --- #524: Any key with each extra policy matches voluptuous 0.16.0 ----------


def _paths(lib: Typ, build: Typ, data: Typ) -> Typ:
    """Run ``build(lib)(data)``, returning the result or each error's path."""
    try:
        return ("ok", build(lib)(data))
    except lib.MultipleInvalid as exc:
        return ("err", sorted(tuple(e.path) for e in exc.errors))


@pytest.mark.parametrize("policy", ["REMOVE_EXTRA", "ALLOW_EXTRA", "PREVENT_EXTRA"])
def test_any_key_with_extra_policy_matches_voluptuous(policy: str) -> None:
    """An Any key under every extra policy agrees with voluptuous (PR #524).

    Under PREVENT_EXTRA the unmatched key is rejected; there probatio's Any key
    message is intentionally more descriptive than voluptuous's (issue #412), so
    the error paths are compared rather than the wording. The accept policies
    (REMOVE/ALLOW) produce no error, so their full results still match.
    """

    def build(lib: Typ) -> Typ:
        return lib.Schema(
            {lib.Any("name", "area"): str, "domain": str},
            extra=getattr(lib, policy),
        )

    data = {"name": "one", "domain": "two", "additional_key": "extra"}
    assert _paths(probatio, build, data) == _paths(voluptuous, build, data)


# --- #534: Required(Any(...)) requires at least one of the keys --------------


def _complex(lib: Typ) -> Typ:
    """A schema requiring at least one of color/temperature/brightness."""
    return lib.Schema(
        {lib.Required(lib.Any("color", "temperature", "brightness")): str}
    )


@pytest.mark.parametrize(
    "data",
    [
        {"color": "red"},
        {"temperature": "warm"},
        {"color": "blue", "brightness": "high"},
        {"color": 5},  # present but wrong value type
    ],
)
def test_complex_required_present_matches_voluptuous(data: dict[str, Typ]) -> None:
    """When a candidate key is present, probatio agrees with voluptuous."""
    assert _detail(probatio, _complex, data) == _detail(voluptuous, _complex, data)


def test_complex_required_none_present_reports_at_least_one() -> None:
    """None present raises a single clear 'at least one of ...' error."""
    with pytest.raises(MultipleInvalid) as caught:
        _complex(probatio)({})

    errors = caught.value.errors
    assert len(errors) == 1
    assert (
        errors[0].error_message
        == "at least one of ['color', 'temperature', 'brightness'] is required"
    )


def test_complex_required_uses_a_custom_message() -> None:
    """A custom msg on the Required marker replaces the default complex message."""
    schema = Schema({Required(Any("a", "b"), msg="need a or b"): str})
    with pytest.raises(MultipleInvalid) as caught:
        schema({})
    assert caught.value.errors[0].error_message == "need a or b"


def test_complex_required_deviation_is_a_single_error() -> None:
    """Deviation: probatio reports one error where voluptuous 0.16.0 reports two.

    voluptuous 0.16.0 also emits a redundant 'required key not provided' for the
    same missing key (it does not discard the complex key from the normal
    required pass). probatio reports the single clear error; this is the only
    intentional deviation for the 0.16.0 feature.
    """
    probatio_errors = _detail(probatio, _complex, {})[1]
    voluptuous_errors = _detail(voluptuous, _complex, {})[1]

    assert len(probatio_errors) == 1
    assert len(voluptuous_errors) == 2  # the upstream double-report
    assert probatio_errors[0] == voluptuous_errors[0]  # the first error matches


# --- combinator repr matches voluptuous (shows up in complex-key paths) ------


def test_combinator_repr_matches_voluptuous() -> None:
    """All/Any/Union render like voluptuous, so error paths read identically."""
    assert repr(Any("a", "b")) == repr(voluptuous.Any("a", "b"))
    assert repr(All(int, str)) == repr(voluptuous.All(int, str))
    assert repr(Union(int, str)) == repr(voluptuous.Union(int, str))


def test_complex_required_path_renders_the_any() -> None:
    """The missing complex key renders its Any in the path, matching voluptuous."""
    with pytest.raises(MultipleInvalid) as caught:
        _complex(probatio)({})
    assert "Any('color', 'temperature', 'brightness', msg=None)" in str(
        caught.value.errors[0],
    )
