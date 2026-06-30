"""The Forbidden marker: assert a key is absent (voluptuous issue #193).

probatio carries this forward as a marker in the Required/Optional/Remove family.
A Forbidden key fails validation when present and is fine when absent; its mapped
value is never validated.
"""

from __future__ import annotations

import pytest

from probatio import (
    ALLOW_EXTRA,
    Forbidden,
    MultipleInvalid,
    Optional,
    Required,
    Schema,
)
from probatio.codecs.fields import serialize
from probatio.codecs.jsonschema import to_json_schema


def test_absent_forbidden_key_is_fine() -> None:
    """A schema with a Forbidden key validates data that omits the key."""
    schema = Schema({Required("id"): int, Forbidden("password"): object})
    assert schema({"id": 1}) == {"id": 1}


def test_present_forbidden_key_fails() -> None:
    """A Forbidden key that is present fails with a path and a code."""
    schema = Schema({Forbidden("password"): object})
    with pytest.raises(MultipleInvalid) as caught:
        schema({"password": "x"})

    error = caught.value.errors[0]
    assert error.path == ["password"]
    assert error.error_message == "key not allowed"
    assert error.code == "forbidden_key"


def test_forbidden_uses_a_custom_message() -> None:
    """A Forbidden marker's own msg replaces the default."""
    schema = Schema({Forbidden("secret", msg="no secrets here"): object})
    with pytest.raises(MultipleInvalid) as caught:
        schema({"secret": 1})
    assert caught.value.errors[0].error_message == "no secrets here"


def test_forbidden_fires_under_allow_extra() -> None:
    """A Forbidden key is matched, so ALLOW_EXTRA does not let it slip through."""
    schema = Schema({Forbidden("p"): object}, extra=ALLOW_EXTRA)
    with pytest.raises(MultipleInvalid):
        schema({"p": 1})


def test_forbidden_is_not_required_under_required_schema() -> None:
    """With required=True, a Forbidden key is not itself demanded."""
    schema = Schema({Required("a"): int, Forbidden("b"): object}, required=True)
    assert schema({"a": 1}) == {"a": 1}


def test_extend_can_forbid_a_previously_optional_key() -> None:
    """Extending a schema with a Forbidden marker replaces an Optional for the key."""
    derived = Schema({Optional("x"): int}).extend({Forbidden("x"): object})
    assert derived({}) == {}
    with pytest.raises(MultipleInvalid):
        derived({"x": 1})


def test_forbidden_type_key_forbids_matching_keys() -> None:
    """A Forbidden type key rejects any key of that type, via the validator path."""
    schema = Schema({Forbidden(str): object, int: str})
    assert schema({5: "v"}) == {5: "v"}

    with pytest.raises(MultipleInvalid) as caught:
        schema({"nope": 1})

    assert caught.value.errors[0].path == ["nope"]


def test_forbidden_exports_a_false_json_schema_property() -> None:
    """to_json_schema renders a Forbidden key as a false property schema."""
    schema = Schema({Required("id"): int, Forbidden("password"): object})
    result = to_json_schema(schema)

    assert result["properties"]["password"] is False
    assert "password" not in result.get("required", [])


def test_forbidden_is_omitted_from_the_field_list() -> None:
    """serialize leaves a Forbidden key out of the rendered field list."""
    fields = serialize(Schema({Required("id"): int, Forbidden("password"): object}))
    names = {field["name"] for field in fields}

    assert names == {"id"}
