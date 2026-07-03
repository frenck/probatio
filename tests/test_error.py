"""Tests for the probatio error hierarchy."""

from __future__ import annotations

import pytest

import probatio
from probatio import _messages
from probatio.error import (
    Error,
    Invalid,
    MultipleInvalid,
    RangeInvalid,
    TypeInvalid,
)


def test_invalid_defaults() -> None:
    """A bare Invalid has an empty path and echoes its message."""
    err = Invalid("not a number")
    assert err.msg == "not a number"
    assert err.path == []
    assert err.error_message == "not a number"
    assert err.error_type is None
    assert str(err) == "not a number"


def test_invalid_renders_path() -> None:
    """The path is appended as a dotted trail, the message stays bare."""
    err = Invalid("expected int", path=["config", "port"])
    assert err.path == ["config", "port"]
    assert err.error_message == "expected int"
    assert str(err) == "expected int at 'config.port'"


def test_invalid_renders_deep_path_with_indices() -> None:
    """Sequence indices render as [n] inside the dotted trail."""
    err = Invalid(
        "expected str",
        path=["automation", 0, "triggers", 2, "entity_id"],
    )
    assert str(err) == "expected str at 'automation[0].triggers[2].entity_id'"


def test_invalid_renders_index_first_path_segment() -> None:
    """A path starting at a sequence index renders without a leading dot."""
    err = Invalid("expected str", path=[1, "name"])
    assert str(err) == "expected str at '[1].name'"


def test_invalid_renders_hyphenated_key_bare() -> None:
    """A hyphenated key (common in configuration) renders without brackets."""
    err = Invalid("expected int", path=["scan-interval"])
    assert str(err) == "expected int at 'scan-interval'"


def test_invalid_renders_awkward_key_bracketed() -> None:
    """A key that does not read cleanly bare falls back to a bracketed repr."""
    err = Invalid("expected int", path=["server", "my key"])
    assert str(err) == "expected int at 'server['my key']'"


def test_invalid_renders_angle_bracket_key_with_control_chars_bracketed() -> None:
    """An attacker-shaped <...> key falls back to repr; no raw control characters."""
    err = Invalid("bad", path=["<bad\nkey>"])
    assert str(err) == "bad at '['<bad\\nkey>']'"
    assert "\n" not in str(err)


def test_invalid_renders_group_segment_bare() -> None:
    """An identifier-like <group> segment renders bare, keeping its brackets."""
    err = Invalid("bad", path=["server", "<auth>"])
    assert str(err) == "bad at 'server.<auth>'"


def test_invalid_renders_bool_key_bracketed() -> None:
    """A boolean key renders as its repr, not as a sequence index."""
    err = Invalid("expected int", path=[True])
    assert str(err) == "expected int at '[True]'"


def test_invalid_does_not_render_error_type() -> None:
    """The error type attribute is kept, but no longer rendered (ADR-015)."""
    err = Invalid("nope", error_type="dictionary value")
    assert err.error_type == "dictionary value"
    assert str(err) == "nope"


def test_invalid_error_message_is_independent_of_message() -> None:
    """error_message can differ from the human message (and stays bare)."""
    err = Invalid("display", error_message="required key not provided", path=["x"])
    assert err.error_message == "required key not provided"


def test_prepend_adds_segments_to_the_front() -> None:
    """prepend grows the path from the front as an error bubbles up."""
    err = Invalid("bad", path=["port"])
    err.prepend(["targets", "localhost"])
    assert err.path == ["targets", "localhost", "port"]


def test_subclasses_are_invalid() -> None:
    """Semantic subclasses are catchable as Invalid (and as Error)."""
    err = TypeInvalid("expected int")
    assert isinstance(err, Invalid)
    assert isinstance(err, Error)


def test_multiple_invalid_collects_errors() -> None:
    """MultipleInvalid holds a list and delegates to the first error."""
    first = Invalid("first", path=["a"], error_type="value")
    second = Invalid("second", path=["b"])
    multi = MultipleInvalid([first, second])

    assert multi.errors == [first, second]
    assert multi.msg == "first"
    assert multi.path == ["a"]
    assert multi.error_message == "first"
    assert multi.error_type == "value"
    assert str(multi) == str(first)

    multi.error_type = "dictionary value"

    assert first.error_type == "dictionary value"


def test_multiple_invalid_add_and_prepend() -> None:
    """add appends, prepend propagates to every wrapped error."""
    multi = MultipleInvalid([Invalid("one", path=["a"])])

    multi.add(Invalid("two", path=["b"]))
    multi.prepend(["root"])

    assert [e.path for e in multi.errors] == [["root", "a"], ["root", "b"]]


def test_empty_multiple_invalid_is_not_a_half_valid_state() -> None:
    """An empty MultipleInvalid (built incrementally) reads safely, never IndexError."""
    multi = MultipleInvalid()
    assert multi.errors == []
    assert multi.msg == ""
    assert multi.path == []
    assert multi.error_message == ""
    assert multi.error_type is None
    assert multi.code is None
    assert multi.context == {}
    assert multi.translation_key is None
    assert multi.placeholders == {}
    assert str(multi) == "no validation errors"
    multi.error_type = "ignored while empty"  # no-op, must not raise
    assert multi.error_type is None

    # And once populated incrementally it behaves normally.
    multi.add(Invalid("boom", path=["x"]))
    assert multi.msg == "boom"
    assert multi.path == ["x"]


def test_multiple_invalid_repr_lists_errors() -> None:
    """The repr surfaces the wrapped errors for debugging."""
    multi = MultipleInvalid([Invalid("boom")])
    assert "MultipleInvalid(" in repr(multi)


def test_subclasses_carry_a_default_code() -> None:
    """Each semantic subclass has a stable machine-readable code."""
    assert TypeInvalid("x").code == "type"
    assert RangeInvalid("x").code == "range"
    assert Invalid("x").code is None


def test_explicit_code_overrides_the_default() -> None:
    """An explicit code wins over the class default."""
    assert TypeInvalid("x", code="custom").code == "custom"


def test_structured_fields_default_empty() -> None:
    """Context and placeholders default to empty, translation_key to None."""
    err = Invalid("x")
    assert err.context == {}
    assert err.placeholders == {}
    assert err.translation_key is None


def test_structured_fields_can_be_set() -> None:
    """The structured layer can be populated at construction."""
    err = Invalid(
        "bad",
        code="too_small",
        context={"min": 0},
        translation_key="value_too_small",
        placeholders={"min": "0"},
    )
    assert err.code == "too_small"
    assert err.context == {"min": 0}
    assert err.translation_key == "value_too_small"
    assert err.placeholders == {"min": "0"}


def test_as_dict_shape() -> None:
    """as_dict renders the structured layer for machine handling."""
    err = TypeInvalid("expected int", path=["port"], context={"expected": "int"})
    rendered = err.as_dict()
    assert rendered == {
        "code": "type",
        "message": "expected int",
        "path": ["port"],
        "secret": False,
        "context": {"expected": "int"},
        "translation_key": None,
        "placeholders": {},
    }


def test_multiple_invalid_as_dict_wraps_children() -> None:
    """MultipleInvalid.as_dict lists each child error's structured form."""
    multi = MultipleInvalid([TypeInvalid("expected int", path=["a"])])
    rendered = multi.as_dict()
    assert rendered["errors"][0]["code"] == "type"


def test_multiple_invalid_delegates_the_secret_flag() -> None:
    """MultipleInvalid reads and writes the first error's redaction flag."""
    first = TypeInvalid("boom", path=["pw"])
    multi = MultipleInvalid([first])
    assert multi.secret is False
    multi.secret = True
    assert first.secret is True
    assert multi.secret is True
    # An empty collection reports no secret and swallows a write.
    empty = MultipleInvalid([])
    assert empty.secret is False
    empty.secret = True
    assert empty.secret is False


def test_multiple_invalid_delegates_structured_fields() -> None:
    """MultipleInvalid surfaces the first error's structured fields."""
    first = TypeInvalid(
        "boom",
        code="type",
        context={"expected": "int"},
        translation_key="key",
        placeholders={"x": "1"},
    )
    multi = MultipleInvalid([first])
    assert multi.code == "type"
    assert multi.context == {"expected": "int"}
    assert multi.translation_key == "key"
    assert multi.placeholders == {"x": "1"}


def test_engine_attaches_codes_and_context() -> None:
    """The engine produces coded errors: extra keys and type mismatches."""
    schema = probatio.Schema({"port": int})

    with pytest.raises(probatio.MultipleInvalid) as caught:
        schema({"port": "x", "extra": 1})

    by_code = {error.code: error for error in caught.value.errors}
    assert "type" in by_code
    assert by_code["type"].context == {"expected": "int"}
    assert "extra_keys_not_allowed" in by_code


def test_errors_are_exported_at_top_level() -> None:
    """The public error names are reachable from the package root."""
    assert probatio.Invalid is Invalid
    assert issubclass(probatio.MultipleInvalid, probatio.Invalid)


def test_long_path_segment_is_truncated_in_str() -> None:
    """A huge path segment cannot blow up the rendered error string."""
    huge = "k" * 5000
    err = Invalid("bad", path=[huge])
    rendered = str(err)
    assert rendered.endswith("...]'")
    assert len(rendered) < 600


def test_normal_path_segment_is_not_truncated() -> None:
    """An ordinary key renders in full, with no truncation."""
    err = Invalid("bad", path=["port"])
    assert str(err) == "bad at 'port'"


def test_deferred_message_renders_from_the_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no message and a translation_key, the text renders from the catalog."""
    monkeypatch.setitem(_messages.CATALOG, "test_min", "value must be at least {min}")
    err = Invalid(translation_key="test_min", placeholders={"min": 10}, path=["n"])
    assert err.msg == "value must be at least 10"
    assert err.error_message == "value must be at least 10"
    assert str(err) == "value must be at least 10 at 'n'"
    assert err.translation_key == "test_min"
    assert err.placeholders == {"min": 10}


def test_deferred_message_is_rendered_once_and_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first read renders and caches; later catalog changes do not show."""
    monkeypatch.setitem(_messages.CATALOG, "test_key", "first")
    err = Invalid(translation_key="test_key")
    assert err.msg == "first"
    monkeypatch.setitem(_messages.CATALOG, "test_key", "second")
    assert err.msg == "first"
    assert err.args == ("first",)


def test_deferred_message_without_placeholders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A template with no placeholders renders as-is."""
    monkeypatch.setitem(_messages.CATALOG, "test_plain", "value is not allowed")
    err = Invalid(translation_key="test_plain")
    assert err.error_message == "value is not allowed"


def test_explicit_message_wins_over_the_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A custom message keeps its text; the key still rides along."""
    monkeypatch.setitem(_messages.CATALOG, "test_min", "value must be at least {min}")
    err = Invalid(
        "own words",
        translation_key="test_min",
        placeholders={"min": 10},
    )
    assert err.msg == "own words"
    assert err.error_message == "own words"
    assert err.translation_key == "test_min"


def test_invalid_without_message_or_key_is_empty() -> None:
    """Neither a message nor a key renders as an empty message."""
    err = Invalid()
    assert err.msg == ""
    assert str(err) == ""
