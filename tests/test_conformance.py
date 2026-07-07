"""Differential conformance tests: probatio must behave like voluptuous.

Each case builds the same schema in both libraries (the API is identical, that is
the whole point), runs the same input through both, and asserts they agree: the
same accepted/normalized result, or rejection with the same error paths. Error
message wording is intentionally not compared, probatio is free to improve it.

voluptuous is a dev-only oracle here; no code is copied from it.
"""

from __future__ import annotations

from typing import Any

import pytest
import voluptuous

import probatio


def basic_mapping(lib: Any) -> Any:
    """Required + Optional-with-default + a typed value."""
    return lib.Schema(
        {
            lib.Required("name"): str,
            lib.Optional("port", default=8080): int,
        },
    )


def all_coerce_range(lib: Any) -> Any:
    """A chained All(Coerce, Range) value."""
    return lib.Schema(
        {lib.Required("n"): lib.All(lib.Coerce(int), lib.Range(min=0, max=10))}
    )


def any_value(lib: Any) -> Any:
    """An Any of two types."""
    return lib.Schema({"v": lib.Any(int, str)})


def list_of_ints(lib: Any) -> Any:
    """A list whose items must all be ints."""
    return lib.Schema({"items": [int]})


def membership(lib: Any) -> Any:
    """An In membership check."""
    return lib.Schema({"color": lib.In(["red", "green"])})


def nested_mapping(lib: Any) -> Any:
    """A mapping nested inside a mapping."""
    return lib.Schema({"a": {"b": int}})


def remove_key(lib: Any) -> Any:
    """A Remove key that still validates its value before dropping it."""
    return lib.Schema({lib.Required("id"): int, lib.Remove("note"): str})


def extra_key(lib: Any) -> Any:
    """An Extra catch-all that validates every otherwise-unmatched key."""
    return lib.Schema({lib.Required("id"): int, lib.Extra: str})


def type_key(lib: Any) -> Any:
    """A mapping keyed by a type, so unmatched keys fail the key validator."""
    return lib.Schema({str: int})


def mixed_key(lib: Any) -> Any:
    """A mapping mixing a literal key with a type key."""
    return lib.Schema({"a": int, int: str})


def two_type_keys(lib: Any) -> Any:
    """Two type keys, so a key failing both reports the first key validator."""
    # Both must stay bare ``isinstance`` keys: ``float`` honors the numeric tower
    # (ADR-017), which would coerce an int key instead of inlining the check.
    return lib.Schema({int: str, bytes: str})


def callable_key(lib: Any) -> Any:
    """A callable (non-type) key: the key must coerce to an int."""
    return lib.Schema({lib.Coerce(int): str})


def two_callable_keys(lib: Any) -> Any:
    """Two callable keys, so a key failing both keeps the first key error."""
    return lib.Schema({lib.Coerce(int): str, lib.Coerce(float): bool})


def remove_extra_mapping(lib: Any) -> Any:
    """A literal-keyed mapping that drops unmatched keys."""
    return lib.Schema({"a": int}, extra=lib.REMOVE_EXTRA)


def literal_value(lib: Any) -> Any:
    """A Literal match."""
    return lib.Schema(lib.Literal("on"))


def set_from_list(lib: Any) -> Any:
    """A Set conversion."""
    return lib.Schema(lib.Set())


def unordered_pair(lib: Any) -> Any:
    """An Unordered pair of element validators."""
    return lib.Schema(lib.Unordered([str, int]))


def some_of(lib: Any) -> Any:
    """A SomeOf with a minimum pass count."""
    return lib.Schema(lib.SomeOf(min_valid=2, validators=[lib.Range(1, 5), int, 3]))


CASES: list[tuple[Any, Any]] = [
    (basic_mapping, {"name": "app"}),
    (basic_mapping, {"name": "app", "port": 3}),
    (basic_mapping, {}),
    (basic_mapping, {"name": 5}),
    (basic_mapping, {"name": "app", "extra": 1}),
    (all_coerce_range, {"n": "5"}),
    (all_coerce_range, {"n": "20"}),
    (all_coerce_range, {"n": "x"}),
    (any_value, {"v": 1}),
    (any_value, {"v": "a"}),
    (any_value, {"v": 1.5}),
    (list_of_ints, {"items": [1, 2, 3]}),
    (list_of_ints, {"items": [1, "x", 3]}),
    (membership, {"color": "red"}),
    (membership, {"color": "blue"}),
    (nested_mapping, {"a": {"b": 1}}),
    (nested_mapping, {"a": {"b": "x"}}),
    (remove_key, {"id": 1, "note": "drop"}),
    (remove_key, {"id": 1, "note": 42}),
    (remove_key, {"id": 1}),
    (extra_key, {"id": 1, "other": "ok"}),
    (extra_key, {"id": 1, "other": 99}),
    (extra_key, {"id": 1}),
    (type_key, {"a": 1, "b": 2}),
    (type_key, {"a": "x"}),
    (type_key, {1: 2}),
    (mixed_key, {"a": 1, "k": "v"}),
    (mixed_key, {"a": 1, 2: "v"}),
    (mixed_key, {"a": 1, 2: 3}),
    (two_type_keys, {"x": "v"}),
    (callable_key, {"5": "v"}),
    (callable_key, {"x": "v"}),
    (two_callable_keys, {"x": "v"}),
    (remove_extra_mapping, {"a": 1, "x": 2}),
    (literal_value, "on"),
    (literal_value, "off"),
    (set_from_list, [1, 2, 2]),
    (unordered_pair, [1, "a"]),
    (unordered_pair, ["a", 1]),
    (unordered_pair, [1, 2]),
    (some_of, 3),
    (some_of, 7),
]


def _run(builder: Any, data: Any, lib: Any) -> Any:
    """Run a schema, returning the result or the sorted set of error paths."""
    try:
        return ("ok", builder(lib)(data))
    except lib.Invalid as exc:
        errors = exc.errors if isinstance(exc, lib.MultipleInvalid) else [exc]
        return ("error", sorted(tuple(error.path) for error in errors))


@pytest.mark.parametrize(("builder", "data"), CASES)
def test_matches_voluptuous(builder: Any, data: Any) -> None:
    """probatio agrees with voluptuous on the result, or on the error paths."""
    assert _run(builder, data, probatio) == _run(builder, data, voluptuous)


def _detail(builder: Any, data: Any, lib: Any) -> Any:
    """Run a schema, returning the result or each error's class, message, and path.

    A drop-in is judged on more than the error path: downstream code reads
    ``.msg``, ``error_message``, and the error subclass. This pins all three.
    ``str(error)`` is left out: probatio deliberately renders the path as a
    dotted trail and drops the error-type clause (ADR-015).
    """
    try:
        return ("ok", builder(lib)(data))
    except lib.Invalid as exc:
        errors = exc.errors if isinstance(exc, lib.MultipleInvalid) else [exc]
        return (
            "error",
            sorted(
                (type(e).__name__, e.error_message, [str(s) for s in e.path])
                for e in errors
            ),
        )


# Builders whose error message/class intentionally diverges from voluptuous, so
# only their error paths are compared (above), not the rendered detail. ``Any``
# lists its expected branches ("expected int or str") where voluptuous reports
# just the first ("expected int"); see issue #412. The mapping builders raise
# ``ExtraKeysInvalid`` with a "not a valid option, did you mean ...?" message on
# an unknown key, where voluptuous raises a bare ``Invalid("extra keys not
# allowed")``; a deliberate improvement that carries close-match suggestions.
# ``Literal`` reads "expected {lit}" instead of voluptuous's broken-English
# "{value} not match for {lit}", and ``Unordered`` reads "expected a sequence"
# / "expected a sequence of N items" / "item N (...) does not match any
# validator" instead of the upstream developer-speak; deliberate rewording,
# documented in the compatibility matrix.
_MESSAGE_DEVIATIONS = {
    any_value,
    basic_mapping,
    remove_key,
    literal_value,
    unordered_pair,
}

_DETAIL_CASES = [case for case in CASES if case[0] not in _MESSAGE_DEVIATIONS]


@pytest.mark.parametrize(("builder", "data"), _DETAIL_CASES)
def test_matches_voluptuous_error_detail(builder: Any, data: Any) -> None:
    """probatio agrees with voluptuous on the error class and rendered message."""
    assert _detail(builder, data, probatio) == _detail(builder, data, voluptuous)
