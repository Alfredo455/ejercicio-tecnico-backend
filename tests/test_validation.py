from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.ingestion.validation import (
    InvalidRow,
    RejectReason,
    parse_device_id,
    parse_position,
    parse_recorded_at,
    parse_row,
    parse_value,
)

INSTANT = datetime(2026, 9, 4, 4, 2, 46, tzinfo=UTC)


def make_row(**overrides):
    row = {
        "device_id": "D-0037",
        "recorded_at": "2026-09-04T04:02:46Z",
        "value": "47.77",
        "lat": "-33.425101",
        "lon": "-70.636526",
    }
    return row | overrides


def assert_rejected(reason, function, *args):
    with pytest.raises(InvalidRow) as error:
        function(*args)
    assert error.value.reason is reason


@pytest.mark.parametrize("text", ["D-0037", "d-0037", " D-0037 ", "  d-0037\t"])
def test_device_id_ignores_case_and_surrounding_spaces(text):
    assert parse_device_id(text) == "D-0037"


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_device_id_is_rejected(text):
    assert_rejected(RejectReason.EMPTY_DEVICE_ID, parse_device_id, text)


@pytest.mark.parametrize(
    "text",
    [
        "2026-09-04T04:02:46Z",
        "2026-09-04T04:02:46.000Z",
        "2026-09-04T00:02:46-04:00",
        "2026-09-04T01:02:46-03:00",
        "2026-09-04T06:02:46+02:00",
        " 2026-09-04T04:02:46Z ",
    ],
)
def test_every_format_of_the_same_instant_is_equal(text):
    assert parse_recorded_at(text) == INSTANT


def test_recorded_at_is_normalized_to_utc():
    assert parse_recorded_at("2026-09-04T00:02:46-04:00").utcoffset().total_seconds() == 0


def test_milliseconds_are_kept():
    assert parse_recorded_at("2026-09-04T04:02:46.250Z").microsecond == 250_000


@pytest.mark.parametrize("text", ["2026-09-04 04:02:46", "2026-09-04T04:02:46", "2026-09-04"])
def test_date_without_timezone_is_rejected(text):
    assert_rejected(RejectReason.MISSING_TIMEZONE, parse_recorded_at, text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "ayer",
        "2026-09-31T25:61:00Z",
        "2026-02-30T10:00:00Z",
        "2026-09-04T24:30:00Z",
        "0001-01-01T00:00:00+05:00",
    ],
)
def test_impossible_date_is_rejected(text):
    assert_rejected(RejectReason.INVALID_DATE, parse_recorded_at, text)


@pytest.mark.parametrize("text", ["", "  ", "NaN", "nan", "NAN", " NaN "])
def test_empty_or_nan_value_means_no_data(text):
    assert parse_value(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [("47.77", "47.77"), (" 47.77 ", "47.77"), ("0", "0"), ("-1.5", "-1.5"), ("1e3", "1E+3")],
)
def test_numeric_value_is_kept_exactly(text, expected):
    assert parse_value(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["abc", "12,5", "Infinity", "-Infinity", "sNaN"])
def test_non_numeric_value_is_rejected(text):
    assert_rejected(RejectReason.INVALID_VALUE, parse_value, text)


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        ("-33.425101", "-70.636526"),
        ("0", "-70.636526"),
        ("-33.425101", "0"),
        ("90", "180"),
        ("-90", "-180"),
    ],
)
def test_usable_position_is_kept(lat, lon):
    assert parse_position(lat, lon) == (float(lat), float(lon))


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        ("", ""),
        ("", "-70.6"),
        ("-33.4", ""),
        ("0", "0"),
        ("0.0", "-0.0"),
        ("90.000001", "-70.6"),
        ("-90.000001", "-70.6"),
        ("-33.4", "180.000001"),
        ("-33.4", "-180.000001"),
        ("abc", "-70.6"),
        ("NaN", "-70.6"),
        ("-33.4", "Infinity"),
    ],
)
def test_unusable_position_means_no_position(lat, lon):
    assert parse_position(lat, lon) == (None, None)


def test_row_is_normalized():
    reading = parse_row(make_row(device_id=" d-0037 ", recorded_at="2026-09-04T00:02:46-04:00"))

    assert reading.device_id == "D-0037"
    assert reading.recorded_at == INSTANT
    assert reading.value == Decimal("47.77")
    assert (reading.lat, reading.lon) == (-33.425101, -70.636526)


def test_row_without_value_or_position_is_still_a_reading():
    reading = parse_row(make_row(value="NaN", lat="0", lon="0"))

    assert reading.value is None
    assert (reading.lat, reading.lon) == (None, None)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"device_id": "  "}, RejectReason.EMPTY_DEVICE_ID),
        ({"recorded_at": "ayer"}, RejectReason.INVALID_DATE),
        ({"recorded_at": "2026-09-04 04:02:46"}, RejectReason.MISSING_TIMEZONE),
        ({"value": "abc"}, RejectReason.INVALID_VALUE),
        ({"lon": None}, RejectReason.WRONG_COLUMNS),
        ({None: ["sobrante"]}, RejectReason.WRONG_COLUMNS),
    ],
)
def test_invalid_row_reports_its_reason(overrides, reason):
    assert_rejected(reason, parse_row, make_row() | overrides)
