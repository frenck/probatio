"""The type-to-validator registry consulted by the annotation-driven builders.

Registering a validator for a type makes a dataclass (or other annotation-driven)
field of that type build to the validator instead of a bare ``isinstance`` check,
so coercion is opt-in. The registry is read at schema-build time and baked in, and
the hand-written ``Schema(type)`` path is never affected (ADR-008).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any

import pytest

from probatio import (
    Coerce,
    DataclassSchema,
    Range,
    Schema,
    clear_type_registry,
    register_type,
    type_registry,
)
from probatio.error import MultipleInvalid

if TYPE_CHECKING:
    from collections.abc import Iterator


def _parse(value: Any) -> datetime:
    """Parse an ISO 8601 string into a datetime."""
    return datetime.fromisoformat(value)


@pytest.fixture(autouse=True)
def _reset_registry() -> Iterator[None]:
    """Clear any process-wide registration a test made, so none leak."""
    yield
    clear_type_registry()


@dataclass
class Event:
    """A dataclass with a scalar and a container field of the same type."""

    when: datetime
    items: list[datetime] = field(default_factory=list)


def test_unregistered_type_is_strict() -> None:
    """Without a registration, a datetime field rejects a string."""
    with pytest.raises(MultipleInvalid) as caught:
        DataclassSchema(Event)({"when": "2020-01-01T00:00"})
    assert caught.value.errors[0].path == ["when"]


def test_global_registration_coerces_including_containers() -> None:
    """A registered validator applies to the field and to nested elements."""
    register_type(datetime, Coerce(_parse))
    result = DataclassSchema(Event)(
        {"when": "2020-01-01T12:00", "items": ["2021-06-01T00:00"]},
    )
    assert result.when == datetime(2020, 1, 1, 12, 0)
    assert result.items == [datetime(2021, 6, 1, 0, 0)]


def test_hand_written_schema_is_unaffected() -> None:
    """The registry does not touch a hand-written Schema(type) isinstance check."""
    register_type(datetime, Coerce(_parse))
    with pytest.raises(MultipleInvalid):
        Schema(datetime)("2020-01-01T00:00")


def test_registration_is_baked_in_at_build_time() -> None:
    """A schema built while registered keeps coercing after the registry clears."""
    register_type(datetime, Coerce(_parse))
    schema = DataclassSchema(Event)
    clear_type_registry()
    assert schema({"when": "2022-01-01T00:00"}).when == datetime(2022, 1, 1, 0, 0)


def test_a_schema_built_after_clear_is_strict_again() -> None:
    """Clearing the registry makes the next build strict; built schemas are stable."""
    register_type(datetime, Coerce(_parse))
    DataclassSchema(Event)  # built-and-baked, then dropped
    clear_type_registry()
    with pytest.raises(MultipleInvalid):
        DataclassSchema(Event)({"when": "2022-01-01T00:00"})


def test_scoped_registry_applies_inside_the_block_only() -> None:
    """type_registry applies to schemas built in the block and restores on exit."""
    with type_registry({datetime: Coerce(_parse)}):
        inside = DataclassSchema(Event)({"when": "2023-01-01T00:00"})
    assert inside.when == datetime(2023, 1, 1, 0, 0)
    with pytest.raises(MultipleInvalid):
        DataclassSchema(Event)({"when": "2023-01-01T00:00"})


def test_scoped_registration_wins_over_global() -> None:
    """A scoped registration overrides a process-wide one for the same type."""
    register_type(datetime, Coerce(lambda _v: datetime(1970, 1, 1)))
    with type_registry({datetime: Coerce(_parse)}):
        assert DataclassSchema(Event)({"when": "2024-05-05T00:00"}).when == datetime(
            2024,
            5,
            5,
        )


def test_registry_composes_with_an_annotated_constraint() -> None:
    """An Annotated validator layers on top of the registry's coercion."""

    @dataclass
    class Bounded:
        """A field that coerces, then range-checks the coerced value."""

        when: Annotated[datetime, Range(min=datetime(2000, 1, 1))]

    register_type(datetime, Coerce(_parse))
    assert DataclassSchema(Bounded)({"when": "2010-01-01T00:00"}).when == datetime(
        2010,
        1,
        1,
    )
    with pytest.raises(MultipleInvalid) as caught:
        DataclassSchema(Bounded)({"when": "1990-01-01T00:00"})
    assert caught.value.errors[0].path == ["when"]


def test_register_type_rejects_a_non_type() -> None:
    """Registering against something that is not a type is a clear error."""
    with pytest.raises(TypeError, match="expects a type"):
        register_type("datetime", Coerce(_parse))  # type: ignore[arg-type]


def test_type_registry_rejects_a_non_type_key() -> None:
    """A scoped registration with a non-type key fails on entering the block."""
    with (
        pytest.raises(TypeError, match="must be types"),
        type_registry({"datetime": Coerce(_parse)}),  # type: ignore[dict-item]
    ):
        pass  # pragma: no cover - the error fires on entering the block


def test_re_registering_replaces_the_previous_entry() -> None:
    """A second registration for a type replaces the first."""
    register_type(datetime, Coerce(lambda _v: datetime(1970, 1, 1)))
    register_type(datetime, Coerce(_parse))
    assert DataclassSchema(Event)({"when": "2025-01-01T00:00"}).when == datetime(
        2025,
        1,
        1,
    )
