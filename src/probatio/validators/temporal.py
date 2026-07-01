"""Date, time, datetime, duration, time-zone, and epoch validators.

``Datetime``/``Date``/``Time`` validate a string against a ``strptime`` format and
return it unchanged, matching voluptuous's string-in, string-out behavior.
``AsDatetime``/``AsDate``/``AsTime`` are the object-returning siblings: they parse
ISO 8601 out of the box (or a ``format=`` you pass) and hand back the parsed
``datetime``/``date``/``time`` instead of the original string. ``Duration``,
``TimeZoneInfo``, ``TimeZone``, and ``FromEpoch`` are probatio additions that coerce to
a Python object (``datetime.timedelta``, a named-zone ``zoneinfo.ZoneInfo``, a
fixed-offset ``datetime.timezone``, and a UTC ``datetime`` from a Unix timestamp),
since that typed value is the point.
"""

from __future__ import annotations

import datetime
import re
import typing
import zoneinfo

from probatio.error import (
    DateInvalid,
    DatetimeInvalid,
    DurationInvalid,
    EpochInvalid,
    SchemaError,
    TimeInvalid,
    TimeZoneInvalid,
)
from probatio.validators._base import _SafeValidator

# A colon duration has hours:minutes or hours:minutes:seconds.
_DURATION_PARTS = (2, 3)
_MAX_CLOCK_FIELD = 59  # the minute and second fields of an H:MM:SS duration
_DURATION_MSG = (
    "expected a duration like H:MM, H:MM:SS, an ISO 8601 duration like PT1H30M, "
    "or a number of seconds"
)

# An ISO 8601 duration, limited to the fields a ``timedelta`` can represent: weeks
# and days, then a time part of hours, minutes, and seconds. Each field is optional
# and may be fractional (a comma or a period). Years and months are left out on
# purpose, since neither is a fixed length. Each quantifier is anchored to a distinct
# trailing letter and none nest, so the match is linear with no backtracking blowup;
# a long digit run is matched and ``float``-parsed in linear time (``float`` has no
# quadratic path and overflows to a caught error), not a hang. Emptiness (``P``,
# ``PT``) and a dangling ``T`` are caught after the match, not by the pattern.
_ISO8601_DURATION = re.compile(
    r"P"
    r"(?:(?P<weeks>\d+(?:[.,]\d+)?)W)?"
    r"(?:(?P<days>\d+(?:[.,]\d+)?)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+(?:[.,]\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:[.,]\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:[.,]\d+)?)S)?"
    r")?",
)

# A fixed UTC offset: a sign, two-digit hours, optional colon, two-digit minutes.
# Matched in full, no backtracking, so a crafted string cannot make it hang.
_UTC_OFFSET = re.compile(r"[+-]\d{2}:?\d{2}")
_TZ_OFFSET_MSG = "expected a UTC offset like +01:00, Z, or UTC"

# How many epoch sub-units make one second, per accepted ``FromEpoch`` unit.
_EPOCH_DIVISORS = {"seconds": 1, "milliseconds": 1000}


def _format_message(kind: str, fmt: str | None) -> str:
    """Build the parse-failure message for an ``As*`` validator."""
    if fmt is None:
        return f"expected an ISO 8601 {kind}"
    return f"value does not match expected format {fmt}"


def _iso_field(raw: str | None) -> float:
    """Read one ISO 8601 duration field (``"1"``, ``"1.5"``, ``"1,5"``) as a float.

    A missing field (``None``) reads as zero, and a comma decimal separator is
    normalized to a period for ``float``.
    """
    return float(raw.replace(",", ".")) if raw else 0.0


class Datetime(_SafeValidator):
    """Validate that a string parses as a datetime in the given format."""

    DEFAULT_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

    def __init__(self, format: str | None = None, msg: str | None = None) -> None:
        """Store the strptime format (read as ``.format``) and a message."""
        self.format = format or self.DEFAULT_FORMAT
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call, matching voluptuous (covers Date/Time)."""
        return f"{type(self).__name__}(format={self.format})"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it parses, else raise DatetimeInvalid."""
        try:
            datetime.datetime.strptime(value, self.format)  # noqa: DTZ007
        except (TypeError, ValueError) as exc:
            message = self.msg or f"value does not match expected format {self.format}"
            raise DatetimeInvalid(message) from exc
        return value


class Date(Datetime):
    """Validate that a string parses as a date in the given format."""

    DEFAULT_FORMAT = "%Y-%m-%d"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it parses, else raise DateInvalid."""
        try:
            datetime.datetime.strptime(value, self.format)  # noqa: DTZ007
        except (TypeError, ValueError) as exc:
            message = self.msg or f"value does not match expected format {self.format}"
            raise DateInvalid(message) from exc
        return value


class Time(Datetime):
    """Validate that a string parses as a time of day in the given format.

    The sibling of ``Date``/``Datetime`` for a wall-clock time (voluptuous issue
    #335). Defaults to ``%H:%M:%S``; pass ``format="%H:%M"`` to drop the seconds.
    """

    DEFAULT_FORMAT = "%H:%M:%S"

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it parses, else raise TimeInvalid."""
        try:
            datetime.datetime.strptime(value, self.format)  # noqa: DTZ007
        except (TypeError, ValueError) as exc:
            message = self.msg or f"value does not match expected format {self.format}"
            raise TimeInvalid(message) from exc
        return value


class AsDatetime(_SafeValidator):
    """Parse a string into a ``datetime.datetime``.

    Parses ISO 8601 by default, accepting anything ``datetime.fromisoformat``
    accepts on this Python (the ``T`` or space separator, a ``Z`` or ``+HH:MM``
    offset, fractional seconds). Pass ``format=`` to parse a specific ``strptime``
    layout instead. Returns the parsed ``datetime.datetime``, not the original
    string. Set ``require_timezone`` to reject a naive result (one without
    ``tzinfo``); the ISO default reads the offset, so this needs no extra format.

    Parsing uses the standard library only, on purpose: a faster backend like
    ciso8601 accepts a different set of strings and returns a different ``tzinfo``
    type, which would make validation depend on what is installed.
    """

    def __init__(
        self,
        format: str | None = None,
        *,
        require_timezone: bool = False,
        msg: str | None = None,
    ) -> None:
        """Store the optional strptime format, the tz requirement, and a message."""
        self.format = format
        self.require_timezone = require_timezone
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call, matching the temporal validators."""
        return (
            f"{type(self).__name__}(format={self.format}, "
            f"require_timezone={self.require_timezone!r})"
        )

    def __call__(self, value: typing.Any) -> datetime.datetime:
        """Return the parsed datetime, passing an existing datetime through.

        A ``datetime`` already (a YAML/TOML loader produces one natively) is returned
        as-is; a string is parsed. The timezone requirement still applies to both.
        """
        if isinstance(value, datetime.datetime):
            parsed = value
        else:
            try:
                if self.format is None:
                    parsed = datetime.datetime.fromisoformat(value)
                else:
                    parsed = datetime.datetime.strptime(value, self.format)  # noqa: DTZ007
            except (TypeError, ValueError) as exc:
                message = self.msg or _format_message("datetime", self.format)
                raise DatetimeInvalid(message) from exc

        if self.require_timezone and parsed.tzinfo is None:
            raise DatetimeInvalid(self.msg or "expected a timezone-aware datetime")

        return parsed


class AsDate(_SafeValidator):
    """Parse a string into a ``datetime.date``.

    The object-returning sibling of ``Date``: it returns the parsed
    ``datetime.date`` instead of the original string. Parses ISO 8601
    (``YYYY-MM-DD``) by default; pass ``format=`` for a specific ``strptime``
    layout.
    """

    def __init__(self, format: str | None = None, msg: str | None = None) -> None:
        """Store the optional strptime format (read as ``.format``) and a message."""
        self.format = format
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call, matching the temporal validators."""
        return f"{type(self).__name__}(format={self.format})"

    def __call__(self, value: typing.Any) -> datetime.date:
        """Return the parsed date, passing an existing date through.

        A pure ``date`` is returned as-is; a ``datetime`` is not a date here (it
        carries a time, so a date field rejects it), and a string is parsed.
        """
        if isinstance(value, datetime.date) and not isinstance(
            value, datetime.datetime
        ):
            return value
        try:
            if self.format is None:
                return datetime.date.fromisoformat(value)
            return datetime.datetime.strptime(value, self.format).date()  # noqa: DTZ007
        except (TypeError, ValueError) as exc:
            message = self.msg or _format_message("date", self.format)
            raise DateInvalid(message) from exc


class AsTime(_SafeValidator):
    """Parse a string into a ``datetime.time``.

    The object-returning sibling of ``Time``: it returns the parsed
    ``datetime.time`` instead of the original string. Parses ISO 8601
    (``HH:MM[:SS]``) by default; pass ``format=`` for a specific ``strptime``
    layout.
    """

    def __init__(self, format: str | None = None, msg: str | None = None) -> None:
        """Store the optional strptime format (read as ``.format``) and a message."""
        self.format = format
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call, matching the temporal validators."""
        return f"{type(self).__name__}(format={self.format})"

    def __call__(self, value: typing.Any) -> datetime.time:
        """Return the parsed time, passing an existing time through.

        A ``time`` already is returned as-is; a string is parsed.
        """
        if isinstance(value, datetime.time):
            return value
        try:
            if self.format is None:
                return datetime.time.fromisoformat(value)
            return datetime.datetime.strptime(value, self.format).time()  # noqa: DTZ007
        except (TypeError, ValueError) as exc:
            message = self.msg or _format_message("time", self.format)
            raise TimeInvalid(message) from exc


class AsTimedelta(_SafeValidator):
    """Parse a duration into a ``datetime.timedelta``.

    Accepts a ``timedelta`` (passed through), a number of seconds (an ``int``,
    ``float``, or numeric string like ``"90"``), a colon string (``"H:MM"`` or
    ``"H:MM:SS"``, optionally negative), an ISO 8601 duration (``"P1DT2H30M"``,
    ``"PT45S"``, ``"-P3D"``), or a mapping of ``timedelta`` keyword arguments
    (``{"hours": 1, "minutes": 30}``). An ISO 8601 duration is limited to the fields
    a ``timedelta`` can represent (weeks, days, hours, minutes, seconds); years and
    months are rejected, since neither is a fixed length. ``Duration`` is the
    validate-only sibling that checks the same forms and returns the value unchanged.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> datetime.timedelta:
        """Return the value as a timedelta, else raise DurationInvalid."""
        if isinstance(value, datetime.timedelta):
            return value

        if isinstance(value, bool):
            # ``bool`` is an ``int`` subclass, but true and false are not durations.
            raise DurationInvalid(self.msg or "expected a duration")

        if isinstance(value, int | float):
            try:
                return datetime.timedelta(seconds=value)
            except (OverflowError, ValueError) as exc:
                # A huge value overflows; ``float('nan')`` raises ValueError.
                raise DurationInvalid(self.msg or "expected a duration") from exc

        if isinstance(value, str):
            return self._parse_string(value)

        if isinstance(value, dict):
            try:
                return datetime.timedelta(**value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise DurationInvalid(self.msg or "expected a duration") from exc

        raise DurationInvalid(self.msg or "expected a duration")

    def _parse_string(self, value: str) -> datetime.timedelta:
        """Parse an ISO 8601, ``H:MM`` / ``H:MM:SS`` colon, or seconds string.

        An ISO 8601 duration (``"P1DT2H"``, ``"PT30M"``, ``"-P3D"``) is coerced to a
        ``timedelta``. A bare numeric string (``"90"``, ``"90.5"``) is read as
        seconds, matching an ``int``/``float`` input, so ``AsTimedelta`` covers the
        whole time-period family rather than only the colon form.
        """
        text = value.strip()

        # An ISO 8601 duration: an optional sign, then ``P`` and its fields.
        head = text[1:] if text[:1] in ("+", "-") else text
        if head[:1] == "P":
            sign = -1 if text[:1] == "-" else 1
            return sign * self._parse_iso8601(head)

        sign = 1
        if text.startswith("-"):
            sign, text = -1, text[1:]

        if ":" not in text:
            return sign * self._seconds(text)

        parts = text.split(":")
        if len(parts) not in _DURATION_PARTS or not all(p.isdigit() for p in parts):
            raise DurationInvalid(self.msg or _DURATION_MSG)
        hours, minutes, *rest = (int(part) for part in parts)
        seconds = rest[0] if rest else 0

        # In clock-style input, minutes and seconds stay in their usual range.
        # Hours remain unbounded because durations can be longer than a day.
        if minutes > _MAX_CLOCK_FIELD or seconds > _MAX_CLOCK_FIELD:
            raise DurationInvalid(self.msg or _DURATION_MSG)

        try:
            return sign * datetime.timedelta(
                hours=hours,
                minutes=minutes,
                seconds=seconds,
            )
        except OverflowError as exc:
            raise DurationInvalid(self.msg or _DURATION_MSG) from exc

    def _seconds(self, text: str) -> datetime.timedelta:
        """Read a bare number of seconds (``"90"``, ``"90.5"``) as a timedelta."""
        try:
            return datetime.timedelta(seconds=float(text))
        except (ValueError, OverflowError) as exc:
            # ``float("abc")`` and an empty string raise ValueError; ``"inf"`` or a
            # huge value overflows timedelta; ``"nan"`` raises ValueError there.
            raise DurationInvalid(self.msg or _DURATION_MSG) from exc

    def _parse_iso8601(self, body: str) -> datetime.timedelta:
        """Coerce an ISO 8601 duration body (``"P..."``) to a ``timedelta``.

        Only the timedelta-representable fields are accepted (weeks, days, hours,
        minutes, seconds). A bare ``"P"``, a ``"PT"`` with no time field, a dangling
        ``"T"``, and any years or months all raise ``DurationInvalid``.
        """
        match = _ISO8601_DURATION.fullmatch(body)
        if match is None:
            raise DurationInvalid(self.msg or _DURATION_MSG)

        fields = match.groupdict()
        has_time = fields["hours"] or fields["minutes"] or fields["seconds"]
        if not any(fields.values()) or ("T" in body and not has_time):
            # ``P`` alone carries nothing; ``P1DT`` has a time separator but no field.
            raise DurationInvalid(self.msg or _DURATION_MSG)

        try:
            return datetime.timedelta(
                weeks=_iso_field(fields["weeks"]),
                days=_iso_field(fields["days"]),
                hours=_iso_field(fields["hours"]),
                minutes=_iso_field(fields["minutes"]),
                seconds=_iso_field(fields["seconds"]),
            )
        except (ValueError, OverflowError) as exc:
            raise DurationInvalid(self.msg or _DURATION_MSG) from exc


class Duration(_SafeValidator):
    """Validate a duration, returning the value unchanged.

    Accepts the same forms as ``AsTimedelta`` (a ``timedelta``, a number of seconds, a
    ``H:MM``/``H:MM:SS`` or ISO 8601 duration string, or a ``timedelta`` keyword
    mapping) and hands the value back as given. Use ``AsTimedelta`` when you want the
    parsed ``datetime.timedelta`` object instead.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is a valid duration, else raise DurationInvalid."""
        AsTimedelta(msg=self.msg)(value)
        return value


class TimeZoneInfo(_SafeValidator):
    """Validate an IANA time zone name, returning the value unchanged.

    Use ``Coerce(zoneinfo.ZoneInfo)`` when you want the parsed ``zoneinfo.ZoneInfo``
    object. For a fixed UTC offset (``+01:00``) rather than a named zone, use
    ``TimeZone`` (with ``AsTimezone`` for the ``datetime.timezone`` object).
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is a valid IANA zone, else raise TimeZoneInvalid."""
        if isinstance(value, zoneinfo.ZoneInfo):
            # An already-resolved zone passes through, so validation is idempotent.
            return value
        try:
            zoneinfo.ZoneInfo(value)
        except (KeyError, ValueError, TypeError, RuntimeError) as exc:
            # ZoneInfoNotFoundError is a KeyError; a bad path is a ValueError; a
            # non-string is a TypeError; a tuple trips the weak-cache RuntimeError.
            raise TimeZoneInvalid(self.msg or "expected an IANA time zone") from exc
        return value


class AsTimezone(_SafeValidator):
    """Parse a fixed UTC offset into a ``datetime.timezone``.

    Accepts an offset string (``+01:00``, ``-0530``, ``Z``), the literal ``UTC``, or
    a native ``datetime.timezone`` (passed through). ``TimeZone`` is the validate-only
    sibling that checks the same forms and returns the value unchanged. For a named
    IANA zone (``Europe/Amsterdam``), use ``TimeZoneInfo``.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> datetime.timezone:
        """Return the parsed fixed-offset timezone, else raise TimeZoneInvalid."""
        if isinstance(value, datetime.timezone):
            return value
        if not isinstance(value, str):
            raise TimeZoneInvalid(self.msg or _TZ_OFFSET_MSG)

        # ``Z`` and ``UTC`` name the zero offset; otherwise the value must be a signed
        # ``HH:MM``/``HHMM`` offset. Parsed by hand, not ``strptime("%z")``, whose
        # accepted set drifts between Python versions (3.15 accepts ``""``).
        if value.upper() in ("Z", "UTC"):
            return datetime.UTC
        if not _UTC_OFFSET.fullmatch(value):
            raise TimeZoneInvalid(self.msg or _TZ_OFFSET_MSG)

        sign = -1 if value[0] == "-" else 1
        digits = value[1:].replace(":", "")
        offset = datetime.timedelta(
            hours=sign * int(digits[:2]),
            minutes=sign * int(digits[2:]),
        )
        try:
            return datetime.timezone(offset)
        except ValueError as exc:
            # An offset of 24 hours or more is out of range for ``datetime.timezone``.
            raise TimeZoneInvalid(self.msg or _TZ_OFFSET_MSG) from exc


class TimeZone(_SafeValidator):
    """Validate a fixed UTC offset, returning the value unchanged.

    Accepts an offset string (``+01:00``, ``-0530``, ``Z``, ``UTC``) or a native
    ``datetime.timezone`` (passed through), and returns it as given. Use
    ``AsTimezone`` when you want the parsed ``datetime.timezone`` object. For a named
    IANA zone (``Europe/Amsterdam``), use ``TimeZoneInfo``.
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> typing.Any:
        """Return the value if it is a valid UTC offset, else raise TimeZoneInvalid."""
        AsTimezone(msg=self.msg)(value)
        return value


class FromEpoch(_SafeValidator):
    """Parse a Unix timestamp into a timezone-aware ``datetime.datetime`` in UTC.

    Accepts an ``int`` or ``float`` count since the epoch (1970-01-01 UTC),
    ``unit="seconds"`` by default or ``unit="milliseconds"``. The result is always
    aware and in UTC: a naive, local result would depend on the host's time zone,
    so the same input would validate to different moments on different machines. A
    ``bool``, a string, or an out-of-range or NaN value is rejected.
    """

    def __init__(self, unit: str = "seconds", msg: str | None = None) -> None:
        """Store the unit (``seconds`` or ``milliseconds``) and an optional message."""
        if unit not in _EPOCH_DIVISORS:
            options = ", ".join(sorted(_EPOCH_DIVISORS))
            message = f"unit must be one of {options}, got {unit!r}"
            raise SchemaError(message)
        self.unit = unit
        self.msg = msg

    def __repr__(self) -> str:
        """Render as a constructor call, matching the temporal validators."""
        return f"FromEpoch(unit={self.unit})"

    def __call__(self, value: typing.Any) -> datetime.datetime:
        """Return the timestamp as an aware UTC datetime, else raise EpochInvalid."""
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise EpochInvalid(self.msg or "expected a Unix timestamp")

        try:
            seconds = value / _EPOCH_DIVISORS[self.unit]
            return datetime.datetime.fromtimestamp(seconds, tz=datetime.UTC)
        except (OverflowError, OSError, ValueError) as exc:
            # A huge value overflows (OverflowError/OSError); ``float('nan')`` and
            # ``float('inf')`` raise ValueError/OverflowError out of fromtimestamp.
            raise EpochInvalid(self.msg or "expected a Unix timestamp") from exc
