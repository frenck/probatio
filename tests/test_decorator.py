"""Tests for the ``probatio`` decorator: annotation-driven argument validation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated

import pytest

from probatio import (
    Coerce,
    Length,
    MultipleInvalid,
    Range,
    SchemaError,
    probatio,
)


def test_infers_a_validator_from_each_annotation() -> None:
    """An annotated parameter is checked against its type."""

    @probatio
    def add(a: int, b: int) -> int:
        return a + b

    assert add(2, 3) == 5


def test_argument_failure_raises_multiple_invalid() -> None:
    """A parameter that fails its type raises, naming the parameter in the path."""

    @probatio
    def add(a: int, b: int) -> int:
        return a + b

    with pytest.raises(MultipleInvalid, match=r"data\['a'\]"):
        add("nope", 3)


def test_coerces_the_value_the_body_receives() -> None:
    """A coercing annotation hands the body the converted value."""

    @probatio
    def widen(value: Annotated[int, Coerce(int)]) -> int:
        return value

    assert widen("41") == 41


def test_unannotated_parameter_passes_through() -> None:
    """A parameter without an annotation is not validated."""

    @probatio
    def keep(value) -> object:  # type: ignore[no-untyped-def]
        return value

    marker = object()
    assert keep(marker) is marker


def test_self_is_skipped_on_a_method() -> None:
    """An unannotated ``self`` is left alone, so the decorator drops onto a method."""

    class Box:
        @probatio
        def scale(self, factor: Annotated[int, Range(min=0)]) -> int:
            return factor * 2

    assert Box().scale(3) == 6
    with pytest.raises(MultipleInvalid):
        Box().scale(-1)


def test_constraints_layer_after_the_type_check() -> None:
    """A ``constraints`` entry runs after the inferred type, like a dataclass rule."""

    @probatio({"name": Length(min=2)})
    def greet(name: str) -> str:
        return f"hi {name}"

    assert greet("ab") == "hi ab"
    with pytest.raises(MultipleInvalid, match="length"):
        greet("a")


def test_constraint_on_an_unannotated_parameter() -> None:
    """A constraint validates a parameter that has no annotation of its own."""

    @probatio({"value": Range(min=0)})
    def keep(value) -> object:  # type: ignore[no-untyped-def]
        return value

    assert keep(5) == 5
    with pytest.raises(MultipleInvalid):
        keep(-1)


def test_constraint_naming_an_unknown_parameter_is_a_schema_error() -> None:
    """A constraint for a parameter that does not exist is refused at decoration."""

    with pytest.raises(SchemaError, match="no such parameter"):

        @probatio({"nope": Range(min=0)})
        def f(value: int) -> int:
            return value


def test_constraint_on_a_variadic_parameter_is_a_schema_error() -> None:
    """A constraint targeting ``*args``/``**kwargs`` is refused, not silently dropped."""

    with pytest.raises(SchemaError, match="variadic"):

        @probatio({"rest": Range(min=0)})
        def f(*rest: int) -> int:
            return sum(rest)


def test_unresolved_return_annotation_is_ignored_when_return_off() -> None:
    """A return annotation that cannot resolve does not break decoration when off."""

    @probatio
    def f(value: int) -> Missing:  # type: ignore[name-defined]  # noqa: F821
        return value

    assert f(3) == 3


def test_unresolved_variadic_annotation_is_ignored() -> None:
    """An unresolved annotation on a skipped ``*args`` does not break decoration."""

    @probatio
    def f(value: int, *rest: Missing) -> int:  # type: ignore[name-defined]  # noqa: F821, ARG001
        return value

    assert f(3, "a", "b") == 3


def test_none_annotation_requires_none() -> None:
    """A parameter typed ``None`` must be ``None``; it is a schema, not "skip"."""

    @probatio
    def f(x: None) -> None:
        return x

    assert f(None) is None
    with pytest.raises(MultipleInvalid):
        f(5)


def test_none_constraint_requires_none() -> None:
    """A constraint of ``None`` is a real schema, not read as an absent entry."""

    @probatio({"value": None})
    def f(value) -> object:  # type: ignore[no-untyped-def]
        return value

    assert f(None) is None
    with pytest.raises(MultipleInvalid):
        f(5)


def test_return_validation_is_off_by_default() -> None:
    """Without ``returns`` the result is not validated, even with a return annotation."""

    @probatio
    def lies() -> int:
        return "not an int"  # type: ignore[return-value]

    assert lies() == "not an int"


def test_returns_true_validates_against_the_annotation() -> None:
    """``returns=True`` validates the result against the ``-> R`` annotation."""

    @probatio(returns=True)
    def clamp(value: int) -> Annotated[int, Range(min=0)]:
        return value

    assert clamp(5) == 5
    with pytest.raises(MultipleInvalid):
        clamp(-1)


def test_returns_true_without_annotation_is_a_schema_error() -> None:
    """``returns=True`` needs a return annotation to validate against."""

    with pytest.raises(SchemaError, match="return annotation"):

        @probatio(returns=True)
        def f(value: int):  # type: ignore[no-untyped-def]
            return value


def test_returns_schema_validates_against_it() -> None:
    """A schema passed as ``returns`` validates the result directly."""

    @probatio({"age": Range(min=0)}, returns=int)
    def age_of(age: int) -> int:
        return age

    assert age_of(30) == 30


def test_returns_false_is_off() -> None:
    """``returns=False`` skips result validation, like the default."""

    @probatio(returns=False)
    def lies() -> int:
        return "nope"  # type: ignore[return-value]

    assert lies() == "nope"


def test_var_positional_and_keyword_pass_through() -> None:
    """``*args`` and ``**kwargs`` carry no schema and reach the body untouched."""

    @probatio
    def collect(first: int, *rest: object, **options: object) -> tuple:
        return first, rest, options

    assert collect(1, "a", "b", x=9) == (1, ("a", "b"), {"x": 9})


def test_positional_only_parameter() -> None:
    """A positional-only parameter is validated and passed back positionally."""

    @probatio
    def f(value: Annotated[int, Coerce(int)], /) -> int:
        return value

    assert f("7") == 7


def test_keyword_only_parameter() -> None:
    """A keyword-only parameter is validated."""

    @probatio
    def f(*, value: Annotated[int, Range(min=0)]) -> int:
        return value

    assert f(value=3) == 3
    with pytest.raises(MultipleInvalid):
        f(value=-1)


def test_omitted_default_is_not_validated() -> None:
    """A parameter left to its default is not run through its schema."""

    @probatio
    def f(value: Annotated[int, Range(min=0)] = -1) -> int:
        return value

    assert f() == -1
    with pytest.raises(MultipleInvalid):
        f(-1)


def test_no_annotated_parameters_is_a_no_op_input() -> None:
    """A callable with nothing to validate still calls through cleanly."""

    @probatio
    def f(a, b) -> object:  # type: ignore[no-untyped-def]
        return (a, b)

    assert f(1, 2) == (1, 2)


def test_wrapped_attribute_skips_validation() -> None:
    """The original callable stays reachable through ``__wrapped__`` for trusted input."""

    @probatio
    def widen(value: Annotated[int, Coerce(int)]) -> int:
        return value

    assert widen.__wrapped__("41") == "41" * 1  # not coerced


@dataclass
class Point:
    """A point, used to test that a dataclass parameter is constructed."""

    x: int
    y: int


def test_dataclass_parameter_is_constructed() -> None:
    """A parameter typed as a dataclass validates a mapping into an instance."""

    @probatio
    def move(point: Point) -> int:
        return point.x + point.y

    assert move({"x": 1, "y": 2}) == 3


def test_annotation_that_cannot_resolve_is_a_schema_error() -> None:
    """An unresolvable annotation is reported as a schema error at decoration."""

    def f(value: DoesNotExist) -> int:  # type: ignore[name-defined]  # noqa: F821
        return value  # type: ignore[return-value]

    with pytest.raises(SchemaError, match="cannot resolve"):
        probatio(f)


def test_empty_call_form() -> None:
    """``@probatio()`` with no arguments behaves like the bare form."""

    @probatio()
    def add(a: int, b: int) -> int:
        return a + b

    assert add(2, 3) == 5


def test_async_function_is_validated() -> None:
    """A coroutine function validates its arguments and coerces the same way."""

    @probatio
    async def widen(value: Annotated[int, Coerce(int)]) -> int:
        return value + 1

    assert asyncio.run(widen("9")) == 10


def test_async_argument_failure_raises() -> None:
    """A failing argument to a coroutine function raises before the body runs."""

    ran = False

    @probatio
    async def f(value: int) -> int:
        nonlocal ran
        ran = True
        return value

    with pytest.raises(MultipleInvalid):
        asyncio.run(f("nope"))
    assert ran is False


def test_async_return_validation() -> None:
    """``returns`` validates the awaited result of a coroutine function."""

    @probatio(returns=True)
    async def f(value: int) -> Annotated[int, Range(min=0)]:
        return value

    assert asyncio.run(f(4)) == 4
    with pytest.raises(MultipleInvalid):
        asyncio.run(f(-1))
