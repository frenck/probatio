"""Tests for the string-transform and format validators (and Match)."""

from __future__ import annotations

import pytest

from probatio import (
    ASCII,
    All,
    Alpha,
    Alphanumeric,
    ByteLength,
    Capitalize,
    Email,
    EndsWith,
    FqdnUrl,
    HexColor,
    IsRegex,
    Lower,
    Match,
    MultipleInvalid,
    NoWhitespace,
    PrintableASCII,
    Replace,
    Schema,
    Slug,
    StartsWith,
    Strip,
    Title,
    Upper,
    Url,
)
from probatio.error import (
    EmailInvalid,
    MatchInvalid,
    SchemaError,
    SlugInvalid,
    UrlInvalid,
)


def test_replace() -> None:
    """Replace substitutes every match of the pattern."""
    assert Schema(Replace(r"\s+", "-"))("a b  c") == "a-b-c"


@pytest.mark.parametrize("value", [123, None, ["a"]])
def test_replace_on_non_string(value: object) -> None:
    """Replace fails cleanly on any non-string, not with a raw TypeError.

    Covers the int/None/list cases of voluptuous PR #540: where voluptuous 0.16.0
    leaks the underlying ``TypeError`` from ``re.sub``, probatio reports a
    ``MatchInvalid``.
    """
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Replace(r"x", "y"))(value)
    assert isinstance(caught.value.errors[0], MatchInvalid)


def test_replace_rejects_a_bad_backreference_at_build() -> None:
    """A substitution with an invalid group reference is a build-time SchemaError.

    ``re`` parses the replacement template eagerly, so ``\\2`` against a one-group
    pattern is caught when the validator is constructed, not leaked as a raw
    ``re.error`` on the first matching value.
    """
    with pytest.raises(SchemaError, match="substitution"):
        Replace(r"(a)", r"\2")


def test_string_transforms() -> None:
    """The transforms coerce to string and apply the expected change."""
    assert Schema(Lower)("ABC") == "abc"
    assert Schema(Upper)("abc") == "ABC"
    assert Schema(Capitalize)("hello world") == "Hello world"
    assert Schema(Title)("hello world") == "Hello World"
    assert Schema(Strip)("  hi  ") == "hi"


def test_transforms_are_identity_comparable() -> None:
    """The transforms are stable callables matchable by name (serializer needs)."""
    assert Lower.__name__ == "Lower"
    assert Schema(Lower).schema is Lower


def test_match_pattern() -> None:
    """Match requires the string to match the pattern."""
    assert Schema(Match(r"^\d+$"))("123") == "123"

    with pytest.raises(MultipleInvalid) as caught:
        Schema(Match(r"^\d+$"))("12a")
    assert isinstance(caught.value.errors[0], MatchInvalid)


def test_match_on_non_string() -> None:
    """Match fails cleanly on a non-string instead of raising TypeError."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Match(r"^\d+$"))(123)
    assert isinstance(caught.value.errors[0], MatchInvalid)


def test_match_exposes_the_pattern_source() -> None:
    """Match keeps a compiled pattern whose source is readable."""
    assert Match(r"^\d+$").pattern.pattern == r"^\d+$"


def test_email_accepts_and_rejects() -> None:
    """Email (a factory like voluptuous) accepts a basic address, rejects bad ones."""
    for good in [
        "user@example.com",
        "a.b+c@sub.example.co.uk",
        "x@y.io",
        "a@host.example.",  # a single trailing root dot, accepted like voluptuous
    ]:
        assert Schema(Email())(good) == good

    for bad in [
        "no-at-sign",
        "a@b@c",
        "@example.com",
        "user@nodot",
        "john@example.com>",  # trailing junk in the domain
        "us er@example.com",  # whitespace in the local part
        "a@b..com",  # an empty domain label
        "a@-b.com",  # a label starting with a hyphen
        "a@b-.com",  # a label ending with a hyphen
        "a@b.1",  # a numeric top-level domain
        "a@1.2.3.4",  # a bare IP address, no real TLD
        "a..b@example.com",  # a doubled dot in the local part
        ".a@example.com",  # a leading dot in the local part
        "a.@example.com",  # a trailing dot in the local part
    ]:
        with pytest.raises(MultipleInvalid) as caught:
            Schema(Email())(bad)
        assert isinstance(caught.value.errors[0], EmailInvalid)


def test_url_accepts_and_rejects() -> None:
    """Url (a factory) requires a scheme and a host."""
    assert Schema(Url())("https://example.com/path") == "https://example.com/path"

    with pytest.raises(MultipleInvalid) as caught:
        Schema(Url())("not a url")
    assert isinstance(caught.value.errors[0], UrlInvalid)


def test_url_rejects_non_string() -> None:
    """Url fails cleanly on a value it cannot parse."""
    with pytest.raises(MultipleInvalid):
        Schema(Url())(b"\xff")


def test_url_custom_message() -> None:
    """The factory passes a custom message through to the raised error."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Url("bad link"))("nope")
    assert "bad link" in str(caught.value.errors[0])


def test_fqdn_url_requires_a_dotted_host() -> None:
    """FqdnUrl (a factory) requires the host to contain a dot."""
    assert Schema(FqdnUrl())("https://example.com") == "https://example.com"

    with pytest.raises(MultipleInvalid) as caught:
        Schema(FqdnUrl())("https://localhost")
    assert isinstance(caught.value.errors[0], UrlInvalid)


def test_fqdn_url_ignores_a_dot_in_the_userinfo() -> None:
    """A dot in the userinfo does not make the host fully-qualified.

    ``http://user.name@localhost`` has the dot in the credentials, not the host
    ``localhost``, so the check must look at the host alone and reject it.
    """
    with pytest.raises(MultipleInvalid) as caught:
        Schema(FqdnUrl())("http://user.name@localhost")
    assert isinstance(caught.value.errors[0], UrlInvalid)
    # The host itself being fully-qualified still passes, userinfo and all.
    assert (
        Schema(FqdnUrl())("http://user.name@host.example.com")
        == "http://user.name@host.example.com"
    )


def test_slug_accepts_a_valid_slug() -> None:
    """Slug accepts a lowercase slug and returns it unchanged."""
    assert Schema(Slug())("my_slug-1") == "my_slug-1"
    assert Schema(Slug())("a") == "a"


@pytest.mark.parametrize("value", [123, "", "-x", "x-", "Bad Slug", "café"])
def test_slug_rejects_invalid(value: object) -> None:
    """A non-string, empty, edge-separator, or non-slug value raises SlugInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Slug())(value)
    assert isinstance(caught.value.errors[0], SlugInvalid)


def test_is_regex_accepts_a_valid_pattern() -> None:
    """IsRegex returns a compilable pattern string unchanged."""
    assert Schema(IsRegex())(r"^\d+$") == r"^\d+$"


@pytest.mark.parametrize("value", ["(", "[a-", 5])
def test_is_regex_rejects_an_invalid_pattern(value: object) -> None:
    """An uncompilable pattern or a non-string raises MatchInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(IsRegex())(value)
    assert isinstance(caught.value.errors[0], MatchInvalid)


@pytest.mark.parametrize(
    ("validator", "ok", "bad"),
    [
        (Alpha(), "abc", "ab1"),
        (Alphanumeric(), "ab1", "a b"),
        (ASCII(), "hi!", "café"),
        (PrintableASCII(), "hi", "a\tb"),
        (NoWhitespace(), "abc", "a b"),
    ],
)
def test_character_classes(validator: object, ok: str, bad: str) -> None:
    """Each character-class validator accepts its class and rejects the rest."""
    assert Schema(validator)(ok) == ok

    with pytest.raises(MultipleInvalid) as caught:
        Schema(validator)(bad)
    assert isinstance(caught.value.errors[0], MatchInvalid)


def test_starts_with_and_ends_with() -> None:
    """StartsWith and EndsWith check string affixes."""
    assert Schema(StartsWith("foo"))("foobar") == "foobar"
    assert Schema(EndsWith(".txt"))("a.txt") == "a.txt"

    with pytest.raises(MultipleInvalid):
        Schema(StartsWith("foo"))("bar")
    with pytest.raises(MultipleInvalid):
        Schema(EndsWith(".txt"))(123)


def test_byte_length() -> None:
    """ByteLength bounds the UTF-8 byte length, not the code-point count."""
    assert Schema(ByteLength(min=1, max=3))("ab") == "ab"
    # 'é' is one character but two UTF-8 bytes.
    assert Schema(ByteLength(min=2, max=2))("é") == "é"

    with pytest.raises(MultipleInvalid):
        Schema(ByteLength(max=2))("abc")
    with pytest.raises(MultipleInvalid):
        Schema(ByteLength(min=2))("a")
    with pytest.raises(MultipleInvalid):
        Schema(ByteLength(min=1))(123)


@pytest.mark.parametrize("value", ["#abc", "#ff8800"])
def test_hex_color_accepts(value: str) -> None:
    """HexColor accepts 3- and 6-digit hex colors."""
    assert Schema(HexColor())(value) == value


def test_hex_color_returns_the_value_unchanged() -> None:
    """HexColor validates and returns the value as given; compose Lower to fold case."""
    assert Schema(HexColor())("#FF8800") == "#FF8800"
    assert Schema(All(HexColor(), Lower))("#FF8800") == "#ff8800"


@pytest.mark.parametrize("value", ["red", "#xyz", "ff8800", 5])
def test_hex_color_rejects(value: object) -> None:
    """A non-hex-color value raises MatchInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(HexColor())(value)
    assert isinstance(caught.value.errors[0], MatchInvalid)
