"""Tests for the date and datetime validators."""

from __future__ import annotations

import datetime
import zoneinfo

import pytest

from probatio import (
    AsDate,
    AsDatetime,
    AsTime,
    AsTimedelta,
    AsTimezone,
    Coerce,
    Date,
    Datetime,
    Duration,
    FromEpoch,
    MultipleInvalid,
    Schema,
    Time,
    TimeZone,
    TimeZoneInfo,
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


def test_as_validators_pass_a_native_object_through() -> None:
    """A native datetime/date/time is returned as-is (a YAML/TOML loader produces one)."""
    dt = datetime.datetime(2020, 1, 2, 3, 4)
    day = datetime.date(2020, 1, 2)
    clock = datetime.time(3, 4)

    assert Schema(AsDatetime())(dt) is dt
    assert Schema(AsDate())(day) is day
    assert Schema(AsTime())(clock) is clock


def test_asdate_rejects_a_datetime() -> None:
    """A datetime carries a time, so a date field rejects it rather than truncating."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(AsDate())(datetime.datetime(2020, 1, 2, 3, 4))
    assert isinstance(caught.value.errors[0], DateInvalid)


def test_asdatetime_require_timezone_applies_to_a_native_object() -> None:
    """require_timezone still holds on the pass-through path: aware passes, naive rejects."""
    aware = datetime.datetime(2020, 1, 2, 3, 4, tzinfo=datetime.UTC)
    assert Schema(AsDatetime(require_timezone=True))(aware) is aware

    with pytest.raises(MultipleInvalid) as caught:
        Schema(AsDatetime(require_timezone=True))(datetime.datetime(2020, 1, 2, 3, 4))
    assert isinstance(caught.value.errors[0], DatetimeInvalid)


def test_astimedelta_passes_through_a_timedelta() -> None:
    """An existing timedelta is returned unchanged."""
    delta = datetime.timedelta(minutes=5)
    assert Schema(AsTimedelta())(delta) == delta


def test_astimedelta_from_seconds() -> None:
    """A number is read as a count of seconds."""
    assert Schema(AsTimedelta())(90) == datetime.timedelta(seconds=90)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1:30:00", datetime.timedelta(hours=1, minutes=30)),
        ("0:45", datetime.timedelta(minutes=45)),
        ("-0:30", -datetime.timedelta(minutes=30)),
        # The hour field is a duration, not a clock, so it runs past 24.
        ("100:30", datetime.timedelta(hours=100, minutes=30)),
    ],
)
def test_astimedelta_from_colon_string(
    value: str,
    expected: datetime.timedelta,
) -> None:
    """A colon string parses into the right timedelta, sign included."""
    assert Schema(AsTimedelta())(value) == expected


def test_astimedelta_from_mapping() -> None:
    """A mapping of timedelta kwargs builds the duration."""
    assert Schema(AsTimedelta())({"hours": 1, "minutes": 30}) == datetime.timedelta(
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
def test_astimedelta_from_numeric_string(
    value: str,
    expected: datetime.timedelta,
) -> None:
    """A bare numeric string is read as seconds, like an int or float."""
    assert Schema(AsTimedelta())(value) == expected


def test_astimedelta_numeric_string_matches_int() -> None:
    """The numeric string "90" gives the same result as the int 90."""
    assert Schema(AsTimedelta())("90") == Schema(AsTimedelta())(90)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("P1DT2H30M", datetime.timedelta(days=1, hours=2, minutes=30)),
        ("PT30M", datetime.timedelta(minutes=30)),
        ("PT45S", datetime.timedelta(seconds=45)),
        ("P3D", datetime.timedelta(days=3)),
        ("P1W", datetime.timedelta(weeks=1)),
        ("P2W3DT4H", datetime.timedelta(weeks=2, days=3, hours=4)),
        ("PT1H30M45S", datetime.timedelta(hours=1, minutes=30, seconds=45)),
        ("PT0S", datetime.timedelta(0)),
        ("-P3D", -datetime.timedelta(days=3)),
        ("+PT1H", datetime.timedelta(hours=1)),
        # A fractional field, with either decimal separator ISO 8601 allows.
        ("PT0.5S", datetime.timedelta(seconds=0.5)),
        ("PT1,5S", datetime.timedelta(seconds=1.5)),
        (" P1D ", datetime.timedelta(days=1)),
    ],
)
def test_astimedelta_from_iso8601(value: str, expected: datetime.timedelta) -> None:
    """An ISO 8601 duration parses into the right timedelta, sign included."""
    assert Schema(AsTimedelta())(value) == expected


_INVALID_DURATIONS = [
    True,
    "x:y",
    "nonsense",
    "",
    {"bogus": 1},
    [1],
    "1:99",  # 99 minutes is out of the 0..59 clock range
    "0:60",  # 60 minutes is out of range
    "1:00:99",  # 99 seconds is out of range
    "1:²",  # a superscript digit: str.isdigit() admits it, int() does not
    "1:2:³",
    "²:00",
    "P",  # a bare designator carries no fields
    "PT",  # a time separator with no time field
    "P1DT",  # a dangling time separator
    "P1Y",  # a year is not a fixed length
    "P1M",  # a month is not a fixed length
    "P1YT1H",  # a year, even alongside a valid field
    "PT1H1D",  # a date field after the time separator
    "PX",  # junk after the designator
]
_OVERFLOW_DURATIONS = [
    10**20,
    "100000000000000:0:0",
    "inf",
    "1e400",
    {"days": 10**20},
    "P999999999999999999W",  # an ISO 8601 duration past timedelta's range
    "9" * 5000 + ":00",  # decimal digits, but past int()'s string-length limit
]


@pytest.mark.parametrize("value", _INVALID_DURATIONS)
def test_astimedelta_rejects_invalid(value: object) -> None:
    """A bool, a malformed/empty string, bad mapping keys, or a wrong type reject."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(AsTimedelta())(value)
    assert isinstance(caught.value.errors[0], DurationInvalid)


@pytest.mark.parametrize("value", _OVERFLOW_DURATIONS)
def test_astimedelta_rejects_overflow(value: object) -> None:
    """A duration too large for timedelta is rejected, not a leaked OverflowError."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(AsTimedelta())(value)
    assert isinstance(caught.value.errors[0], DurationInvalid)


@pytest.mark.parametrize(
    "value",
    ["1:30:00", "0:45", "90", "P1DT2H", datetime.timedelta(minutes=5)],
)
def test_duration_validates_and_returns_unchanged(value: object) -> None:
    """Duration validates a duration and returns the value as given (AsTimedelta parses)."""
    assert Schema(Duration())(value) == value


def test_duration_object_via_astimedelta() -> None:
    """The parsed timedelta is opt-in through AsTimedelta, not the Duration validator."""
    assert Schema(AsTimedelta())("1:30:00") == datetime.timedelta(hours=1, minutes=30)


@pytest.mark.parametrize("value", [*_INVALID_DURATIONS, *_OVERFLOW_DURATIONS])
def test_duration_rejects_invalid(value: object) -> None:
    """Duration rejects the same values AsTimedelta rejects, since it validates by it."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(Duration())(value)
    assert isinstance(caught.value.errors[0], DurationInvalid)


def test_timezoneinfo_validates_a_name() -> None:
    """TimeZoneInfo validates an IANA name and returns it unchanged (Coerce for object)."""
    assert Schema(TimeZoneInfo())("Europe/Amsterdam") == "Europe/Amsterdam"


def test_timezoneinfo_passes_through_a_zoneinfo() -> None:
    """An already-resolved ZoneInfo passes through, so validation is idempotent."""
    zone = zoneinfo.ZoneInfo("Europe/Amsterdam")
    assert Schema(TimeZoneInfo())(zone) is zone


def test_timezoneinfo_object_via_coerce() -> None:
    """The parsed ZoneInfo is opt-in through Coerce, not the validator."""
    result = Schema(Coerce(zoneinfo.ZoneInfo))("Europe/Amsterdam")
    assert result == zoneinfo.ZoneInfo("Europe/Amsterdam")


@pytest.mark.parametrize("value", ["Mars/Phobos", 5])
def test_timezoneinfo_rejects_invalid(value: object) -> None:
    """An unknown zone or a non-string raises TimeZoneInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(TimeZoneInfo())(value)
    assert isinstance(caught.value.errors[0], TimeZoneInvalid)


@pytest.mark.parametrize(
    ("value", "offset_hours"),
    [("+01:00", 1), ("-0530", -5.5), ("Z", 0), ("UTC", 0), ("+00:00", 0)],
)
def test_astimezone_parses_a_fixed_offset(value: str, offset_hours: float) -> None:
    """AsTimezone returns a datetime.timezone for a fixed UTC offset, Z, or UTC."""
    result = Schema(AsTimezone())(value)
    assert isinstance(result, datetime.timezone)
    assert result.utcoffset(None) == datetime.timedelta(hours=offset_hours)


def test_astimezone_passes_through_a_native_timezone() -> None:
    """An existing datetime.timezone passes through unchanged."""
    tz = datetime.timezone(datetime.timedelta(hours=2))
    assert Schema(AsTimezone())(tz) is tz


_INVALID_OFFSETS = ["Europe/Amsterdam", "noon", "", "+25:00", 5]


@pytest.mark.parametrize("value", _INVALID_OFFSETS)
def test_astimezone_rejects_a_non_offset(value: object) -> None:
    """A named zone, junk, an empty string, or an out-of-range offset is rejected."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(AsTimezone())(value)
    assert isinstance(caught.value.errors[0], TimeZoneInvalid)


@pytest.mark.parametrize(
    "value",
    ["+01:00", "-0530", "Z", "UTC", datetime.timezone(datetime.timedelta(hours=2))],
)
def test_timezone_validates_and_returns_unchanged(value: object) -> None:
    """TimeZone validates an offset and returns it unchanged (AsTimezone for object)."""
    assert Schema(TimeZone())(value) == value


@pytest.mark.parametrize("value", _INVALID_OFFSETS)
def test_timezone_rejects_a_non_offset(value: object) -> None:
    """TimeZone rejects the same values AsTimezone rejects, since it validates by it."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(TimeZone())(value)
    assert isinstance(caught.value.errors[0], TimeZoneInvalid)


def test_epoch_seconds_returns_aware_utc_datetime() -> None:
    """FromEpoch reads a seconds count into a timezone-aware UTC datetime."""
    result = Schema(FromEpoch())(1719571800)
    assert result == datetime.datetime(2024, 6, 28, 10, 50, tzinfo=datetime.UTC)
    assert result.tzinfo is datetime.UTC


def test_epoch_milliseconds_unit() -> None:
    """With unit=milliseconds, the count is read as milliseconds since the epoch."""
    result = Schema(FromEpoch(unit="milliseconds"))(1719571800000)
    assert result == datetime.datetime(2024, 6, 28, 10, 50, tzinfo=datetime.UTC)


def test_epoch_accepts_a_float() -> None:
    """A float epoch keeps sub-second precision."""
    result = Schema(FromEpoch())(1719571800.5)
    assert result.microsecond == 500000


@pytest.mark.parametrize(
    "value", [True, "1719571800", float("nan"), float("inf"), 10**30]
)
def test_epoch_rejects_bad_values(value: object) -> None:
    """A bool, a string, NaN, infinity, or an out-of-range value raises EpochInvalid."""
    with pytest.raises(MultipleInvalid) as caught:
        Schema(FromEpoch())(value)
    assert isinstance(caught.value.errors[0], EpochInvalid)


def test_epoch_rejects_an_unknown_unit_at_construction() -> None:
    """An unsupported unit is a schema error, raised when the validator is built."""
    with pytest.raises(SchemaError):
        FromEpoch(unit="nanoseconds")


def test_epoch_repr() -> None:
    """FromEpoch renders as a constructor call showing its unit."""
    assert repr(FromEpoch()) == "FromEpoch(unit=seconds)"
    assert repr(FromEpoch(unit="milliseconds")) == "FromEpoch(unit=milliseconds)"
