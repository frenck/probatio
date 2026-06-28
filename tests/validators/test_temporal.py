"""Tests for the date and datetime validators."""

from __future__ import annotations

import datetime
import zoneinfo

import pytest

from probatio import (
    AsDate,
    AsDatetime,
    AsTime,
    Date,
    Datetime,
    Duration,
    Epoch,
    MultipleInvalid,
    Schema,
    Time,
    TimeZone,
)
from probatio.error import (
    DateInvalid,
    DatetimeInvalid,
    DurationInvalid,
    EpochInvalid,
    SchemaError,
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


def test_asdatetime_parses_iso_8601_by_default() -> None:
    """AsDatetime parses ISO 8601 out of the box, offset and all, no format needed."""
    result = Schema(AsDatetime())("2026-06-28T12:30:00+02:00")
    assert result == datetime.datetime(
        2026, 6, 28, 12, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=2))
    )


def test_asdatetime_honors_a_custom_format() -> None:
    """A strptime format overrides the ISO default."""
    result = Schema(AsDatetime(format="%Y-%m-%d %H:%M"))("2026-06-28 12:30")
    assert result == datetime.datetime(2026, 6, 28, 12, 30)


def test_asdatetime_rejects_a_bad_value() -> None:
    """A string that is not a datetime raises DatetimeInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(AsDatetime())("not a datetime")
    assert isinstance(caught.value.errors[0], DatetimeInvalid)


def test_asdatetime_require_timezone_accepts_aware_iso() -> None:
    """With require_timezone, an ISO offset (here Z) yields an aware datetime."""
    result = Schema(AsDatetime(require_timezone=True))("2026-06-28T12:30:00Z")
    assert result.tzinfo is not None


def test_asdatetime_require_timezone_rejects_naive() -> None:
    """With require_timezone, a naive parse is rejected, not returned."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(AsDatetime(require_timezone=True))("2026-06-28T12:30:00")
    assert isinstance(caught.value.errors[0], DatetimeInvalid)


def test_asdate_returns_a_date_object() -> None:
    """AsDate parses ISO 8601 and returns a date, not the string."""
    assert Schema(AsDate())("2026-06-28") == datetime.date(2026, 6, 28)


def test_asdate_honors_a_custom_format() -> None:
    """AsDate honors a strptime format and rejects a value that does not match it."""
    assert Schema(AsDate(format="%d/%m/%Y"))("28/06/2026") == datetime.date(2026, 6, 28)
    with pytest.raises(MultipleInvalid) as caught:
        Schema(AsDate(format="%d/%m/%Y"))("2026-06-28")
    assert isinstance(caught.value.errors[0], DateInvalid)


def test_asdate_rejects_a_bad_value() -> None:
    """A non-date string raises DateInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(AsDate())("2026-13-99")
    assert isinstance(caught.value.errors[0], DateInvalid)


def test_astime_returns_a_time_object() -> None:
    """AsTime parses ISO 8601 and returns a time, not the string."""
    assert Schema(AsTime())("14:30:00") == datetime.time(14, 30)


def test_astime_honors_a_custom_format() -> None:
    """A strptime format overrides the ISO default for AsTime."""
    assert Schema(AsTime(format="%H.%M"))("14.30") == datetime.time(14, 30)


def test_astime_rejects_a_bad_value() -> None:
    """A non-time string raises TimeInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(AsTime())("25:99:99")
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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("90", datetime.timedelta(seconds=90)),
        ("90.5", datetime.timedelta(seconds=90.5)),
        ("-30", -datetime.timedelta(seconds=30)),
        (" 90 ", datetime.timedelta(seconds=90)),
    ],
)
def test_duration_from_numeric_string(value: str, expected: datetime.timedelta) -> None:
    """A bare numeric string is read as seconds, like an int or float."""
    assert Schema(Duration())(value) == expected


def test_duration_numeric_string_matches_int() -> None:
    """The numeric string "90" gives the same result as the int 90."""
    assert Schema(Duration())("90") == Schema(Duration())(90)


@pytest.mark.parametrize("value", [True, "x:y", "nonsense", "", {"bogus": 1}, [1]])
def test_duration_rejects_invalid(value: object) -> None:
    """A bool, a malformed/empty string, bad mapping keys, or a wrong type reject."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Duration())(value)
    assert isinstance(caught.value.errors[0], DurationInvalid)


@pytest.mark.parametrize(
    "value",
    [10**20, "100000000000000:0:0", "inf", "1e400", {"days": 10**20}],
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


def test_epoch_seconds_returns_aware_utc_datetime() -> None:
    """Epoch reads a seconds count into a timezone-aware UTC datetime."""
    result = Schema(Epoch())(1719571800)
    assert result == datetime.datetime(2024, 6, 28, 10, 50, tzinfo=datetime.UTC)
    assert result.tzinfo is datetime.UTC


def test_epoch_milliseconds_unit() -> None:
    """With unit=milliseconds, the count is read as milliseconds since the epoch."""
    result = Schema(Epoch(unit="milliseconds"))(1719571800000)
    assert result == datetime.datetime(2024, 6, 28, 10, 50, tzinfo=datetime.UTC)


def test_epoch_accepts_a_float() -> None:
    """A float epoch keeps sub-second precision."""
    result = Schema(Epoch())(1719571800.5)
    assert result.microsecond == 500000


@pytest.mark.parametrize(
    "value", [True, "1719571800", float("nan"), float("inf"), 10**30]
)
def test_epoch_rejects_bad_values(value: object) -> None:
    """A bool, a string, NaN, infinity, or an out-of-range value raises EpochInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Epoch())(value)
    assert isinstance(caught.value.errors[0], EpochInvalid)


def test_epoch_rejects_an_unknown_unit_at_construction() -> None:
    """An unsupported unit is a schema error, raised when the validator is built."""
    with pytest.raises(SchemaError):
        Epoch(unit="nanoseconds")


def test_epoch_repr() -> None:
    """Epoch renders as a constructor call showing its unit."""
    assert repr(Epoch()) == "Epoch(unit=seconds)"
    assert repr(Epoch(unit="milliseconds")) == "Epoch(unit=milliseconds)"
