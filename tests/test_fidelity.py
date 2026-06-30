"""Error-output fidelity: probatio renders errors like voluptuous.

The conformance suite pins behavior (accept/reject and error paths) but leaves
wording free. For a drop-in, wording matters too: downstream code string-matches
``str(error)``, ``.msg``, and ``humanize_error``. These cases lock the rendered
message and path to voluptuous for the spots where the two once diverged.

voluptuous is a dev-only oracle; no code is copied from it.
"""

from __future__ import annotations

from typing import Any

import pytest
import voluptuous

import probatio


def range_exclusive_min(lib: Any) -> Any:
    """A Range with an exclusive lower bound."""
    return lib.Schema(lib.Range(min=1, min_included=False))


def range_exclusive_max(lib: Any) -> Any:
    """A Range with an exclusive upper bound."""
    return lib.Schema(lib.Range(max=5, max_included=False))


def length_min(lib: Any) -> Any:
    """A minimum-length check."""
    return lib.Schema(lib.Length(min=2))


def length_max(lib: Any) -> Any:
    """A maximum-length check."""
    return lib.Schema(lib.Length(max=2))


def datetime_default(lib: Any) -> Any:
    """A Datetime with the default format."""
    return lib.Schema(lib.Datetime())


def date_default(lib: Any) -> Any:
    """A Date with the default format."""
    return lib.Schema(lib.Date())


def membership_in(lib: Any) -> Any:
    """An In membership check over an unsorted container."""
    return lib.Schema(lib.In(["red", "blue"]))


def membership_not_in(lib: Any) -> Any:
    """A NotIn check over an unsorted container."""
    return lib.Schema(lib.NotIn(["red", "blue"]))


def multi_schema_sequence(lib: Any) -> Any:
    """A sequence whose items match one of several element schemas."""
    return lib.Schema([int, str])


def exclusive_group(lib: Any) -> Any:
    """Two keys in the same exclusive group."""
    return lib.Schema(
        {
            lib.Exclusive("a", "grp"): int,
            lib.Exclusive("b", "grp"): int,
        },
    )


def inclusive_group(lib: Any) -> Any:
    """Two keys in the same inclusive group."""
    return lib.Schema(
        {
            lib.Inclusive("a", "grp"): int,
            lib.Inclusive("b", "grp"): int,
        },
    )


def unique(lib: Any) -> Any:
    """A uniqueness check."""
    return lib.Schema(lib.Unique())


def type_key_mapping(lib: Any) -> Any:
    """A mapping keyed by a type; an unmatched key reports the key validator."""
    return lib.Schema({str: int})


CASES: list[tuple[Any, Any]] = [
    (range_exclusive_min, 1),
    (range_exclusive_max, 5),
    (length_min, "a"),
    (length_max, "abc"),
    (datetime_default, "nope"),
    (date_default, "nope"),
    (membership_in, "green"),
    (membership_not_in, "red"),
    (multi_schema_sequence, [1.2]),
    (exclusive_group, {"a": 1, "b": 2}),
    (inclusive_group, {"a": 1}),
    (unique, [1, 1, 2]),
    (type_key_mapping, {1: 2}),
]


def _first_error(builder: Any, data: Any, lib: Any) -> Any:
    """Return the first error's rendered string and path from a failed validation."""
    try:
        builder(lib)(data)
    except lib.Invalid as exc:
        error = exc.errors[0] if isinstance(exc, lib.MultipleInvalid) else exc
        return (str(error), [str(segment) for segment in error.path])
    msg = "expected the schema to reject the value"
    raise AssertionError(msg)


@pytest.mark.parametrize(("builder", "data"), CASES)
def test_error_string_matches_voluptuous(builder: Any, data: Any) -> None:
    """probatio renders the same error string and path as voluptuous."""
    assert _first_error(builder, data, probatio) == _first_error(
        builder,
        data,
        voluptuous,
    )


def test_virtual_path_component_renders_in_brackets() -> None:
    """A group path segment renders as ``<group>`` in the error string."""
    with pytest.raises(probatio.MultipleInvalid) as caught:
        exclusive_group(probatio)({"a": 1, "b": 2})

    error = caught.value.errors[0]
    assert str(error).endswith("@ data[<grp>]")
    assert error.path == ["grp"]
    assert repr(error.path[0]) == "<grp>"
