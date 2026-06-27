"""Date, time, datetime, duration, and time-zone validators.

``Datetime``/``Date``/``Time`` validate a string against a ``strptime`` format and
return it unchanged, matching voluptuous's string-in, string-out behavior.
``Duration`` and ``TimeZone`` are probatio additions that coerce to a Python
object (``datetime.timedelta`` and ``zoneinfo.ZoneInfo``), since that typed value
is the point.
"""

from __future__ import annotations

import datetime
import typing
import zoneinfo

from probatio.error import (
    DateInvalid,
    DatetimeInvalid,
    DurationInvalid,
    TimeInvalid,
    TimeZoneInvalid,
)
from probatio.validators._base import _SafeValidator

# A colon duration has hours:minutes or hours:minutes:seconds.
_DURATION_PARTS = (2, 3)


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


class Duration(_SafeValidator):
    """Validate a duration, returning a ``datetime.timedelta``.

    Accepts a ``timedelta`` (passed through), a number of seconds, a colon string
    (``"H:MM"`` or ``"H:MM:SS"``, optionally negative), or a mapping of
    ``timedelta`` keyword arguments (``{"hours": 1, "minutes": 30}``).
    """

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> datetime.timedelta:
        """Return the value as a timedelta, else raise DurationInvalid."""
        if isinstance(value, datetime.timedelta):
            return value
        if isinstance(value, bool):
            # A bool is an int, but "true seconds" is never what a config means.
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
        """Parse a ``H:MM`` / ``H:MM:SS`` colon string into a timedelta."""
        text = value.strip()
        sign = 1
        if text.startswith("-"):
            sign, text = -1, text[1:]
        parts = text.split(":")
        if len(parts) not in _DURATION_PARTS or not all(p.isdigit() for p in parts):
            message = self.msg or "expected a duration like H:MM or H:MM:SS"
            raise DurationInvalid(message)
        hours, minutes, *rest = (int(part) for part in parts)
        seconds = rest[0] if rest else 0
        try:
            return sign * datetime.timedelta(
                hours=hours,
                minutes=minutes,
                seconds=seconds,
            )
        except OverflowError as exc:
            message = self.msg or "expected a duration like H:MM or H:MM:SS"
            raise DurationInvalid(message) from exc


class TimeZone(_SafeValidator):
    """Validate an IANA time zone name, returning a ``zoneinfo.ZoneInfo``."""

    def __init__(self, msg: str | None = None) -> None:
        """Store an optional custom message."""
        self.msg = msg

    def __call__(self, value: typing.Any) -> zoneinfo.ZoneInfo:
        """Return the resolved time zone, else raise TimeZoneInvalid."""
        if isinstance(value, zoneinfo.ZoneInfo):
            # An already-resolved zone passes through, so validation is idempotent.
            return value
        try:
            return zoneinfo.ZoneInfo(value)
        except (KeyError, ValueError, TypeError, RuntimeError) as exc:
            # ZoneInfoNotFoundError is a KeyError; a bad path is a ValueError; a
            # non-string is a TypeError; a tuple trips the weak-cache RuntimeError.
            raise TimeZoneInvalid(self.msg or "expected an IANA time zone") from exc
