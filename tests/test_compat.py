"""Tests for the voluptuous drop-in compatibility layer."""

from __future__ import annotations

import sys
import warnings
from typing import TYPE_CHECKING

import pytest

import probatio
from probatio import error
from probatio._vol_shim.schema_builder import _compile_scalar
from probatio.compat import install_as_voluptuous

if TYPE_CHECKING:
    from collections.abc import Iterator

_VOLUPTUOUS_KEYS = [
    "voluptuous",
    "voluptuous.error",
    "voluptuous.humanize",
    "voluptuous.validators",
    "voluptuous.schema_builder",
]


def test_compile_scalar_type() -> None:
    """A type scalar validates instances and rejects others with TypeInvalid."""
    validate = _compile_scalar(int)
    assert validate([], 5) == 5
    with pytest.raises(error.TypeInvalid):
        validate(["p"], "x")


def test_compile_scalar_callable_ok_and_value_error() -> None:
    """A non-class callable scalar runs and maps ValueError to ValueInvalid."""

    def to_int(value: object) -> int:
        return int(value)  # type: ignore[arg-type, call-overload]

    coerce = _compile_scalar(to_int)
    assert coerce([], "5") == 5
    with pytest.raises(error.ValueInvalid):
        coerce([], "x")


def test_compile_scalar_callable_repaths_invalid() -> None:
    """A callable that raises Invalid has the current path prepended."""

    def picky(_value: object) -> object:
        message = "nope"
        raise error.Invalid(message)

    with pytest.raises(error.Invalid) as caught:
        _compile_scalar(picky)(["a"], 1)
    assert caught.value.path == ["a"]


def test_compile_scalar_value() -> None:
    """A plain value scalar matches by equality, else ScalarInvalid."""
    validate = _compile_scalar("on")
    assert validate([], "on") == "on"
    with pytest.raises(error.ScalarInvalid):
        validate([], "off")


@pytest.fixture
def _restore_voluptuous() -> Iterator[None]:
    """Snapshot and restore the voluptuous sys.modules entries around a test."""
    snapshot = {key: sys.modules.get(key) for key in _VOLUPTUOUS_KEYS}
    try:
        yield
    finally:
        for key, module in snapshot.items():
            if module is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = module


@pytest.mark.usefixtures("_restore_voluptuous")
def test_install_as_voluptuous_aliases_modules() -> None:
    """install_as_voluptuous makes voluptuous resolve to Probatio and its parts."""
    install_as_voluptuous()

    import voluptuous  # noqa: PLC0415
    from voluptuous import schema_builder  # noqa: PLC0415

    # The form dependencies actually use must resolve off sys.modules alone.
    from voluptuous.schema_builder import _compile_scalar as imported  # noqa: PLC0415

    # voluptuous is a distinct shim module, not probatio itself, but its names
    # resolve to probatio's.
    assert voluptuous is not probatio
    assert voluptuous.Schema is probatio.Schema
    assert sys.modules["voluptuous.error"].Invalid is error.Invalid
    # The internal helper that dependencies import directly is present and works.
    assert schema_builder._compile_scalar(int)([], 7) == 7
    assert imported(int)([], 7) == 7
    assert schema_builder.Schema is probatio.Schema


@pytest.mark.usefixtures("_restore_voluptuous")
def test_shim_exposes_only_voluptuous_surface() -> None:
    """The embedded surface table matches the pinned voluptuous, so it cannot rot."""
    import importlib  # noqa: PLC0415

    # Drop any shim registration so the real voluptuous loads from disk, not a
    # leftover shim from another test.
    for key in [
        k for k in sys.modules if k == "voluptuous" or k.startswith("voluptuous.")
    ]:
        del sys.modules[key]
    voluptuous = pytest.importorskip("voluptuous")
    util = importlib.import_module("voluptuous.util")
    schema_builder = importlib.import_module("voluptuous.schema_builder")
    err = importlib.import_module("voluptuous.error")
    validators = importlib.import_module("voluptuous.validators")

    from probatio._vol_shim import _surface  # noqa: PLC0415

    public = set(probatio.__all__)

    def real(mod: object) -> set[str]:
        """The voluptuous module's public names that probatio also provides."""
        return {name for name in public if hasattr(mod, name)}

    assert set(_surface.TOP) == real(voluptuous)
    assert set(_surface.UTIL) == real(util)
    assert set(_surface.SCHEMA_BUILDER) == real(schema_builder)
    assert set(_surface.ERROR) == real(err)
    assert set(_surface.VALIDATORS) == real(validators)


@pytest.mark.usefixtures("_restore_voluptuous")
def test_probatio_only_names_are_not_importable_via_the_shim() -> None:
    """A probatio addition is not reachable through the voluptuous shim."""
    install_as_voluptuous()
    import voluptuous  # noqa: PLC0415
    import voluptuous.validators  # noqa: PLC0415

    # CreditCard, Alias, and Immutable are probatio additions voluptuous never had.
    for name in ("CreditCard", "Alias", "Immutable", "TypedDictSchema"):
        assert not hasattr(voluptuous, name)
        assert not hasattr(voluptuous.validators, name)


@pytest.mark.usefixtures("_restore_voluptuous")
def test_install_as_voluptuous_is_quiet_when_not_shadowing() -> None:
    """With no voluptuous already imported, install does not warn."""
    sys.modules.pop("voluptuous", None)
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a warning would raise
        install_as_voluptuous()


@pytest.mark.usefixtures("_restore_voluptuous")
def test_install_as_voluptuous_warns_when_shadowing_real_voluptuous() -> None:
    """A real voluptuous already imported is shadowed, with a RuntimeWarning."""
    import types  # noqa: PLC0415

    sys.modules["voluptuous"] = types.ModuleType(
        "voluptuous"
    )  # stand-in for the real one
    with pytest.warns(RuntimeWarning, match="shadowing"):
        install_as_voluptuous()
