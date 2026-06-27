"""Tests for process-wide and scoped default serde options."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yamlrocks

from probatio import (
    clear_default_options,
    default_options,
    dump_json,
    load_yaml,
    set_default_options,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _reset_defaults() -> Iterator[None]:
    """Clear any process-wide defaults a test set, so none leak to the next."""
    yield
    clear_default_options()


def test_global_default_applies_to_later_loads() -> None:
    """A process-wide default reaches every later load for that format."""
    assert load_yaml("flag: yes")["flag"] == "yes"  # 1.2 baseline
    set_default_options("yaml", load={"option": yamlrocks.OPT_YAML_1_1})
    assert load_yaml("flag: yes")["flag"] is True  # 1.1 from the default


def test_global_default_applies_to_dumps() -> None:
    """A process-wide dump default reaches every later dump for that format."""
    import orjson  # noqa: PLC0415

    assert "\n" not in dump_json({"a": 1})  # compact by default
    set_default_options("json", dump={"option": orjson.OPT_INDENT_2})
    assert "\n" in dump_json({"a": 1})  # pretty from the default


def test_per_call_options_win_over_the_global_default() -> None:
    """A call's own options override the process-wide default per key."""
    set_default_options("yaml", load={"option": yamlrocks.OPT_YAML_1_1})
    assert load_yaml("flag: yes", options={"option": 0})["flag"] == "yes"


def test_clear_default_options_removes_the_default() -> None:
    """clear_default_options drops the process-wide default."""
    set_default_options("yaml", load={"option": yamlrocks.OPT_YAML_1_1})
    clear_default_options()
    assert load_yaml("flag: yes")["flag"] == "yes"


def test_scoped_default_options_are_restored_on_exit() -> None:
    """default_options applies inside the block and restores on exit."""
    with default_options("yaml", load={"option": yamlrocks.OPT_YAML_1_1}):
        assert load_yaml("flag: yes")["flag"] is True
    assert load_yaml("flag: yes")["flag"] == "yes"


def test_scoped_default_options_compose_when_nested() -> None:
    """Nested scopes merge, and the inner value wins for the same key."""
    with (
        default_options(
            "yaml",
            load={"option": yamlrocks.OPT_YAML_1_1},
        ),
        default_options("json", dump={"option": 0}),
    ):
        # the yaml scope from the outer block is still in effect
        assert load_yaml("flag: yes")["flag"] is True


def test_per_call_wins_over_scoped_default() -> None:
    """A per-call option overrides a scoped default."""
    with default_options("yaml", load={"option": yamlrocks.OPT_YAML_1_1}):
        assert load_yaml("flag: yes", options={"option": 0})["flag"] == "yes"


def test_set_default_options_rejects_unknown_format() -> None:
    """Setting a process-wide default for an unknown format raises a clear error."""
    with pytest.raises(ValueError, match="unknown format"):
        set_default_options("xml", load={})


def test_default_options_rejects_unknown_format() -> None:
    """A scoped default for an unknown format raises when the block is entered."""
    with (
        pytest.raises(ValueError, match="unknown format"),
        default_options(
            "xml",
            load={},
        ),
    ):
        pass  # pragma: no cover - the error fires on entering the block
