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

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is a string of the right class, else MatchInvalid."""
        if isinstance(value, str) and type(self).check(value):
            return value
        raise MatchInvalid(self.msg or self.message)


class Alpha(_CharacterClass):
    """Require a string of only ASCII letters."""

    check = staticmethod(_is_ascii_alpha)
    message = "expected only ASCII letters"


class Alphanumeric(_CharacterClass):
    """Require a string of only ASCII letters and digits."""

    check = staticmethod(_is_ascii_alnum)
    message = "expected only ASCII letters and digits"


class ASCII(_CharacterClass):
    """Require a string of only ASCII characters."""

    check = staticmethod(str.isascii)
    message = "expected only ASCII characters"


class PrintableASCII(_CharacterClass):
    """Require a string of only printable ASCII characters."""

    check = staticmethod(_is_printable_ascii)
    message = "expected only printable ASCII characters"


class NoWhitespace(_CharacterClass):
    """Require a string with no whitespace."""

    check = staticmethod(_has_no_whitespace)
    message = "expected no whitespace"


class StartsWith(_SafeValidator):
    """Require a string to start with a given prefix."""

    def __init__(self, prefix: str, msg: str | None = None) -> None:
        """Store the required prefix."""
        self.prefix = prefix
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it starts with the prefix, else MatchInvalid."""
        if isinstance(value, str) and value.startswith(self.prefix):
            return value
        raise MatchInvalid(self.msg or f"value must start with {self.prefix!r}")


class EndsWith(_SafeValidator):
    """Require a string to end with a given suffix."""

    def __init__(self, suffix: str, msg: str | None = None) -> None:
        """Store the required suffix."""
        self.suffix = suffix
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it ends with the suffix, else MatchInvalid."""
        if isinstance(value, str) and value.endswith(self.suffix):
            return value
        raise MatchInvalid(self.msg or f"value must end with {self.suffix!r}")


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
            raise LengthInvalid(self.msg or "expected a string")
        # ``surrogatepass`` so a lone surrogate (``'\ud800'``) is measured rather
        # than leaking a UnicodeEncodeError.
        size = len(value.encode("utf-8", "surrogatepass"))
        if (self.min is not None and size < self.min) or (
            self.max is not None and size > self.max
        ):
            raise LengthInvalid(self.msg or "byte length out of bounds")
        return value


class HexColor(_SafeValidator):
    """Require a hex color string (``#rgb`` or ``#rrggbb``).

    With ``normalize`` (the default) the value is lower-cased, or upper-cased with
    ``upper=True``, keeping the leading ``#``; ``normalize=False`` returns it
    unchanged.
    """

    def __init__(
        self,
        normalize: bool = True,
        *,
        upper: bool = False,
        msg: str | None = None,
    ) -> None:
        """Store the normalization options and an optional custom message."""
        self.normalize = normalize
        self.upper = upper
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the hex color (cased when normalizing), else MatchInvalid."""
        if isinstance(value, str) and _HEX_COLOR.match(value):
            if not self.normalize:
                return value
            return value.upper() if self.upper else value.lower()
        raise MatchInvalid(self.msg or "expected a hex color like #rrggbb")


class Match(_SafeValidator):
    """Require a string to match a regular expression."""

    def __init__(self, pattern: typing.Any, msg: str | None = None) -> None:
        """Compile ``pattern`` (read its source as ``.pattern.pattern``)."""
        self.pattern = re.compile(pattern) if isinstance(pattern, str) else pattern
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call, matching voluptuous."""
        return f"Match({self.pattern.pattern!r}, msg={self.msg!r})"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it matches, else raise MatchInvalid."""
        try:
            matched = self.pattern.match(value)
        except TypeError as exc:
            message = self.msg or "expected a string"
            raise MatchInvalid(message) from exc
        if not matched:
            message = self.msg or "does not match the expected pattern"
            raise MatchInvalid(message)
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
# The same set without the dot: the dot separates labels, so it is not a label
# character. Matches voluptuous's USER_REGEX, which allows a dot only between
# non-empty runs of these characters.
_EMAIL_LOCAL_LABEL_CHARS = _EMAIL_LOCAL_CHARS - {"."}
_EMAIL_LABEL_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-",
)


def _valid_email_local(local: str) -> bool:
    """Return whether the local part is well-formed, matching voluptuous.

    The unquoted local part is dot-separated runs of allowed characters, so a
    leading, trailing, or doubled dot is rejected (``a..b``, ``.a``, ``a.``). This
    mirrors voluptuous's ``USER_REGEX`` with plain string checks rather than a
    backtracking regular expression, so a crafted address cannot hang it.
    """
    return all(
        label and _EMAIL_LOCAL_LABEL_CHARS.issuperset(label)
        for label in local.split(".")
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
    return all(
        label
        and len(label) <= 63
        and label[0] != "-"
        and label[-1] != "-"
        and _EMAIL_LABEL_CHARS.issuperset(label)
        for label in labels
    )


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
            raise EmailInvalid(msg or "expected an email address")
        local, _, domain = value.partition("@")
        if (
            not local
            or not _valid_email_local(local)
            or not _valid_email_domain(domain)
        ):
            raise EmailInvalid(msg or "expected an email address")
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
        raise UrlInvalid(msg or "expected a URL")
    try:
        parsed = urlparse(value)
    except (ValueError, TypeError) as exc:
        raise UrlInvalid(msg or "expected a URL") from exc
    if not parsed.scheme or not parsed.netloc:
        raise UrlInvalid(msg or "expected a URL")
    return value


def Url(msg: str | None = None) -> typing.Callable[[typing.Any], typing.Any]:
    """Return a validator for a URL with a scheme and a host (voluptuous factory)."""

    def validate(value: typing.Any) -> typing.Any:
        """Validate a URL, parsing with the standard library."""
        return _validate_url(value, msg)

    setattr(validate, "__probatio_json_format__", "uri")  # noqa: B010
    return validate


def FqdnUrl(msg: str | None = None) -> typing.Callable[[typing.Any], typing.Any]:
    """Return a validator for a URL whose host is a fully-qualified domain name."""

    def validate(value: typing.Any) -> typing.Any:
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
            raise UrlInvalid(msg or "expected a URL with a fully-qualified domain name")
        return value

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
            message = self.msg or "expected a valid regular expression"
            raise MatchInvalid(message) from exc
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
            raise SlugInvalid(self.msg or "expected a slug")
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

    def __repr__(self) -> str:
        """Render as a constructor call, matching voluptuous."""
        return f"Replace({self.pattern.pattern!r}, {self.substitution!r}, msg={self.msg!r})"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the string with the pattern replaced, else raise MatchInvalid."""
        try:
            return self.pattern.sub(self.substitution, value)
        except TypeError as exc:
            message = self.msg or "expected a string"
            raise MatchInvalid(message) from exc
