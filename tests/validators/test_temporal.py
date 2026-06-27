"""Tests for the date and datetime validators."""

from __future__ import annotations

import datetime
import zoneinfo

import pytest

from probatio import Date, Datetime, Duration, MultipleInvalid, Schema, Time, TimeZone
from probatio.error import (
    DateInvalid,
    DatetimeInvalid,
    DurationInvalid,
    TimeInvalid,
    TimeZoneInvalid,
)


def test_datetime_default_format() -> None:
    """Datetime accepts the default ISO-style format and rejects others."""
    schema = Schema(Datetime())
    assert schema("2026-06-25T12:30:00.000000Z") == "2026-06-25T12:30:00.000000Z"
    with pytest.raises(MultipleInvalid) as caught:
        schema("not a datetime")
    assert isinstance(caught.value.errors[0], DatetimeInvalid)


def test_datetime_custom_format_exposed() -> None:
    """A custom format is honored and readable as .format."""
    schema = Schema(Datetime(format="%Y/%m/%d %H:%M"))
    assert Datetime(format="%Y/%m/%d %H:%M").format == "%Y/%m/%d %H:%M"
    assert schema("2026/06/25 12:30") == "2026/06/25 12:30"


def test_date_format() -> None:
    """Date accepts the default date format and rejects bad values."""
    schema = Schema(Date())
    assert schema("2026-06-25") == "2026-06-25"
    with pytest.raises(MultipleInvalid) as caught:
        schema("2026-13-99")
    assert isinstance(caught.value.errors[0], DateInvalid)


def test_datetime_on_non_string() -> None:
    """A non-string is rejected cleanly, not with a TypeError."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Datetime())(12345)
    assert isinstance(caught.value.errors[0], DatetimeInvalid)


def test_time_default_and_custom_format() -> None:
    """Time validates a time-of-day string, defaulting to %H:%M:%S."""
    assert Schema(Time())("14:30:00") == "14:30:00"
    assert Schema(Time(format="%H:%M"))("14:30") == "14:30"


def test_time_rejects_a_bad_value() -> None:
    """A non-time value raises TimeInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Time())("25:99:99")
    assert isinstance(caught.value.errors[0], TimeInvalid)


def test_duration_passes_through_a_timedelta() -> None:
    """An existing timedelta is returned unchanged."""
    delta = datetime.timedelta(minutes=5)
    assert Schema(Duration())(delta) == delta


def test_duration_from_seconds() -> None:
    """A number is read as a count of seconds."""
    assert Schema(Duration())(90) == datetime.timedelta(seconds=90)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1:30:00", datetime.timedelta(hours=1, minutes=30)),
        ("0:45", datetime.timedelta(minutes=45)),
        ("-0:30", -datetime.timedelta(minutes=30)),
    ],
)
def test_duration_from_colon_string(value: str, expected: datetime.timedelta) -> None:
    """A colon string parses into the right timedelta, sign included."""
    assert Schema(Duration())(value) == expected


def test_duration_from_mapping() -> None:
    """A mapping of timedelta kwargs builds the duration."""
    assert Schema(Duration())({"hours": 1, "minutes": 30}) == datetime.timedelta(
        hours=1,
        minutes=30,
    )


@pytest.mark.parametrize("value", [True, "x:y", "nonsense", {"bogus": 1}, [1]])
def test_duration_rejects_invalid(value: object) -> None:
    """A bool, a malformed string, bad mapping keys, or a wrong type all reject."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Duration())(value)
    assert isinstance(caught.value.errors[0], DurationInvalid)


@pytest.mark.parametrize(
    "value",
    [10**20, "100000000000000:0:0", {"days": 10**20}],
)
def test_duration_rejects_overflow(value: object) -> None:
    """A duration too large for timedelta is rejected, not a leaked OverflowError."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Duration())(value)
    assert isinstance(caught.value.errors[0], DurationInvalid)


def test_timezone_resolves_an_iana_name() -> None:
    """TimeZone returns a zoneinfo.ZoneInfo for a valid name."""
    assert Schema(TimeZone())("Europe/Amsterdam") == zoneinfo.ZoneInfo(
        "Europe/Amsterdam",
    )


def test_timezone_passes_through_a_zoneinfo() -> None:
    """An already-resolved ZoneInfo passes through, so validation is idempotent."""
    zone = zoneinfo.ZoneInfo("Europe/Amsterdam")
    assert Schema(TimeZone())(zone) is zone


@pytest.mark.parametrize("value", ["Mars/Phobos", 5])
def test_timezone_rejects_invalid(value: object) -> None:
    """An unknown zone or a non-string raises TimeZoneInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(TimeZone())(value)
    assert isinstance(caught.value.errors[0], TimeZoneInvalid)
