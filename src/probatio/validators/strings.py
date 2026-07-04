"""String transforms and format validators.

The transforms are plain functions (matching voluptuous), so they are
identity-comparable, which schema serialization relies on. The format validators
avoid backtracking regular expressions: ``Url`` parses with the standard library
and ``Email`` uses simple string checks, so a crafted input cannot hang them.
"""

from __future__ import annotations

import re
import typing
from urllib.parse import urlparse

from probatio.error import (
    EmailInvalid,
    LengthInvalid,
    MatchInvalid,
    SchemaError,
    SlugInvalid,
    UrlInvalid,
)
from probatio.validators._base import _SafeValidator

# The characters allowed in a slug: lowercase ASCII letters, digits, and the two
# word separators. A frozenset test is linear, so no input can make it backtrack.
_SLUG_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-_")
# A hex color: a leading hash and 3 or 6 hex digits. Fixed counts, so no backtrack.
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _is_ascii_alpha(value: str) -> bool:
    """Whether the string is non-empty and only ASCII letters."""
    return value.isascii() and value.isalpha()


def _is_ascii_alnum(value: str) -> bool:
    """Whether the string is non-empty and only ASCII letters and digits."""
    return value.isascii() and value.isalnum()


def _is_printable_ascii(value: str) -> bool:
    """Whether the string is all printable ASCII (empty is printable)."""
    return value.isascii() and value.isprintable()


def _has_no_whitespace(value: str) -> bool:
    """Whether the string contains no whitespace character."""
    return not any(character.isspace() for character in value)


class _CharacterClass(_SafeValidator):
    """Base for the character-class string validators (Alpha, ASCII, ...)."""

    check: typing.Callable[[str], bool]
    message: str
    # The catalog key matching ``message``; underscored so it does not shadow the
    # error's ``translation_key`` property in readers' minds.
    _translation_key: str

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is a string of the right class, else MatchInvalid."""
        if isinstance(value, str) and type(self).check(value):
            return value
        raise MatchInvalid(self.msg, translation_key=self._translation_key)


class Alpha(_CharacterClass):
    """Require a string of only ASCII letters."""

    check = staticmethod(_is_ascii_alpha)
    message = "expected only ASCII letters"
    _translation_key = "expected_alpha"


class Alphanumeric(_CharacterClass):
    """Require a string of only ASCII letters and digits."""

    check = staticmethod(_is_ascii_alnum)
    message = "expected only ASCII letters and digits"
    _translation_key = "expected_alphanumeric"


class ASCII(_CharacterClass):
    """Require a string of only ASCII characters."""

    check = staticmethod(str.isascii)
    message = "expected only ASCII characters"
    _translation_key = "expected_ascii"


class PrintableASCII(_CharacterClass):
    """Require a string of only printable ASCII characters."""

    check = staticmethod(_is_printable_ascii)
    message = "expected only printable ASCII characters"
    _translation_key = "expected_printable_ascii"


class NoWhitespace(_CharacterClass):
    """Require a string with no whitespace."""

    check = staticmethod(_has_no_whitespace)
    message = "expected no whitespace"
    _translation_key = "expected_no_whitespace"


def _is_affix(value: typing.Any) -> bool:
    """Whether ``value`` is a valid ``startswith``/``endswith`` argument.

    ``str.startswith``/``endswith`` accept a string or a tuple of strings; anything
    else raises a ``TypeError`` at call time, so it is refused when the validator is
    built instead.
    """
    if isinstance(value, str):
        return True
    return isinstance(value, tuple) and all(isinstance(item, str) for item in value)


class StartsWith(_SafeValidator):
    """Require a string to start with a given prefix."""

    def __init__(self, prefix: str, msg: str | None = None) -> None:
        """Store the required prefix, rejecting a non-string one at build time."""
        if not _is_affix(prefix):
            message = "StartsWith prefix must be a string or a tuple of strings"
            raise SchemaError(message)
        self.prefix = prefix
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it starts with the prefix, else MatchInvalid."""
        if isinstance(value, str) and value.startswith(self.prefix):
            return value
        raise MatchInvalid(
            self.msg,
            translation_key="value_must_start_with",
            placeholders={"prefix": self.prefix},
        )


class EndsWith(_SafeValidator):
    """Require a string to end with a given suffix."""

    def __init__(self, suffix: str, msg: str | None = None) -> None:
        """Store the required suffix, rejecting a non-string one at build time."""
        if not _is_affix(suffix):
            message = "EndsWith suffix must be a string or a tuple of strings"
            raise SchemaError(message)
        self.suffix = suffix
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it ends with the suffix, else MatchInvalid."""
        if isinstance(value, str) and value.endswith(self.suffix):
            return value
        raise MatchInvalid(
            self.msg,
            translation_key="value_must_end_with",
            placeholders={"suffix": self.suffix},
        )


class ByteLength(_SafeValidator):
    """Require a string's UTF-8 byte length to fall within bounds.

    Distinct from ``Length``, which counts code points: a single emoji is one
    character but several bytes, and byte-limited backends care about the latter.
    """

    def __init__(
        self,
        min: typing.Any = None,
        max: typing.Any = None,
        msg: str | None = None,
    ) -> None:
        """Store the minimum and maximum allowed byte lengths."""
        self.min = min
        self.max = max
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if its UTF-8 byte length is in bounds, else raise."""
        if not isinstance(value, str):
            raise LengthInvalid(self.msg, translation_key="expected_string")

        # ``surrogatepass`` so a lone surrogate (``'\ud800'``) is measured rather
        # than leaking a UnicodeEncodeError.
        size = len(value.encode("utf-8", "surrogatepass"))
        try:
            out_of_bounds = (self.min is not None and size < self.min) or (
                self.max is not None and size > self.max
            )
        except TypeError as exc:
            # A non-numeric bound makes the comparison raise; report it cleanly like
            # Range does, rather than leak the TypeError.
            raise LengthInvalid(
                self.msg, translation_key="invalid_value_or_type"
            ) from exc
        if out_of_bounds:
            raise LengthInvalid(self.msg, translation_key="byte_length_out_of_bounds")

        return value


class HexColor(_SafeValidator):
    """Require a hex color string (``#rgb`` or ``#rrggbb``), returning it unchanged.

    Normalization here is only case folding, so compose with ``Lower`` (or ``Upper``)
    for a canonical case: ``All(HexColor(), Lower)``.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is a valid hex color, else raise MatchInvalid."""
        if isinstance(value, str) and _HEX_COLOR.match(value):
            return value
        raise MatchInvalid(self.msg, translation_key="expected_hex_color")


class Match(_SafeValidator):
    """Require a string to match a regular expression."""

    def __init__(self, pattern: typing.Any, msg: str | None = None) -> None:
        """Compile ``pattern`` (read its source as ``.pattern.pattern``).

        A ``str`` or ``bytes`` pattern is compiled now, so an invalid regular
        expression is a build-time ``SchemaError`` rather than a leaked ``re.error``;
        an already-compiled pattern is used as is. Anything else (an ``int``, a bare
        object) would only fail later on ``.match``, so it is refused here.
        """
        if isinstance(pattern, str | bytes):
            try:
                self.pattern = re.compile(pattern)
            except re.error as exc:
                message = (
                    f"Match pattern {pattern!r} is not a valid regular expression: "
                    f"{exc}"
                )
                raise SchemaError(message) from exc
        elif isinstance(pattern, re.Pattern):
            self.pattern = pattern
        else:
            message = (
                "Match pattern must be a string, bytes, or a compiled regular "
                "expression"
            )
            raise SchemaError(message)
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call, matching voluptuous."""
        return f"Match({self.pattern.pattern!r}, msg={self.msg!r})"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it matches, else raise MatchInvalid."""
        try:
            matched = self.pattern.match(value)
        except TypeError as exc:
            raise MatchInvalid(self.msg, translation_key="expected_string") from exc

        if not matched:
            raise MatchInvalid(self.msg, translation_key="does_not_match_pattern")

        return value


def Lower(value: typing.Any) -> str:
    """Lower-case the value (coercing to a string first)."""
    return str(value).lower()


def Upper(value: typing.Any) -> str:
    """Upper-case the value (coercing to a string first)."""
    return str(value).upper()


def Capitalize(value: typing.Any) -> str:
    """Capitalize the value (coercing to a string first)."""
    return str(value).capitalize()


def Title(value: typing.Any) -> str:
    """Title-case the value (coercing to a string first)."""
    return str(value).title()


def Strip(value: typing.Any) -> str:
    """Strip surrounding whitespace (coercing to a string first)."""
    return str(value).strip()


_EMAIL_LOCAL_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    "-!#$%&'*+/=?^_`{}|~.",
)
_EMAIL_LABEL_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-",
)


def _valid_email_local(local: str) -> bool:
    """Return whether the local part is well-formed, matching voluptuous.

    The unquoted local part is dot-separated runs of allowed characters, so a
    leading, trailing, or doubled dot is rejected (``a..b``, ``.a``, ``a.``). This
    mirrors voluptuous's ``USER_REGEX`` with plain string checks rather than a
    backtracking regular expression, so a crafted address cannot hang it. The
    whole-string form (one charset sweep, the dot included, plus the three dot
    placement checks) says exactly that without splitting into labels, and runs
    entirely in C.
    """
    return (
        _EMAIL_LOCAL_CHARS.issuperset(local)
        and local[0] != "."
        and local[-1] != "."
        and ".." not in local
    )


def _valid_email_domain(domain: str) -> bool:
    """Return whether the domain is a dotted host with valid labels and a TLD.

    Each dot-separated label is non-empty, at most 63 characters, made of ASCII
    letters/digits/hyphen, and does not start or end with a hyphen. There must be
    at least two labels and the final one (the TLD) at least two characters, so a
    single-label host or a bare IP like ``1.2.3.4`` is rejected. Digit-bearing
    TLDs are allowed, and a single trailing root dot (``host.example.``) is
    accepted, both matching voluptuous.
    """
    # voluptuous's DOMAIN_REGEX ends with an optional ``\.?``: one trailing root
    # dot is allowed. Strip it before the label checks so it does not read as an
    # empty final label.
    domain = domain.removesuffix(".")
    labels = domain.split(".")
    if len(labels) < 2 or len(labels[-1]) < 2:
        return False
    # A plain loop: the genexpr form pays a generator frame per validated address.
    for label in labels:
        if (
            not label
            or len(label) > 63
            or label[0] == "-"
            or label[-1] == "-"
            or not _EMAIL_LABEL_CHARS.issuperset(label)
        ):
            return False
    return True


def Email(msg: str | None = None) -> typing.Callable[[typing.Any], str]:
    """Return a validator for a basic email address.

    Like voluptuous, this is a factory: ``Email()`` builds the validator, so a
    schema uses ``Email()`` rather than the bare name. The checks are plain
    character-set and structure tests (no backtracking regular expression), so a
    crafted input cannot hang it. The RFC quoted local-part form (``"a..b"@x``)
    is not supported, a deliberate deviation from voluptuous; it is effectively
    never used in configuration.
    """

    def validate(value: typing.Any) -> str:
        """Validate a basic email address with simple string checks."""
        if not isinstance(value, str) or value.count("@") != 1:
            raise EmailInvalid(msg, translation_key="expected_email_address")

        local, _, domain = value.partition("@")
        if (
            not local
            or not _valid_email_local(local)
            or not _valid_email_domain(domain)
        ):
            raise EmailInvalid(msg, translation_key="expected_email_address")

        return value

    # Tag the closure so to_json_schema can render the called form Email() as a
    # string with format "email"; the bare reference is matched by identity.
    setattr(validate, "__probatio_json_format__", "email")  # noqa: B010
    return validate


def _validate_url(value: typing.Any, msg: str | None) -> typing.Any:
    """Validate that a value is a URL with a scheme and a host."""
    # Only a string or bytes can be a URL; anything else makes ``urlparse`` leak
    # an AttributeError (it reaches for ``.decode``), so reject it up front.
    if not isinstance(value, str | bytes):
        raise UrlInvalid(msg, translation_key="expected_url")

    try:
        parsed = urlparse(value)
    except (ValueError, TypeError) as exc:
        raise UrlInvalid(msg, translation_key="expected_url") from exc

    if not parsed.scheme or not parsed.netloc:
        raise UrlInvalid(msg, translation_key="expected_url")

    return value


def Url(msg: str | None = None) -> typing.Callable[[typing.Any], str | bytes]:
    """Return a validator for a URL with a scheme and a host (voluptuous factory).

    The validator returns its input unchanged on success: a URL is a ``str`` or
    ``bytes``, so the result is typed ``str | bytes`` rather than ``Any``.
    """

    def validate(value: typing.Any) -> str | bytes:
        """Validate a URL, parsing with the standard library."""
        return typing.cast("str | bytes", _validate_url(value, msg))

    setattr(validate, "__probatio_json_format__", "uri")  # noqa: B010
    return validate


def FqdnUrl(msg: str | None = None) -> typing.Callable[[typing.Any], str | bytes]:
    """Return a validator for a URL whose host is a fully-qualified domain name."""

    def validate(value: typing.Any) -> str | bytes:
        """Validate a URL and require its host to contain a dot."""
        _validate_url(value, msg)

        # Check the dot in the host, not the whole netloc: the netloc also holds the
        # userinfo and port, so ``http://user.name@localhost`` would otherwise pass
        # on the dot in ``user.name`` even though the host ``localhost`` has none.
        # ``hostname`` is bytes for a bytes URL and None when there is no host, so
        # match the separator to the type and reject a missing host.
        host = urlparse(value).hostname
        dot = b"." if isinstance(value, bytes) else "."
        if host is None or dot not in host:
            raise UrlInvalid(msg, translation_key="expected_url_with_fqdn")

        return typing.cast("str | bytes", value)

    setattr(validate, "__probatio_json_format__", "uri")  # noqa: B010
    return validate


class IsRegex(_SafeValidator):
    """Validate that the value is itself a compilable regular expression.

    Returns the string unchanged when it compiles. This checks the pattern is
    valid; it does not run it, so it is safe on any input. Use ``Match`` to
    validate values *against* a pattern.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it compiles as a regex, else raise MatchInvalid."""
        try:
            re.compile(value)
        except (re.error, TypeError) as exc:
            raise MatchInvalid(
                self.msg, translation_key="expected_valid_regex"
            ) from exc
        return value


class Slug(_SafeValidator):
    """Validate that a string is already a slug, returning it unchanged.

    A slug is a non-empty string of lowercase ASCII letters, digits, hyphens, and
    underscores, beginning and ending with a letter or digit. This validates the
    shape; it does not slugify arbitrary text (transliteration and separator
    policy belong to a dedicated package like ``python-slugify``, reached via
    ``Coerce``).
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> str:
        """Return the value if it is a valid slug, else raise SlugInvalid."""
        if (
            not isinstance(value, str)
            or not value
            or value[0] in "-_"
            or value[-1] in "-_"
            or not _SLUG_CHARS.issuperset(value)
        ):
            raise SlugInvalid(self.msg, translation_key="expected_slug")
        return value


class Replace(_SafeValidator):
    """Substitute every match of a pattern in a string."""

    def __init__(
        self,
        pattern: typing.Any,
        substitution: str,
        msg: str | None = None,
    ) -> None:
        """Compile ``pattern`` and remember the replacement text."""
        self.pattern = re.compile(pattern) if isinstance(pattern, str) else pattern
        self.substitution = substitution
        self.msg = msg
        # Validate the substitution now, not at call time. A bad group reference
        # (``\2`` with one group) is a schema error, and ``re`` parses the template
        # eagerly, so a dry run against an empty string surfaces it here as a clean
        # SchemaError rather than leaking ``re.error`` on the first matching value.
        try:
            self.pattern.sub(self.substitution, "")
        except re.error as exc:
            message = (
                f"Replace substitution {substitution!r} is not valid for pattern "
                f"{self.pattern.pattern!r}: {exc}"
            )
            raise SchemaError(message) from exc

    def __repr__(self) -> str:
        """Render as a constructor call, matching voluptuous."""
        return f"Replace({self.pattern.pattern!r}, {self.substitution!r}, msg={self.msg!r})"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the string with the pattern replaced, else raise MatchInvalid."""
        try:
            return self.pattern.sub(self.substitution, value)
        except TypeError as exc:
            raise MatchInvalid(self.msg, translation_key="expected_string") from exc
