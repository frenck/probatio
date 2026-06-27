"""Key aliasing: accept a value under alternate names, emit it under one canonical.

``Alias`` is a mapping-key marker. It accepts the value under any of its names,
in declaration order (first present wins), and stores it under the canonical name.
A pre-pass renames the accepted name before the normal candidate machinery runs,
so aliasing composes with defaults, required keys, and the extra-key policy.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

from probatio import ALLOW_EXTRA, Alias, Schema
from probatio.error import MultipleInvalid, SchemaError


def test_alias_maps_to_the_canonical_output() -> None:
    """A value provided under an alias is stored under the canonical name."""
    schema = Schema({Alias("user_name", "user-name"): str})
    assert schema({"user-name": "ada"}) == {"user_name": "ada"}


def test_canonical_name_is_accepted_by_default() -> None:
    """By default the canonical name is an accepted input name too."""
    schema = Schema({Alias("user_name", "user-name"): str})
    assert schema({"user_name": "ada"}) == {"user_name": "ada"}


def test_first_present_alias_wins_by_declaration_order() -> None:
    """Among present aliases, the earliest in declaration order wins, not input."""
    schema = Schema({Alias("n", "a", "b", accept_canonical=False): str})
    # ``a`` (rank 0) wins over ``b`` (rank 1) regardless of which comes first in
    # the input, so both input orders resolve to the same value.
    assert schema({"b": "from_b", "a": "from_a"}) == {"n": "from_a"}
    assert schema({"a": "from_a", "b": "from_b"}) == {"n": "from_a"}


def test_canonical_leads_the_search() -> None:
    """When the canonical and an alias both appear, the canonical wins."""
    schema = Schema({Alias("name", "alias"): str})
    assert schema({"alias": "x", "name": "canonical"}) == {"name": "canonical"}


def test_accept_canonical_false_rejects_the_canonical_name() -> None:
    """With accept_canonical=False only the aliases are accepted; the canonical is
    not an input name, so a value under it is dropped (a strict rename)."""
    schema = Schema({Alias("n", "a", accept_canonical=False): str})
    assert schema({"a": "ok"}) == {"n": "ok"}
    assert schema({"n": "ignored"}) == {}


def test_alias_default_applies_when_absent() -> None:
    """An absent aliased key fills its default under the canonical name."""
    schema = Schema({Alias("port", "Port", default=8080): int})
    assert schema({}) == {"port": 8080}


def test_required_alias_missing_reports_the_canonical_path() -> None:
    """A required aliased key absent under every name errors at the canonical."""
    schema = Schema({Alias("name", "nm", required=True): str})
    with pytest.raises(MultipleInvalid) as caught:
        schema({})
    assert caught.value.errors[0].path == ["name"]


def test_required_alias_satisfied_by_an_alias() -> None:
    """A required aliased key is satisfied when any of its names is present."""
    schema = Schema({Alias("name", "nm", required=True): str})
    assert schema({"nm": "ada"}) == {"name": "ada"}


def test_alias_value_is_validated_under_the_canonical_path() -> None:
    """A wrong-typed value under an alias reports the error at the canonical."""
    schema = Schema({Alias("count", "n"): int})
    with pytest.raises(MultipleInvalid) as caught:
        schema({"n": "not an int"})
    assert caught.value.errors[0].path == ["count"]


def test_alias_colliding_with_another_key_is_a_schema_error() -> None:
    """An alias that names another key in the schema is rejected at build time."""
    with pytest.raises(SchemaError, match="collides"):
        Schema({Alias("a", "b"): str, "b": int})


def test_same_alias_in_two_specs_is_a_schema_error() -> None:
    """An alias used by two keys is ambiguous, rejected at build time."""
    with pytest.raises(SchemaError, match="more than one"):
        Schema({Alias("a", "shared"): str, Alias("b", "shared"): int})


def test_alias_without_any_alias_name_is_a_schema_error() -> None:
    """Alias needs at least one alias besides the canonical key."""
    with pytest.raises(SchemaError, match="at least one"):
        Alias("lonely")


def test_unknown_key_still_errors_under_prevent_extra() -> None:
    """Aliasing does not loosen the extra-key policy for unrelated keys."""
    schema = Schema({Alias("a", "b"): str})
    with pytest.raises(MultipleInvalid):
        schema({"unknown": 1})


def test_allow_extra_passes_unknown_keys_through() -> None:
    """Under ALLOW_EXTRA an unknown key passes through and the alias still resolves."""
    schema = Schema({Alias("a", "b"): str}, extra=ALLOW_EXTRA)
    assert schema({"b": "x", "keep": 1}) == {"a": "x", "keep": 1}


def test_alias_resolves_a_non_dict_mapping() -> None:
    """A Mapping that is not a dict is normalized and validated like a dict."""
    schema = Schema({Alias("a", "b"): str})
    assert schema(MappingProxyType({"b": "x"})) == {"a": "x"}


def test_alias_marker_behaves_as_its_canonical_key() -> None:
    """The marker hashes and renders as the canonical key, like other markers."""
    marker = Alias("name", "alias")
    assert hash(marker) == hash("name")
    assert str(marker) == "name"
