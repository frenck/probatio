"""Tests for the JSON and YAML loaders."""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from probatio import (
    MultipleInvalid,
    Required,
    Schema,
    load,
    load_json,
    load_toml,
    load_yaml,
    load_yaml_with_locations,
)
from probatio.serde import _optional

if TYPE_CHECKING:
    from pathlib import Path


def test_load_json_from_string() -> None:
    """JSON is parsed from a string."""
    assert load_json('{"a": 1}') == {"a": 1}


def test_load_json_from_bytes() -> None:
    """JSON is parsed from bytes."""
    assert load_json(b'{"a": 1}') == {"a": 1}


def test_load_json_from_path(tmp_path: Path) -> None:
    """JSON is parsed from a file path."""
    file = tmp_path / "data.json"
    file.write_text('{"a": 1}')
    assert load_json(file) == {"a": 1}


def test_load_json_from_file_like() -> None:
    """JSON is parsed from a file-like object."""
    assert load_json(io.StringIO('{"a": 1}')) == {"a": 1}


def test_optional_load_returns_none_for_missing_module() -> None:
    """The optional-backend loader returns None when a module is not installed."""
    assert _optional._load("probatio_no_such_backend") is None


def test_optional_load_reraises_a_broken_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An installed-but-broken backend re-raises instead of being masked as absent.

    A ModuleNotFoundError naming a different module (a dependency the backend imports)
    is a real install problem, not the backend being absent, so it must propagate.
    """

    def boom(_name: str) -> object:
        message = "No module named 'innards'"
        raise ModuleNotFoundError(message, name="innards")

    monkeypatch.setattr(_optional, "import_module", boom)

    with pytest.raises(ModuleNotFoundError, match="innards"):
        _optional._load("orjson")


def test_load_json_uses_orjson_when_present() -> None:
    """With orjson installed (the test env has it), JSON parses through it."""
    assert load_json('{"a": 1, "b": [2, 3]}') == {"a": 1, "b": [2, 3]}


def test_load_json_falls_back_to_stdlib(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without orjson, the standard library json module parses."""
    monkeypatch.setattr(_optional, "orjson", None)
    assert load_json('{"a": 1}') == {"a": 1}


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("with_orjson", [True, False])
def test_load_json_rejects_non_standard_constants(
    token: str,
    *,
    with_orjson: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NaN/Infinity are rejected the same way with or without orjson.

    The standard library accepts these JavaScript constants by default while orjson
    rejects them, which would otherwise make hostile non-standard JSON backend-
    dependent. Both paths now refuse them.
    """
    if not with_orjson:
        monkeypatch.setattr(_optional, "orjson", None)
    with pytest.raises(ValueError):  # noqa: PT011 - both backends raise ValueError subtypes
        load_json(token)


def test_load_json_caller_can_opt_into_non_standard_constants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-supplied parse_constant overrides the default rejection."""
    monkeypatch.setattr(_optional, "orjson", None)
    result = load_json("NaN", options={"parse_constant": lambda token: token})
    assert result == "NaN"


def test_load_yaml_with_yamlrocks() -> None:
    """With YAMLRocks installed, it parses YAML."""
    assert load_yaml("a: 1\nb: two\n") == {"a": 1, "b": "two"}


def test_load_yaml_falls_back_to_pyyaml(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without YAMLRocks, PyYAML's safe loader parses."""
    monkeypatch.setattr(_optional, "yamlrocks", None)
    assert load_yaml("a: 1\nb: two\n") == {"a": 1, "b": "two"}


def test_load_yaml_without_a_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no YAML parser installed, a clear error is raised."""
    monkeypatch.setattr(_optional, "yamlrocks", None)
    monkeypatch.setattr(_optional, "pyyaml", None)
    with pytest.raises(RuntimeError, match="no YAML parser"):
        load_yaml("a: 1")


def test_unsupported_source_type() -> None:
    """A source that is neither content, path, nor file-like is rejected."""
    with pytest.raises(TypeError):
        load_json(12345)


def test_schema_load_json_parses_and_validates() -> None:
    """Schema.load_json parses then validates in one step."""
    schema = Schema({Required("port"): int})
    assert schema.load_json('{"port": 80}') == {"port": 80}


def test_schema_load_json_reports_validation_errors() -> None:
    """A parsed-but-invalid payload still fails validation."""
    schema = Schema({Required("port"): int})
    with pytest.raises(MultipleInvalid):
        schema.load_json('{"port": "nope"}')


def test_schema_load_yaml_parses_and_validates() -> None:
    """Schema.load_yaml parses then validates in one step."""
    schema = Schema({Required("name"): str})
    assert schema.load_yaml("name: app") == {"name": "app"}


def test_load_toml_from_string() -> None:
    """TOML is parsed from a string via the standard library."""
    assert load_toml('port = 80\nname = "app"\n') == {"port": 80, "name": "app"}


def test_load_toml_from_bytes() -> None:
    """TOML is parsed from bytes (decoded first, since tomllib wants text)."""
    assert load_toml(b"port = 80\n") == {"port": 80}


def test_schema_load_toml_parses_and_validates() -> None:
    """Schema.load_toml parses then validates in one step."""
    schema = Schema({Required("port"): int})
    assert schema.load_toml("port = 80") == {"port": 80}


def test_load_dispatches_on_format() -> None:
    """The unified load() dispatches on an explicit format."""
    assert load('{"a": 1}', "json") == {"a": 1}
    assert load("a: 1", "yaml") == {"a": 1}
    assert load("a = 1", "toml") == {"a": 1}


def test_load_auto_detects_from_path_extension(tmp_path: Path) -> None:
    """load() infers the format from a path extension when none is given."""
    file = tmp_path / "config.toml"
    file.write_text('name = "app"\n')
    assert load(file) == {"name": "app"}


def test_load_rejects_unknown_format() -> None:
    """An unsupported format name is rejected with a clear error."""
    with pytest.raises(ValueError, match="unsupported format"):
        load("{}", "xml")


def test_load_cannot_detect_format_from_bare_string() -> None:
    """Without a path or explicit format, detection fails clearly."""
    with pytest.raises(ValueError, match="cannot detect format"):
        load('{"a": 1}')


def test_load_cannot_detect_unknown_extension(tmp_path: Path) -> None:
    """A path with an unknown extension cannot be auto-detected."""
    file = tmp_path / "config.ini"
    file.write_text("x")
    with pytest.raises(ValueError, match="cannot detect format"):
        load(file)


def test_schema_load_auto_detects(tmp_path: Path) -> None:
    """Schema.load parses (auto-detected) then validates."""
    file = tmp_path / "config.json"
    file.write_text('{"port": 80}')
    schema = Schema({Required("port"): int})
    assert schema.load(file) == {"port": 80}


def test_load_options_are_forwarded_to_the_backend() -> None:
    """Backend options reach the active parser (a YAML spec switch, TOML parse_float)."""
    import yamlrocks  # noqa: PLC0415

    # YAML 1.2 (default) keeps `yes` a string; 1.1 reads it as a boolean.
    assert load_yaml("v: yes")["v"] == "yes"
    one_one = load_yaml("v: yes", options={"option": yamlrocks.OPT_YAML_1_1})
    assert one_one["v"] is True

    from decimal import Decimal  # noqa: PLC0415

    parsed = load_toml("x = 1.5", options={"parse_float": Decimal})
    assert isinstance(parsed["x"], Decimal)


def test_load_dispatches_options() -> None:
    """The unified load() forwards options to the chosen loader."""
    import yamlrocks  # noqa: PLC0415

    result = load("v: yes", "yaml", options={"option": yamlrocks.OPT_YAML_1_1})
    assert result["v"] is True


def test_load_json_options_on_stdlib_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without orjson, JSON load options reach the standard library parser."""
    monkeypatch.setattr(_optional, "orjson", None)
    from decimal import Decimal  # noqa: PLC0415

    result = load_json('{"x": 1.5}', options={"parse_float": Decimal})
    assert isinstance(result["x"], Decimal)


def test_load_yaml_with_locations_resolves_paths() -> None:
    """The locator maps an error path to the exact position of its value."""
    from probatio import Location  # noqa: PLC0415

    text = "name: web\nlimits:\n  max: 999\n"
    data, locator = load_yaml_with_locations(text)

    assert data == {"name": "web", "limits": {"max": 999}}
    loc = locator(["limits", "max"])
    assert isinstance(loc, Location)
    assert (loc.line, loc.column) == (3, 8)  # the value 999, not the block
    assert str(locator([])) == "1:1"  # the document root, no file


def test_load_yaml_with_locations_resolves_merge_keys_like_load_yaml() -> None:
    """A ``<<`` merge resolves to the same data the plain loader returns."""
    text = (
        "base: &b\n  a: 1\n  b: 2\n"
        "over: &o\n  a: 99\n"
        "derived:\n  <<: [*o, *b]\n  c: 3\n  a: 7\n"
    )
    plain = load_yaml(text)
    located, _locator = load_yaml_with_locations(text)

    assert located == plain
    # Explicit key wins over both sources, and the earlier source wins for shared keys.
    assert located["derived"] == {"c": 3, "a": 7, "b": 2}


def test_load_yaml_with_locations_returns_none_for_an_unknown_path() -> None:
    """A path that is not in the document has no position, so the locator is None."""
    _data, locator = load_yaml_with_locations("a: 1\n")
    assert locator(["a", "missing"]) is None


def test_load_yaml_with_locations_returns_none_for_a_non_key_segment() -> None:
    """A path segment that is not a valid mapping key cannot be located."""
    _data, locator = load_yaml_with_locations("a: 1\n")
    assert locator([object()]) is None


def test_load_yaml_with_locations_fills_file_from_a_path(tmp_path: object) -> None:
    """A Path source sets the document origin, so the location carries the file."""
    from pathlib import Path  # noqa: PLC0415

    config = Path(tmp_path) / "cfg.yaml"  # type: ignore[arg-type]
    config.write_text("nested:\n  level: 1\n")
    _data, locator = load_yaml_with_locations(config)
    loc = locator(["nested", "level"])

    assert loc.file == str(config)
    assert str(loc) == f"{config}:2:10"


def test_load_yaml_with_locations_needs_yamlrocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the YAMLRocks backend, source locations are unavailable."""
    monkeypatch.setattr(_optional, "yamlrocks", None)
    with pytest.raises(RuntimeError, match="YAMLRocks"):
        load_yaml_with_locations("a: 1")


def test_load_yaml_with_locations_returns_none_for_an_empty_document() -> None:
    """An empty document has no positioned node, so the locator yields None."""
    _data, locator = load_yaml_with_locations("")
    assert locator([]) is None


def test_load_yaml_with_locations_needs_locate_capable_yamlrocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A YAMLRocks too old to provide ``locate`` is refused with a clear error."""

    class _OldDocument:
        """A pre-0.5.0 document, without the ``locate`` method."""

    monkeypatch.setattr(
        _optional.yamlrocks,
        "loads",
        lambda *_args, **_kwargs: _OldDocument(),
    )

    with pytest.raises(RuntimeError, match="or newer"):
        load_yaml_with_locations("a: 1")


def test_resolve_merge_keys_skips_a_non_mapping_source() -> None:
    """A non-mapping inside a ``<<`` list is ignored; mapping sources still merge."""
    from probatio.serde.loaders import _resolve_merge_keys  # noqa: PLC0415

    resolved = _resolve_merge_keys({"<<": [5, {"a": 1}], "c": 3})
    assert resolved == {"c": 3, "a": 1}


def test_load_json_options_honored_even_with_orjson() -> None:
    """JSON load options route through the standard library; orjson takes none."""
    from decimal import Decimal  # noqa: PLC0415

    # orjson is present in the test env; the option must still be honored.
    assert _optional.orjson is not None
    result = load_json('{"x": 1.5}', options={"parse_float": Decimal})
    assert isinstance(result["x"], Decimal)


def test_load_yaml_option_rejected_by_backend_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A YAMLRocks-style option on the PyYAML fallback is a clear error, not a leak."""
    monkeypatch.setattr(_optional, "yamlrocks", None)
    with pytest.raises(ValueError, match="does not accept the option"):
        load_yaml("v: 1", options={"option": 1})


def test_load_yaml_backend_typeerror_is_not_mislabeled_as_a_bad_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A backend TypeError merely mentioning 'argument' propagates, not a bad-option error."""

    def boom(_data: object, **_options: object) -> object:
        # A data-related TypeError that happens to contain the word "argument": it
        # accepts the option keywords, so this is not an unaccepted-option error.
        message = "the document argument is malformed"
        raise TypeError(message)

    monkeypatch.setattr(_optional, "yamlrocks", None)
    monkeypatch.setattr(_optional, "pyyaml", SimpleNamespace(safe_load=boom))
    with pytest.raises(TypeError, match="document argument is malformed"):
        load_yaml("v: 1", options={"flow": True})
