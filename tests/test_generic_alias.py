"""A parameterized generic used as a schema validates its type arguments.

``dict[str, str]``, ``list[int]``, ``int | None`` and friends translate to the
structural schema they spell, the same way a dataclass field annotation does, so
``dict[str, str]`` validates exactly like ``{str: str}``. voluptuous instead calls
the alias as a constructor (``list[int]("abc")`` returns ``["a", "b", "c"]``), so
this is a deliberate deviation (ADR-018, issue #469).
"""

from __future__ import annotations

import typing
from dataclasses import dataclass
from enum import StrEnum

import pytest

from probatio import (
    ALLOW_EXTRA,
    MultipleInvalid,
    Optional,
    Range,
    Required,
    Schema,
)


class _Color(StrEnum):
    """A string enum, the shape of a Home Assistant service enum field."""

    RED = "red"


@dataclass
class _Point:
    """A small dataclass to nest inside a generic."""

    x: int


@pytest.mark.parametrize(
    ("schema", "value"),
    [
        (dict[str, str], {"a": "b"}),
        (list[int], [1, 2]),
        (set[int], {1, 2}),
        (frozenset[int], frozenset({1})),
        (tuple[int, ...], (1, 2)),
        (tuple[int, str], (1, "a")),
        (typing.List[int], [1]),  # noqa: UP006
        (typing.Dict[str, int], {"a": 1}),  # noqa: UP006
        (typing.Sequence[int], [1]),
        (typing.Mapping[str, int], {"a": 1}),
        (int | None, None),
        (int | None, 1),
        (typing.Optional[str], "a"),  # noqa: UP045
        (list[dict[str, int]], [{"a": 1}]),
    ],
)
def test_a_generic_accepts_a_matching_value(schema: object, value: object) -> None:
    """A value that matches the type arguments validates to an equal value."""
    assert Schema(schema)(value) == value


@pytest.mark.parametrize(
    ("schema", "value", "message"),
    [
        (dict[str, str], {"a": 1}, "expected str at 'a'"),
        (list[int], ["x"], "expected int at '[0]'"),
        (list[int], "abc", "expected a list"),
        (dict[str, str], [("a", "b")], "expected a mapping"),
        (typing.List[int], "abc", "expected a list"),  # noqa: UP006
        (int | None, "x", "expected int"),
        (list[dict[str, int]], [{"a": "b"}], "expected int at '[0].a'"),
    ],
)
def test_a_generic_rejects_a_mismatched_value(
    schema: object, value: object, message: str
) -> None:
    """The type arguments are checked, with the path to the offending value."""
    with pytest.raises(MultipleInvalid) as excinfo:
        Schema(schema)(value)
    assert str(excinfo.value) == message


def test_a_generic_is_not_called_as_a_constructor() -> None:
    """list[int] no longer explodes a string into characters, as voluptuous does."""
    with pytest.raises(MultipleInvalid):
        Schema(list[str])("abc")


def test_a_generic_validates_like_its_structural_twin() -> None:
    """dict[str, list[int]] gives the same result and error as {str: [int]}."""
    generic = Schema(dict[str, list[int]])
    structural = Schema({str: [int]})
    assert generic({"a": [1]}) == structural({"a": [1]})

    with pytest.raises(MultipleInvalid) as from_generic:
        generic({"a": [1, "x"]})
    with pytest.raises(MultipleInvalid) as from_structural:
        structural({"a": [1, "x"]})
    assert str(from_generic.value) == str(from_structural.value)


def test_a_generic_nested_as_a_mapping_value_reports_the_full_path() -> None:
    """A generic under a marker key checks its arguments, with the key in the path."""
    schema = Schema({Required("ids"): list[str], Optional("extras"): dict[str, str]})
    assert schema({"ids": ["a"], "extras": {"k": "v"}}) == {
        "ids": ["a"],
        "extras": {"k": "v"},
    }
    with pytest.raises(MultipleInvalid) as excinfo:
        schema({"ids": ["a"], "extras": {"k": 1}})
    assert str(excinfo.value) == "expected str at 'extras.k'"


def test_a_generic_of_an_enum_coerces_to_members() -> None:
    """list[SomeEnum] coerces each value to a member, like a bare enum schema."""
    assert Schema(list[_Color])(["red"]) == [_Color.RED]
    with pytest.raises(MultipleInvalid):
        Schema(list[_Color])(["blue"])


def test_a_generic_of_a_dataclass_builds_the_dataclass() -> None:
    """list[SomeDataclass] validates each item as that dataclass."""
    assert Schema(list[_Point])([{"x": 1}]) == [_Point(x=1)]


def test_a_literal_validates_membership() -> None:
    """Literal["a", "b"] accepts its values and rejects anything else."""
    schema = Schema(typing.Literal["a", "b"])
    assert schema("a") == "a"
    with pytest.raises(MultipleInvalid):
        schema("c")


def test_annotated_metadata_runs_as_validators() -> None:
    """Annotated[int, Range(min=5)] applies the Range on top of the int check."""
    schema = Schema(typing.Annotated[int, Range(min=5)])
    assert schema(5) == 5
    with pytest.raises(MultipleInvalid):
        schema(3)


def test_the_enclosing_extra_policy_reaches_a_generic_dict() -> None:
    """A dict[str, int] inside an ALLOW_EXTRA schema still checks its values."""
    schema = Schema({"data": dict[str, int]}, extra=ALLOW_EXTRA)
    assert schema({"data": {"a": 1}, "other": 1}) == {"data": {"a": 1}, "other": 1}
    with pytest.raises(MultipleInvalid):
        schema({"data": {"a": "b"}})


def test_the_compiled_engine_agrees() -> None:
    """The generated validator gives the same result and error as the interpreter."""
    shape = {Required("ids"): list[int], Optional("map"): dict[str, str]}
    interpreted = Schema(shape)
    compiled = Schema(shape, compile=True).compile()
    data = {"ids": [1], "map": {"a": "b"}}
    assert compiled(data) == interpreted(data)

    bad = {"ids": [1, "x"], "map": {"a": 1}}
    with pytest.raises(MultipleInvalid) as from_interpreted:
        interpreted(bad)
    with pytest.raises(MultipleInvalid) as from_compiled:
        compiled(bad)
    assert str(from_compiled.value) == str(from_interpreted.value)
