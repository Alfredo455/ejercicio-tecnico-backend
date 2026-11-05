import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.ingestion.csv_reader import InvalidFile, parse_csv
from app.ingestion.validation import RejectReason

HEADER = b"device_id,recorded_at,value,lat,lon\n"
KEY = ("D-0001", datetime(2026, 9, 4, 4, 0, tzinfo=UTC))


def test_lowest_row_wins_inside_a_file_across_formats():
    parsed = parse_csv(
        HEADER
        + b"D-0001,2026-09-04T04:00:00Z,1,-33.4,-70.6\n"
        + b" d-0001 ,2026-09-04T00:00:00.000-04:00,2,-33.5,-70.7\n",
        "a.csv",
    )

    assert parsed.rows_read == 2
    assert parsed.rows_valid == 2
    assert len(parsed.readings) == 1
    assert parsed.readings[KEY].reading.value == Decimal("2")
    assert parsed.readings[KEY].source_line == 3


def test_invalid_lower_row_does_not_replace_the_valid_one():
    parsed = parse_csv(
        HEADER + b"D-0001,2026-09-04T04:00:00Z,1,,\n" + b"D-0001,2026-09-04T04:00:00Z,abc,,\n",
        "a.csv",
    )

    assert parsed.readings[KEY].reading.value == Decimal("1")
    assert parsed.rejections == {RejectReason.INVALID_VALUE: 1}


def test_counters_add_up_by_reason():
    parsed = parse_csv(
        HEADER
        + b"D-0001,2026-09-04T04:00:00Z,1,,\n"
        + b",2026-09-04T04:00:00Z,1,,\n"
        + b"D-0001,ayer,1,,\n"
        + b"D-0001,2026-09-04 04:00:00,1,,\n"
        + b"D-0001,2026-09-04T04:00:00Z\n",
        "a.csv",
    )

    assert (parsed.rows_read, parsed.rows_valid, parsed.rows_discarded) == (5, 1, 4)
    assert parsed.rejections == {
        RejectReason.EMPTY_DEVICE_ID: 1,
        RejectReason.INVALID_DATE: 1,
        RejectReason.MISSING_TIMEZONE: 1,
        RejectReason.WRONG_COLUMNS: 1,
    }


def test_hash_comes_from_the_file_bytes():
    content = HEADER + b"D-0001,2026-09-04T04:00:00Z,1,,\n"
    assert parse_csv(content, "a.csv").sha256 == hashlib.sha256(content).hexdigest()


def test_bom_is_tolerated():
    parsed = parse_csv(b"\xef\xbb\xbf" + HEADER + b"D-0001,2026-09-04T04:00:00Z,1,,\n", "a.csv")
    assert parsed.rows_valid == 1


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"device_id,recorded_at,value,lat\n",
        b"\xff\xfeinvalido",
        HEADER + b"D-\x000001,2026-09-04T04:00:00Z,1,,\n",
    ],
)
def test_unreadable_file_is_rejected(content):
    with pytest.raises(InvalidFile):
        parse_csv(content, "a.csv")
