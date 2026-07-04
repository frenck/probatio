"""Tests for the JSON and YAML dumpers."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest

from probatio import (
    dump,
    dump_json,
    dump_toml,
    dump_yaml,
    load_json,
    load_toml,
    load_yaml,
)
from probatio.serde import _optional


def test_dump_json_round_trips_with_load_json() -> None:
    """A plain value dumps to JSON that load_json parses back unchanged."""
    value = {"name": "app", "ports": [80, 443], "on": True, "note": None}
    assert load_json(dump_json(value)) == value


def test_dump_json_normalizes_special_types() -> None:
    """Decimal, datetime/date/time, and set/tuple are normalized for JSON."""
    value = {
        "price": Decimal("1.5"),
        "when": datetime.datetime(2024, 1, 2, 3, 4, 5),
        "day": datetime.date(2024, 1, 2),
        "at": datetime.time(3, 4, 5),
        "pair": (1, 2),
    }
    parsed = load_json(dump_json(value))
    assert parsed["price"] == 1.5
    assert parsed["when"] == "2024-01-02T03:04:05"
    assert parsed["day"] == "2024-01-02"
    assert parsed["at"] == "03:04:05"
    assert parsed["pair"] == [1, 2]


def test_dump_json_normalizes_sets() -> None:
    """A set becomes a list (order-independent)."""
    assert set(load_json(dump_json({1, 2, 3}))) == {1, 2, 3}


def test_dump_json_custom_default() -> None:
    """A custom default handles a type the dumper does not know."""

    class Point:
        def __init__(self) -> None:
            self.x = 1

    def default(value: Any) -> Any:
        if isinstance(value, Point):
            return {"x": value.x}
        raise TypeError

    assert load_json(dump_json(Point(), default=default)) == {"x": 1}


def test_dump_json_unserializable_without_default() -> None:
    """An unknown type with no default raises a clear TypeError."""
    with pytest.raises(TypeError, match="cannot serialize"):
        dump_json(object())


def test_dump_json_uses_orjson_when_present() -> None:
    """With orjson installed, its bytes output is decoded to a str and round-trips."""
    result = dump_json({"a": 1, "b": [2, 3]})
    assert isinstance(result, str)
    assert load_json(result) == {"a": 1, "b": [2, 3]}


def test_dump_json_falls_back_to_stdlib(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without orjson, the standard library json module serializes."""
    monkeypatch.setattr(_optional, "orjson", None)
    assert load_json(dump_json({"a": 1})) == {"a": 1}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_dump_json_rejects_non_finite_floats(value: float) -> None:
    """JSON has no nan/inf, so a non-finite float is refused, not corrupted."""
    with pytest.raises(ValueError, match="non-finite"):
        dump_json({"x": value})


def test_dump_json_handles_big_ints_and_non_str_keys() -> None:
    """A >64-bit int and a non-string key serialize the same with or without orjson."""
    assert load_json(dump_json({"n": 2**70})) == {"n": 2**70}
    assert load_json(dump_json({1: "a"})) == {"1": "a"}


def test_dump_json_falls_back_and_still_handles_big_ints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stdlib fallback path also serializes a >64-bit int and a non-string key."""
    monkeypatch.setattr(_optional, "orjson", None)
    assert load_json(dump_json({"n": 2**70})) == {"n": 2**70}
    assert load_json(dump_json({1: "a"})) == {"1": "a"}


@pytest.mark.parametrize("dumper", [dump_json, dump_yaml])
def test_dump_rejects_an_unpaired_surrogate(dumper: object) -> None:
    """A lone surrogate has no UTF-8 form, so it is refused, not emitted as invalid text.

    Previously dump_json emitted ``'"\\ud800"'``, which cannot be UTF-8 encoded or
    reloaded; a clean ValueError is raised instead.
    """
    with pytest.raises(ValueError, match="surrogate"):
        dumper("\ud800")  # type: ignore[operator]


def test_dump_toml_rejects_an_unpaired_surrogate() -> None:
    """The surrogate check applies to TOML too, before the backend sees the value."""
    with pytest.raises(ValueError, match="surrogate"):
        dump_toml({"key": "\ud800"})


def test_dump_json_output_matches_across_backends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The JSON text is the same whether orjson is present or not."""
    value = {"name": "app", "ports": [80, 443]}
    with_orjson = dump_json(value)

    monkeypatch.setattr(_optional, "orjson", None)
    assert dump_json(value) == with_orjson


def test_dump_json_keeps_non_ascii_raw_on_both_paths() -> None:
    """Non-ASCII text is emitted raw whether the orjson or stdlib path runs."""
    # The int key forces the stdlib fallback; a str-keyed copy stays on orjson.
    orjson_text = dump_json({"name": "café €"})
    fallback_text = dump_json({1: "café €"})
    assert "café €" in orjson_text
    assert "café €" in fallback_text
    assert "\\u" not in fallback_text


def test_dump_yaml_round_trips_with_load_yaml() -> None:
    """A plain value dumps to YAML that load_yaml parses back unchanged."""
    value = {"name": "app", "ports": [80, 443]}
    assert load_yaml(dump_yaml(value)) == value


def test_dump_yaml_normalizes_special_types() -> None:
    """The same normalization applies to YAML output."""
    parsed = load_yaml(dump_yaml({"price": Decimal("2.5"), "tags": {"a"}}))
    assert parsed["price"] == 2.5
    assert parsed["tags"] == ["a"]


def test_dump_yaml_allows_non_finite_floats() -> None:
    """Unlike JSON, YAML has .nan and .inf, so a non-finite float is kept."""
    assert ".nan" in dump_yaml({"x": float("nan")})
    assert ".inf" in dump_yaml({"x": float("inf")})


def test_dump_yaml_uses_yamlrocks_when_present() -> None:
    """With YAMLRocks installed, its bytes output is decoded and round-trips."""
    result = dump_yaml({"a": 1})
    assert isinstance(result, str)
    assert load_yaml(result) == {"a": 1}


def test_dump_yaml_falls_back_to_pyyaml(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without YAMLRocks, PyYAML's safe dumper serializes."""
    monkeypatch.setattr(_optional, "yamlrocks", None)
    assert load_yaml(dump_yaml({"a": 1})) == {"a": 1}


def test_dump_yaml_without_a_dumper(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no YAML dumper installed, a clear error is raised."""
    monkeypatch.setattr(_optional, "yamlrocks", None)
    monkeypatch.setattr(_optional, "pyyaml", None)
    with pytest.raises(RuntimeError, match="no YAML dumper"):
        dump_yaml({"a": 1})


def test_dump_toml_round_trips_with_load_toml() -> None:
    """dump_toml (real tomli-w) normalizes and round-trips through load_toml."""
    parsed = load_toml(dump_toml({"port": Decimal(80), "name": "app"}))
    assert parsed == {"port": 80, "name": "app"}


def test_dump_toml_preserves_native_temporal_types() -> None:
    """TOML has native datetime/date/time, so they round-trip as the same type."""
    value = {
        "when": datetime.datetime(2024, 1, 2, 3, 4, 5),
        "day": datetime.date(2024, 1, 2),
        "at": datetime.time(3, 4, 5),
    }
    parsed = load_toml(dump_toml(value))
    assert parsed == value
    assert isinstance(parsed["when"], datetime.datetime)
    assert isinstance(parsed["day"], datetime.date)
    assert isinstance(parsed["at"], datetime.time)


@pytest.mark.parametrize("value", [None, 5, [1, 2]])
def test_dump_toml_rejects_non_mapping_top_level(value: Any) -> None:
    """A TOML document is a table, so a bare scalar or list is refused clearly."""
    with pytest.raises(TypeError, match="top level"):
        dump_toml(value)


def test_dump_toml_without_a_dumper(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no TOML dumper installed, a clear error is raised."""
    monkeypatch.setattr(_optional, "tomli_w", None)
    with pytest.raises(RuntimeError, match="no TOML dumper"):
        dump_toml({"a": 1})


def test_dump_dispatches_on_format() -> None:
    """The unified dump() dispatches on the format name."""
    assert load_json(dump({"a": 1}, "json")) == {"a": 1}
    assert load_yaml(dump({"a": 1}, "yaml")) == {"a": 1}


def test_dump_passes_default_through() -> None:
    """The unified dump() forwards the default hook to the chosen dumper."""

    class Tag:
        pass

    result = dump({"t": Tag()}, "json", default=lambda _v: "tagged")
    assert load_json(result) == {"t": "tagged"}


def test_dump_rejects_unknown_format() -> None:
    """An unsupported format name is rejected with a clear error."""
    with pytest.raises(ValueError, match="unsupported format"):
        dump({"a": 1}, "xml")


def test_dump_options_are_forwarded_to_the_backend() -> None:
    """Backend options reach the active serializer (orjson indent, YAML sort)."""
    import orjson  # noqa: PLC0415
    import yamlrocks  # noqa: PLC0415

    indented = dump_json({"a": 1}, options={"option": orjson.OPT_INDENT_2})
    assert "\n" in indented  # pretty-printed, not the compact default

    sorted_yaml = dump_yaml(
        {"b": 1, "a": 2}, options={"option": yamlrocks.OPT_SORT_KEYS}
    )
    assert sorted_yaml.strip() == "a: 2\nb: 1"


def test_dump_json_options_on_stdlib_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without orjson, JSON dump options reach the standard library serializer."""
    monkeypatch.setattr(_optional, "orjson", None)
    indented = dump_json({"a": 1}, options={"indent": 2})
    assert "\n" in indented


def test_dump_dispatches_options() -> None:
    """The unified dump() forwards options to the chosen dumper."""
    import yamlrocks  # noqa: PLC0415

    result = dump({"b": 1, "a": 2}, "yaml", options={"option": yamlrocks.OPT_SORT_KEYS})
    assert result.strip() == "a: 2\nb: 1"


def test_dump_refuses_a_circular_reference() -> None:
    """A self-referential structure fails cleanly, not with a RecursionError."""
    data: dict[str, Any] = {}
    data["self"] = data

    for fmt in ("json", "yaml", "toml"):
        with pytest.raises(ValueError, match="circular reference"):
            dump(data, fmt)


def test_dump_json_refuses_a_circular_list() -> None:
    """A list that contains itself is refused as a circular reference."""
    items: list[Any] = []
    items.append(items)

    with pytest.raises(ValueError, match="circular reference"):
        dump_json(items)


def test_dump_allows_a_shared_substructure() -> None:
    """The same object reached twice (a DAG, not a cycle) dumps fine."""
    shared = {"x": 1}
    assert dump_json({"a": shared, "b": shared}) == '{"a":{"x":1},"b":{"x":1}}'


def test_dump_json_refuses_keys_that_collide_after_coercion() -> None:
    """An int key and a str key that coerce to the same JSON key are refused."""
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        dump_json({1: "a", "1": "b"})


def test_dump_json_keeps_distinct_coerced_keys() -> None:
    """Keys that coerce to different strings (1 and 1.5) are both kept."""
    assert load_json(dump_json({1: "a", 1.5: "b"})) == {"1": "a", "1.5": "b"}


def test_dump_json_coerces_bool_and_none_keys() -> None:
    """Bool and None keys coerce to their JSON spellings without colliding."""
    assert load_json(dump_json({True: "a", None: "b"})) == {"true": "a", "null": "b"}


def test_dump_json_leaves_a_non_coercible_key_to_the_backend() -> None:
    """A key JSON cannot represent (a tuple) is left for the backend to reject."""
    with pytest.raises(TypeError):
        dump_json({(1, 2): "x"})


def test_dump_yaml_option_rejected_by_backend_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A YAMLRocks-style dump option on the PyYAML fallback is a clear error."""
    monkeypatch.setattr(_optional, "yamlrocks", None)
    with pytest.raises(ValueError, match="does not accept the option"):
        dump_yaml({"a": 1}, options={"option": 1})
