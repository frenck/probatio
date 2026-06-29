"""Tests for the probatio package metadata."""

from __future__ import annotations

from importlib import metadata

import pytest

import probatio


def test_version_matches_package_metadata() -> None:
    """__version__ is resolved from the installed package metadata."""
    assert probatio.__version__ == metadata.version("probatio")


def test_version_is_a_non_empty_string() -> None:
    """__version__ is a usable version string."""
    assert isinstance(probatio.__version__, str)
    assert probatio.__version__


def test_unknown_attribute_raises_attribute_error() -> None:
    """Accessing an undefined module attribute still raises AttributeError."""
    with pytest.raises(AttributeError):
        _ = probatio.does_not_exist
