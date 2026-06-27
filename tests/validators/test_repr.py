"""Tests for validator __repr__ (readable, constructor-style, like voluptuous)."""

from __future__ import annotations

from probatio import (
    All,
    Any,
    Clamp,
    Coerce,
    Contains,
    Date,
    Datetime,
    Equal,
    ExactSequence,
    In,
    Length,
    Match,
    Maybe,
    NotIn,
    Range,
    Replace,
    Time,
)


def test_coerce_repr() -> None:
    """Coerce shows its target type by name."""
    assert repr(Coerce(int, msg="moo")) == "Coerce(int, msg='moo')"


def test_match_and_replace_repr() -> None:
    """Match and Replace show their pattern source (not the compiled object)."""
    assert (
        repr(Match("a pattern", msg="message")) == "Match('a pattern', msg='message')"
    )
    assert (
        repr(Replace("you", "I", msg="you and I"))
        == "Replace('you', 'I', msg='you and I')"
    )


def test_range_repr() -> None:
    """Range shows every bound and its inclusivity."""
    assert (
        repr(Range(min=0, max=42, min_included=False, max_included=False, msg="nope"))
        == "Range(min=0, max=42, min_included=False, max_included=False, msg='nope')"
    )


def test_combinator_repr_nests() -> None:
    """All/Any show each inner validator by its own repr, by their own class name."""
    assert repr(All("10", Coerce(int), msg="all msg")) == (
        "All('10', Coerce(int, msg=None), msg='all msg')"
    )
    assert repr(Any(int, str)) == "Any(<class 'int'>, <class 'str'>, msg=None)"


def test_maybe_repr_is_itself() -> None:
    """Maybe reprs as Maybe (probatio's Maybe is a first-class validator)."""
    assert repr(Maybe(int)) == "Maybe(<class 'int'>, msg=None)"


def test_membership_and_comparison_repr() -> None:
    """In, NotIn, Contains, and Equal repr as constructor calls, matching voluptuous."""
    assert repr(In([1, 2])) == "In([1, 2])"
    assert repr(NotIn([1, 2])) == "NotIn([1, 2])"
    assert repr(Contains(1)) == "Contains(1)"
    assert repr(Equal(5)) == "Equal(5)"


def test_length_and_clamp_repr() -> None:
    """Length and Clamp show their bounds (no msg, matching voluptuous)."""
    assert repr(Length(min=1)) == "Length(min=1, max=None)"
    assert repr(Clamp(min=0, max=5)) == "Clamp(min=0, max=5)"


def test_temporal_repr() -> None:
    """Date/Datetime/Time show their format, the class name following the subclass."""
    assert repr(Date()) == "Date(format=%Y-%m-%d)"
    assert repr(Datetime()) == "Datetime(format=%Y-%m-%dT%H:%M:%S.%fZ)"
    assert repr(Time()) == "Time(format=%H:%M:%S)"


def test_exact_sequence_repr() -> None:
    """ExactSequence shows its positional validators, matching voluptuous."""
    assert (
        repr(ExactSequence([int, str]))
        == "ExactSequence([<class 'int'>, <class 'str'>])"
    )
