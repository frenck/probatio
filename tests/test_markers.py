"""Tests for schema markers."""

from __future__ import annotations

import copy

from probatio import (
    UNDEFINED,
    Extra,
    Optional,
    Remove,
    Required,
)
from probatio.markers import Undefined, default_factory


def test_marker_wraps_the_key_schema() -> None:
    """A marker keeps the underlying key as .schema and renders as it."""
    marker = Required("name")
    assert marker.schema == "name"
    assert str(marker) == "name"
    assert repr(marker) == repr("name")


def test_marker_equals_the_bare_key_both_ways() -> None:
    """A marker compares equal to its bare key from either side."""
    marker = Optional("port")
    key = "port"
    assert marker == key
    # Reflected: str.__eq__ defers, so the marker's __eq__ must answer.
    assert key == marker


def test_markers_match_when_their_keys_match() -> None:
    """Two markers are equal when they wrap the same key, regardless of kind."""
    assert Required("name") == Optional("name")
    assert hash(Required("name")) == hash("name")


def test_marker_is_interchangeable_as_a_dict_key() -> None:
    """A marker hashes like its key, so it indexes the same dict slot."""
    mapping = {Required("name"): 1}
    assert mapping["name"] == 1
    assert "name" in mapping


def test_description_is_writable() -> None:
    """description is a plain attribute that downstream code can set."""
    marker = Optional("name")
    marker.description = "the friendly name"
    assert marker.description == "the friendly name"


def test_description_holds_structured_data() -> None:
    """description may hold any value, not only a string (voluptuous parity).

    Home Assistant stuffs a dict like ``{"suggested_value": ...}`` into a marker's
    description, so the type must stay as permissive as voluptuous left it.
    """
    marker = Optional("name", description={"suggested_value": 42})
    assert marker.description == {"suggested_value": 42}
    marker.description = {"suggested_value": "later"}
    assert marker.description["suggested_value"] == "later"


def test_copy_yields_an_independent_marker() -> None:
    """copy.copy gives an equal but separate marker that can be mutated."""
    marker = Optional("name")
    clone = copy.copy(marker)
    assert clone == marker
    assert clone is not marker
    clone.schema = "other"
    assert marker.schema == "name"


def test_required_default_is_undefined_by_default() -> None:
    """A required key has no default unless one is given."""
    assert Required("name").default is UNDEFINED


def test_optional_wraps_a_plain_default_in_a_callable() -> None:
    """A plain default value is exposed as a zero-argument callable."""
    marker = Optional("port", default=8080)
    assert marker.default is not UNDEFINED
    assert marker.default() == 8080


def test_optional_passes_a_callable_default_through() -> None:
    """A callable default is kept as-is and used as the factory."""
    marker = Optional("items", default=list)
    assert marker.default() == []


def test_remove_markers_are_distinct_keys() -> None:
    """Remove markers compare by identity, so several can coexist in a dict."""
    mapping = {Remove(str): 1, Remove(int): 2}
    assert len(mapping) == 2
    assert Remove(str) != Remove(str)
    assert "Remove(" in repr(Remove(str))


def test_default_factory_handles_each_case() -> None:
    """default_factory returns UNDEFINED, the callable, or a value factory."""
    assert default_factory(UNDEFINED) is UNDEFINED
    assert default_factory(str)() == ""
    assert default_factory(5)() == 5


def test_undefined_has_a_readable_repr() -> None:
    """The undefined sentinel renders clearly for debugging."""
    assert isinstance(UNDEFINED, Undefined)
    assert repr(UNDEFINED) == "<undefined>"


def test_extra_is_a_callable_sentinel_with_a_readable_repr() -> None:
    """Extra is callable (so codecs treat it as a catch-all) and reads as 'Extra'."""
    assert callable(Extra)
    assert repr(Extra) == "Extra"


def test_markers_sort_by_their_underlying_key() -> None:
    """A list of markers sorts alphabetically by key, matching voluptuous."""
    foo = Required("foo")
    bar = Required("bar")
    assert sorted([foo, bar]) == [bar, foo]


def test_a_marker_orders_against_a_bare_key() -> None:
    """A marker compares against a plain value by its underlying key."""
    assert Optional("classification") < "name"
    assert not Required("zebra") < "name"
