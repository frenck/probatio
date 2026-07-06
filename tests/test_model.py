"""The SchemaMixin: a dataclass gets a cached, validating from_dict by inheriting it."""

from __future__ import annotations

import gc
import weakref
from dataclasses import dataclass, field, make_dataclass
from typing import Annotated

import pytest

from probatio import (
    ALLOW_EXTRA,
    REMOVE_EXTRA,
    Coerce,
    MultipleInvalid,
    SchemaError,
    SchemaMixin,
)


@dataclass
class Point(SchemaMixin):
    """A closed model (the default PREVENT_EXTRA)."""

    x: int
    y: int = 0


@dataclass
class Loose(SchemaMixin, extra=REMOVE_EXTRA):
    """A model that drops unknown keys."""

    name: str = ""


@dataclass
class LooseChild(Loose):
    """A subclass that sets no policy of its own, so it inherits Loose's."""

    extra_field: int = 0


@dataclass(frozen=True)
class Inner(SchemaMixin, extra=REMOVE_EXTRA):
    """A nested frozen model with an all-defaulted field."""

    a: int = 0


@dataclass(frozen=True)
class Outer(SchemaMixin, extra=REMOVE_EXTRA):
    """A frozen model exercising the nested fixes through from_dict."""

    inner: Inner = field(default_factory=Inner)
    label: Annotated[
        int | None, Coerce(lambda v: None if v in (None, "-1") else int(v))
    ] = None


def test_from_dict_validates_and_constructs() -> None:
    """from_dict validates the mapping and returns a built instance."""
    result = Point.from_dict({"x": 1, "y": 2})
    assert result == Point(x=1, y=2)
    assert isinstance(result, Point)


def test_from_dict_reports_a_validation_error() -> None:
    """A bad field is reported like any DataclassSchema call."""
    with pytest.raises(MultipleInvalid) as caught:
        Point.from_dict({"x": "no"})
    assert caught.value.errors[0].path == ["x"]


def test_default_policy_is_prevent_extra() -> None:
    """Without an extra argument, an unknown key is rejected."""
    with pytest.raises(MultipleInvalid):
        Point.from_dict({"x": 1, "junk": 2})


def test_extra_policy_is_applied() -> None:
    """extra=REMOVE_EXTRA on the class drops an unknown key."""
    assert Loose.from_dict({"name": "app", "junk": 1}) == Loose(name="app")


def test_extra_is_inherited_by_a_subclass() -> None:
    """A subclass that sets no policy keeps the parent's extra."""
    assert LooseChild._probatio_extra == REMOVE_EXTRA
    result = LooseChild.from_dict({"name": "app", "extra_field": 3, "junk": 9})
    assert result == LooseChild(name="app", extra_field=3)


def test_a_subclass_can_override_the_policy() -> None:
    """A subclass may pin its own extra, not the parent's."""

    @dataclass
    class Strict(Loose, extra=ALLOW_EXTRA):
        pass

    assert Strict._probatio_extra == ALLOW_EXTRA


def test_schema_is_built_once_and_reused() -> None:
    """Two from_dict calls succeed; the schema is built on the first and cached."""
    first = Point.from_dict({"x": 1})
    second = Point.from_dict({"x": 2})
    assert first == Point(x=1)
    assert second == Point(x=2)


def test_the_nested_fixes_flow_through_from_dict() -> None:
    """Nested extra, an instance default, and a union coercer all apply via from_dict."""
    result = Outer.from_dict(
        {"inner": {"a": 9, "innerjunk": 1}, "label": "5", "top": 2}
    )
    assert result == Outer(inner=Inner(a=9), label=5)
    assert Outer.from_dict({}) == Outer(inner=Inner(a=0), label=None)


def test_a_non_dataclass_subclass_raises() -> None:
    """Using the mixin on a non-dataclass fails clearly when from_dict is called."""

    class NotADataclass(SchemaMixin):
        pass

    with pytest.raises(SchemaError):
        NotADataclass.from_dict({})


def test_the_cached_schema_does_not_pin_a_throwaway_class() -> None:
    """A dynamically created model is collectible after use; the cache dies with it."""
    tmp = make_dataclass("Tmp", [("v", int)], bases=(SchemaMixin,))
    tmp.from_dict({"v": 5})  # builds and caches the schema on the class
    ref = weakref.ref(tmp)
    del tmp
    gc.collect()
    assert ref() is None
