"""Errors raised by probatio when validation fails.

The hierarchy mirrors voluptuous so existing error handling keeps working: a
single ``Invalid`` base, an aggregating ``MultipleInvalid``, and a set of
semantic subclasses that callers catch by type.

Every error carries two layers. The voluptuous-compatible layer is ``path`` (a
list of segments), ``msg``, ``error_message`` (the bare message, without the
path), and ``error_type``; downstream code reads these attributes, so they keep
their voluptuous semantics. The structured layer is additive: a stable
machine-readable ``code`` (defaulted per error class) and a ``context`` dict,
both filled in by the built-in validators, plus ``translation_key`` /
``placeholders`` slots for localization that the built-ins leave empty for a
caller raising its own error to populate. All four are surfaced together by
``as_dict()``.

``str(error)`` is for humans and deliberately deviates from voluptuous
(ADR-015): the path renders as a dotted trail (``at 'hosts[2].name'``) instead
of ``@ data['hosts'][2]['name']``, and the ``error_type`` clause is not
rendered. Programmatic consumers read ``path``, ``code``, and ``as_dict()``;
the rendered string promises readability, not stability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Any, cast

# A single rendered path segment is capped at this length, so an error string
# cannot be blown up by a huge attacker-controlled mapping key. Far longer than
# any real key, so normal output is untouched.
_MAX_PATH_SEGMENT_LENGTH = 500


def _format_candidates(names: list[str]) -> str:
    """Render close-match names: ``'a'``, ``'a' or 'b'``, ``'a', 'b' or 'c'``."""
    quoted = [repr(name) for name in names]
    if len(quoted) == 1:
        return quoted[0]
    return f"{', '.join(quoted[:-1])} or {quoted[-1]}"


@dataclass(frozen=True)
class Location:
    """A source location for a value: its line, column, and file when known.

    Produced by a *locator* (for example the YAMLRocks-backed one from
    ``load_yaml_with_locations``) that maps an error's ``path`` back to where the
    offending value sits in the source. ``humanize_error`` appends ``str(...)`` of
    it; programmatic callers read the fields directly. Line and column are
    1-indexed; ``file`` is the source file (the included file, through nested
    ``!include`` layers) or ``None`` when the source was not a file.
    """

    line: int
    column: int
    file: str | None = None

    def __str__(self) -> str:
        """Render as ``file:line:column`` (or ``line:column`` without a file)."""
        where = f"{self.file}:" if self.file else ""
        return f"{where}{self.line}:{self.column}"


def _render_segment(segment: Any) -> str:
    """Render one path segment, truncating an unreasonably long repr."""
    text = repr(segment)
    if len(text) > _MAX_PATH_SEGMENT_LENGTH:
        return text[: _MAX_PATH_SEGMENT_LENGTH - 3] + "..."
    return text


# A mapping key that reads cleanly bare in a dotted path: identifier-like,
# hyphens allowed (common in configuration keys).
_BARE_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")


def render_path(path: list[Any]) -> str:
    """Render an error path as a dotted trail: ``server.port``, ``hosts[2].name``.

    This is the rendering ``str(error)`` uses; it is public so a consumer
    building its own error output renders paths the same way. Mapping keys join
    with dots, integer segments (list indices, integer keys) render as ``[n]``,
    and anything else (a key with spaces, a marker object) falls back to its
    bracketed ``repr``. Group segments keep their ``<group>`` rendering (see
    ``VirtualPathComponent``). An empty path renders as an empty string.
    """
    parts: list[str] = []
    for segment in path:
        if isinstance(segment, str):
            # str(...) honors subclasses like VirtualPathComponent (``<group>``).
            text = str(segment)
            if len(text) <= _MAX_PATH_SEGMENT_LENGTH and (
                _BARE_KEY.fullmatch(text)
                or (text.startswith("<") and text.endswith(">"))
            ):
                parts.append(f".{text}" if parts else text)
                continue
        elif isinstance(segment, int) and not isinstance(segment, bool):
            parts.append(f"[{segment}]")
            continue
        parts.append(f"[{_render_segment(segment)}]")
    return "".join(parts)


class Error(Exception):
    """Base class for all probatio errors."""


class SchemaError(Error):
    """The schema definition itself is invalid (a programming error)."""


class Invalid(Error):
    """The data did not match the schema."""

    # Stable machine-readable code for this kind of error. Subclasses set it, so
    # every raise is coded without passing ``code`` at the call site. An explicit
    # ``code`` argument still wins.
    default_code: str | None = None

    # Class-level defaults for the rarely-passed fields, stored on the instance
    # only when a non-default value is given. Error construction is a hot path in
    # its own right (an ``Any`` miss builds an error per branch and discards most),
    # and a store skipped is a store saved. The setters below still write through
    # to the instance, shadowing the class default, so mutation works unchanged.
    # ``_path`` stays per-instance: it is exposed as a mutable list.
    _error_type: str | None = None
    _secret = False
    _code: str | None = None
    _context: dict[str, Any] | None = None
    _translation_key: str | None = None
    _placeholders: dict[str, Any] | None = None

    def __init__(
        self,
        message: str,
        path: list[Any] | None = None,
        error_message: str | None = None,
        error_type: str | None = None,
        *,
        code: str | None = None,
        context: dict[str, Any] | None = None,
        translation_key: str | None = None,
        placeholders: dict[str, Any] | None = None,
    ) -> None:
        """Create an error for ``message`` at the given ``path``."""
        super().__init__(message)

        self._path = list(path) if path else []
        self._error_message = error_message or message
        if error_type is not None:
            self._error_type = error_type
        if code is not None:
            self._code = code
        # ``None`` until read: most errors never have their context/placeholders
        # looked at (a miss inside a combinator branch is built and discarded), so
        # the dict copies are deferred to the property getters.
        if context:
            self._context = dict(context)
        if translation_key is not None:
            self._translation_key = translation_key
        if placeholders:
            self._placeholders = dict(placeholders)

    @property
    def msg(self) -> str:
        """The human-readable message."""
        return cast("str", self.args[0])

    @property
    def path(self) -> list[Any]:
        """The path of keys and indices to the offending value."""
        return self._path

    @property
    def error_message(self) -> str:
        """The bare message, without the path appended."""
        return self._error_message

    @property
    def error_type(self) -> str | None:
        """The kind of value that failed, for example ``dictionary value``."""
        return self._error_type

    @error_type.setter
    def error_type(self, value: str | None) -> None:
        """Set the kind of value that failed (voluptuous sets this while compiling)."""
        self._error_type = value

    @property
    def secret(self) -> bool:
        """Whether the offending value must be redacted, not echoed, when rendered.

        Set by the mapping engine for an error under a ``Secret`` key, so
        ``humanize_error`` (and any consumer building its own output) shows a
        placeholder instead of the value.
        """
        return self._secret

    @secret.setter
    def secret(self, value: bool) -> None:
        """Mark (or unmark) the offending value for redaction."""
        self._secret = value

    @property
    def code(self) -> str | None:
        """The stable machine-readable code (the class default unless overridden)."""
        return self._code if self._code is not None else type(self).default_code

    @property
    def context(self) -> dict[str, Any]:
        """Structured detail about the failure (for example the expected type)."""
        if self._context is None:
            self._context = {}
        return self._context

    @property
    def translation_key(self) -> str | None:
        """An optional key for localizing the message."""
        return self._translation_key

    @property
    def placeholders(self) -> dict[str, Any]:
        """Values to interpolate into the translated message."""
        if self._placeholders is None:
            self._placeholders = {}
        return self._placeholders

    def __str__(self) -> str:
        """Render the message with the path to the offending value appended."""
        output = Exception.__str__(self)

        if self._path:
            output += f" at '{render_path(self._path)}'"

        return output

    def prepend(self, path: list[Any]) -> None:
        """Grow the path from the front, as the error bubbles up the schema."""
        self._path = [*path, *self._path]

    def as_dict(self) -> dict[str, Any]:
        """Render the error as a structured, serializable dictionary."""
        return {
            "code": self.code,
            "message": self.error_message,
            "path": list(self.path),
            "secret": self.secret,
            "context": dict(self.context),
            "translation_key": self.translation_key,
            "placeholders": dict(self.placeholders),
        }


_NO_SUGGESTION = object()


class _SuggestionInvalid(Invalid):
    """An ``Invalid`` that suggests close allowed values, matched only when read.

    The match against the allowed string ``suggest_pool`` (``difflib``, which is
    not cheap) is deferred until the error's ``candidates`` or message is actually
    read. An error raised speculatively inside a combinator and then discarded
    never pays for it; a surfaced error pays exactly once and caches the result.
    The "``, did you mean ...?``" suffix is appended to the default message only
    (a custom ``msg`` still records candidates but keeps its own text).
    """

    def __init__(
        self,
        message: str,
        path: list[Any] | None = None,
        error_message: str | None = None,
        error_type: str | None = None,
        *,
        suggest_value: Any = _NO_SUGGESTION,
        suggest_pool: tuple[str, ...] | list[str] = (),
        suggest_exclude: Any = _NO_SUGGESTION,
        suffix: bool = True,
        code: str | None = None,
        context: dict[str, Any] | None = None,
        translation_key: str | None = None,
        placeholders: dict[str, Any] | None = None,
    ) -> None:
        """Record what to match against; the match itself happens lazily.

        ``suggest_exclude`` names one pool entry to leave out of the match (an
        unknown key must not suggest itself back); it is applied lazily with the
        match, so the raiser can pass its prebuilt pool without copying it.
        """
        self._suggest_value = suggest_value
        self._suggest_pool = suggest_pool
        self._suggest_exclude = suggest_exclude
        self._with_suffix = suffix
        self._candidates: list[str] | None = None
        self._suffix_cache: str | None = None

        super().__init__(
            message,
            path,
            error_message,
            error_type,
            code=code,
            context=context,
            translation_key=translation_key,
            placeholders=placeholders,
        )

    @property
    def candidates(self) -> list[str]:
        """The close matches among the allowed values, computed on first read."""
        if self._candidates is None:
            value = self._suggest_value
            if isinstance(value, str):
                pool: tuple[str, ...] | list[str] = self._suggest_pool
                if self._suggest_exclude is not _NO_SUGGESTION:
                    exclude = self._suggest_exclude
                    pool = [name for name in pool if name != exclude]
                self._candidates = get_close_matches(value, pool)
            else:
                self._candidates = []
        return self._candidates

    def _suffix_text(self) -> str:
        """Return the ``, did you mean ...?`` fragment for the message, cached."""
        if self._suffix_cache is None:
            self._suffix_cache = (
                f", did you mean {_format_candidates(self.candidates)}?"
                if self._with_suffix and self.candidates
                else ""
            )
        return self._suffix_cache

    @property
    def error_message(self) -> str:
        """The bare message, with the suggestion suffix when there is one."""
        return self._error_message + self._suffix_text()

    @property
    def msg(self) -> str:
        """The human-readable message (same text as ``error_message`` here)."""
        return self.error_message

    @property
    def context(self) -> dict[str, Any]:
        """Structured detail, including the close matches when there are any."""
        ctx = dict(self._context) if self._context else {}
        if self.candidates:
            ctx.setdefault("candidates", self.candidates)
        return ctx

    def __str__(self) -> str:
        """Render the (suffixed) message with the path to the offending value."""
        output = self.error_message

        if self._path:
            output += f" at '{render_path(self._path)}'"

        return output


class MultipleInvalid(Invalid):
    """A collection of validation errors gathered from one validation pass."""

    def __init__(self, errors: list[Invalid] | None = None) -> None:
        """Wrap the given child errors (a shallow copy is kept)."""
        self.errors: list[Invalid] = list(errors) if errors else []

    def __repr__(self) -> str:
        """Show the wrapped errors."""
        return f"MultipleInvalid({self.errors!r})"

    @property
    def msg(self) -> str:
        """The first error's message (empty when the collection is empty)."""
        return self.errors[0].msg if self.errors else ""

    @property
    def path(self) -> list[Any]:
        """The first error's path (empty when the collection is empty)."""
        return self.errors[0].path if self.errors else []

    @property
    def error_message(self) -> str:
        """The first error's bare message (empty when the collection is empty)."""
        return self.errors[0].error_message if self.errors else ""

    @property
    def error_type(self) -> str | None:
        """The first error's type (None when the collection is empty)."""
        return self.errors[0].error_type if self.errors else None

    @error_type.setter
    def error_type(self, value: str | None) -> None:
        """Set the first error's type (kept read-write to match the base class)."""
        if self.errors:
            self.errors[0].error_type = value

    @property
    def secret(self) -> bool:
        """Whether the first error is redacted (False when the collection is empty)."""
        return self.errors[0].secret if self.errors else False

    @secret.setter
    def secret(self, value: bool) -> None:
        """Set the first error's redaction flag (kept read-write like the base)."""
        if self.errors:
            self.errors[0].secret = value

    @property
    def code(self) -> str | None:
        """The first error's code (None when the collection is empty)."""
        return self.errors[0].code if self.errors else None

    @property
    def context(self) -> dict[str, Any]:
        """The first error's context (empty when the collection is empty)."""
        return self.errors[0].context if self.errors else {}

    @property
    def translation_key(self) -> str | None:
        """The first error's translation key (None when the collection is empty)."""
        return self.errors[0].translation_key if self.errors else None

    @property
    def placeholders(self) -> dict[str, Any]:
        """The first error's placeholders (empty when the collection is empty)."""
        return self.errors[0].placeholders if self.errors else {}

    def add(self, error: Invalid) -> None:
        """Append another error to the collection."""
        self.errors.append(error)

    def prepend(self, path: list[Any]) -> None:
        """Prepend the path segments to every wrapped error."""
        for error in self.errors:
            error.prepend(path)

    def __str__(self) -> str:
        """Render the first error (a clear note when the collection is empty)."""
        return str(self.errors[0]) if self.errors else "no validation errors"

    def as_dict(self) -> dict[str, Any]:
        """Render every wrapped error as a structured dictionary."""
        return {"errors": [error.as_dict() for error in self.errors]}


class RequiredFieldInvalid(Invalid):
    """A required key was missing from the data."""

    default_code = "required"


class ObjectInvalid(Invalid):
    """The value is not the expected object."""

    default_code = "object"


class DictInvalid(Invalid):
    """The value is not a mapping."""

    default_code = "not_a_dictionary"


class ExtraKeysInvalid(_SuggestionInvalid):
    """A mapping key matched no schema key under ``PREVENT_EXTRA``.

    Carries ``candidates``: the close matches among the schema's known keys, so a
    caller can render (or has already rendered) a "did you mean ...?" hint. The
    match is lazy (see ``_SuggestionInvalid``) and empty when nothing was close.
    """

    default_code = "extra_keys_not_allowed"


class ExclusiveInvalid(Invalid):
    """More than one key from a mutually exclusive group was provided."""

    default_code = "exclusive"


class InclusiveInvalid(Invalid):
    """Some, but not all, keys from a co-dependent group were provided."""

    default_code = "inclusive"


class SequenceTypeInvalid(Invalid):
    """The value is not the expected sequence type (list, tuple, or set)."""

    default_code = "not_a_sequence"


class TypeInvalid(Invalid):
    """The value is not of the expected type."""

    default_code = "type"


class ValueInvalid(Invalid):
    """A validator rejected the value."""

    default_code = "value"


class ScalarInvalid(Invalid):
    """The value does not match a scalar literal."""

    default_code = "not_valid"


class CoerceInvalid(_SuggestionInvalid):
    """A value could not be coerced to the requested type.

    Carries ``candidates``: when the target is an ``Enum`` with string values, the
    close matches among them, so a caller can render (or has already rendered) a
    "did you mean ...?" hint. The match is lazy (see ``_SuggestionInvalid``) and
    empty for any other coercion.
    """

    default_code = "coerce"


class EnumInvalid(Invalid):
    """The value is not a member of the expected Enum, nor one of its values."""

    default_code = "enum"


class ImmutableInvalid(Invalid):
    """A field that may not change (immutable or write-once) was changed."""

    default_code = "immutable"


class AnyInvalid(Invalid):
    """The value matched none of the candidates."""

    default_code = "no_match"


class AllInvalid(Invalid):
    """The value failed one of a chain of validators."""

    default_code = "all"


class MatchInvalid(Invalid):
    """The value does not match the expected pattern."""

    default_code = "match"


class RangeInvalid(Invalid):
    """The value falls outside the allowed range."""

    default_code = "range"


class LengthInvalid(Invalid):
    """The value's length falls outside the allowed bounds."""

    default_code = "length"


class InInvalid(_SuggestionInvalid):
    """The value is not a member of the allowed set.

    Carries ``candidates``: the close matches among the allowed string members, so
    a caller can render (or has already rendered) a "did you mean ...?" hint. The
    match is lazy (see ``_SuggestionInvalid``) and empty when nothing was close
    enough or the members are not strings.
    """

    default_code = "not_in_list"


class NotInInvalid(Invalid):
    """The value is a member of a disallowed set."""

    default_code = "in_list"


class ContainsInvalid(Invalid):
    """The collection does not contain the required element."""

    default_code = "contains"


class ExactSequenceInvalid(Invalid):
    """The sequence does not match the expected exact sequence."""

    default_code = "exact_sequence"


class TrueInvalid(Invalid):
    """The value is not truthy."""

    default_code = "not_true"


class FalseInvalid(Invalid):
    """The value is not falsy."""

    default_code = "not_false"


class BooleanInvalid(Invalid):
    """The value could not be read as a boolean."""

    default_code = "boolean"


class UrlInvalid(Invalid):
    """The value is not a valid URL."""

    default_code = "url"


class EmailInvalid(Invalid):
    """The value is not a valid email address."""

    default_code = "email"


class DirInvalid(Invalid):
    """The value is not an existing directory."""

    default_code = "not_a_directory"


class LiteralInvalid(Invalid):
    """The value does not match a ``Literal``."""

    default_code = "not_valid"


class FileInvalid(Invalid):
    """The value is not an existing file."""

    default_code = "not_a_file"


class PathInvalid(Invalid):
    """The value is not an existing path."""

    default_code = "not_a_path"


class SymlinkInvalid(Invalid):
    """The value is not an existing symbolic link."""

    default_code = "not_a_symlink"


class SocketInvalid(Invalid):
    """The value is not an existing socket."""

    default_code = "not_a_socket"


class FifoInvalid(Invalid):
    """The value is not an existing named pipe (FIFO)."""

    default_code = "not_a_fifo"


class BlockDeviceInvalid(Invalid):
    """The value is not an existing block device."""

    default_code = "not_a_block_device"


class NotEnoughValid(Invalid):
    """Too few of a ``SomeOf`` group's validators passed."""

    default_code = "not_enough_valid"


class TooManyValid(Invalid):
    """Too many of a ``SomeOf`` group's validators passed."""

    default_code = "too_many_valid"


class DatetimeInvalid(Invalid):
    """The value is not a valid datetime."""

    default_code = "datetime"


class DateInvalid(Invalid):
    """The value is not a valid date."""

    default_code = "date"


class TimeInvalid(Invalid):
    """The value is not a valid time of day."""

    default_code = "time"


class DurationInvalid(Invalid):
    """The value is not a valid duration."""

    default_code = "duration"


class TimeZoneInvalid(Invalid):
    """The value is not a valid IANA time zone."""

    default_code = "time_zone"


class EpochInvalid(Invalid):
    """The value is not a valid Unix epoch timestamp."""

    default_code = "epoch"


class IpInvalid(Invalid):
    """The value is not a valid IP address or network."""

    default_code = "ip"


class MacAddressInvalid(Invalid):
    """The value is not a valid MAC address."""

    default_code = "mac_address"


class UuidInvalid(Invalid):
    """The value is not a valid UUID."""

    default_code = "uuid"


class HostnameInvalid(Invalid):
    """The value is not a valid hostname."""

    default_code = "hostname"


class SlugInvalid(Invalid):
    """The value is not a valid slug."""

    default_code = "slug"


class MultipleOfInvalid(Invalid):
    """The value is not a multiple of the required factor."""

    default_code = "multiple_of"


class JsonInvalid(Invalid):
    """The value is not a valid JSON string."""

    default_code = "json"


class YamlInvalid(Invalid):
    """The value is not a valid YAML string."""

    default_code = "yaml"
