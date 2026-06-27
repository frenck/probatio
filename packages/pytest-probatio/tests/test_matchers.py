"""Tests for the probatio schema matchers and the assertion-explaining hook."""

from __future__ import annotations

from pytest_probatio import Exact, Partial, S
from pytest_probatio.plugin import pytest_assertrepr_compare

from probatio import Port


def test_strict_match_passes() -> None:
    """A value matching the schema exactly compares equal."""
    assert {"name": "app", "port": 8080} == S({"name": str, "port": Port()})


def test_strict_match_rejects_extra_keys() -> None:
    """An extra key makes a strict S matcher unequal."""
    assert {"name": "app", "extra": 1} != S({"name": str})


def test_strict_match_rejects_a_bad_value() -> None:
    """A value of the wrong type compares unequal."""
    assert {"port": "nope"} != S({"port": Port()})


def test_partial_allows_extra_keys() -> None:
    """Partial accepts extra keys under ==."""
    assert {"name": "app", "extra": 1} == Partial({"name": str})


def test_le_operator_is_a_partial_match() -> None:
    """The <= operator relaxes S to a partial match (extra keys allowed)."""
    assert S({"name": str}) <= {"name": "app", "extra": 1}


def test_exact_requires_no_extra_keys() -> None:
    """Exact behaves strictly under ==, like S."""
    assert {"a": 1} == Exact({"a": int})
    assert {"a": 1, "b": 2} != Exact({"a": int})


def test_matcher_records_errors_with_paths() -> None:
    """A failed comparison records probatio errors carrying the offending path."""
    matcher = S({"server": {"port": Port()}})
    assert {"server": {"port": 70000}} != matcher
    assert matcher.errors
    assert matcher.errors[0].path == ["server", "port"]


def test_assertrepr_hook_lists_errors_by_path() -> None:
    """The pytest hook renders each error as a path and message."""
    matcher = S({"port": Port()})
    matcher == {"port": "nope"}  # noqa: B015 - run the comparison to record errors
    lines = pytest_assertrepr_compare("==", matcher, {"port": "nope"})
    assert lines is not None
    assert any("data['port']" in line for line in lines)


def test_assertrepr_hook_ignores_unrelated_comparisons() -> None:
    """The hook returns None when neither side is a matcher (no interference)."""
    assert pytest_assertrepr_compare("==", 1, 2) is None


def test_matcher_is_unhashable() -> None:
    """The matcher is not hashable, since it records mutable error state."""
    import pytest  # noqa: PLC0415

    with pytest.raises(TypeError):
        hash(S({"a": int}))


def test_plugin_explains_a_failed_assertion_end_to_end(pytester) -> None:
    """A failing `data == S(...)` under pytest shows the schema error, via the hook.

    This exercises the registered pytest11 plugin, not just the hook function: the
    entry point must be active for the explanation to appear in a real run.
    """
    pytester.makepyfile(
        """
        from pytest_probatio import S
        from probatio import Port

        def test_response():
            assert {"port": "nope"} == S({"port": Port()})
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    output = result.stdout.str()
    assert "does not match the probatio schema" in output
    assert "data['port']" in output
