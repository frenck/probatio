"""Tests for the English message catalog."""

from __future__ import annotations

import re
from pathlib import Path
from string import Formatter

import pytest

from probatio import MultipleInvalid, Schema
from probatio._messages import CATALOG, render

_DOCS_TABLE = (
    Path(__file__).parent.parent
    / "docs"
    / "src"
    / "content"
    / "docs"
    / "reference"
    / "translation-keys.md"
)


def test_every_template_is_well_formed() -> None:
    """Every catalog template parses as a str.format template."""
    formatter = Formatter()
    for key, template in CATALOG.items():
        # parse() raises ValueError on a malformed template.
        assert list(formatter.parse(template)), key


def test_keys_are_snake_case() -> None:
    """Every translation key is a stable snake_case identifier."""
    for key in CATALOG:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", key), key


def test_render_formats_placeholders() -> None:
    """render interpolates placeholders into the template."""
    assert render("length_min", {"min": 10}) == "length of value must be at least 10"


def test_render_without_placeholders_returns_the_template() -> None:
    """render returns the bare template when there is nothing to interpolate."""
    assert render("required", None) == "required key not provided"


def test_docs_reference_mirrors_the_catalog() -> None:
    """The translation-keys reference page lists exactly the catalog, verbatim.

    The keys are public API; this pins the documentation to the source of
    truth, so adding, renaming, or rewording a key without updating the docs
    fails here instead of shipping drift.
    """
    documented: dict[str, str] = {}
    for line in _DOCS_TABLE.read_text().splitlines():
        match = re.fullmatch(r"\| `([a-z0-9_]+)` \| `(.*)` \|", line)
        if match:
            documented[match.group(1)] = match.group(2).replace("\\|", "|")

    assert documented == CATALOG


def test_suggestion_suffix_renders_from_the_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The did-you-mean fragment comes from the catalog, so locales can swap it."""
    monkeypatch.setitem(CATALOG, "did_you_mean", ", bedoelde je {candidates}?")
    schema = Schema({"name": str})
    with pytest.raises(MultipleInvalid) as caught:
        schema({"nmae": "x"})
    error = caught.value.errors[0]
    assert error.error_message == "not a valid option, bedoelde je 'name'?"
    assert error.context["candidates"] == ["name"]
