from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.core.timezone import (
    get_timezone,
    next_local_midnight_utc,
    now_utc,
    to_local,
    to_utc,
)


def test_now_utc():
    now = now_utc()
    assert now.tzinfo is not None
    assert now.tzinfo == timezone.utc


def test_to_local_tehran():
    # 12:00:00 UTC should be 15:30:00 in Asia/Tehran (UTC+03:30)
    utc_dt = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)
    local_dt = to_local(utc_dt, "Asia/Tehran")
    assert local_dt.hour == 15
    assert local_dt.minute == 30
    assert local_dt.tzinfo == ZoneInfo("Asia/Tehran")


def test_to_utc():
    tehran_dt = datetime(2026, 11, 14, 15, 30, 0, tzinfo=ZoneInfo("Asia/Tehran"))
    utc_dt = to_utc(tehran_dt)
    assert utc_dt.hour == 12
    assert utc_dt.minute == 0
    assert utc_dt.tzinfo == timezone.utc


def test_next_local_midnight_utc():
    # For calendar date 2026-11-14 in Asia/Tehran:
    # Next local midnight is 2026-11-15 00:00:00 Tehran time (UTC+03:30).
    # In UTC, this is 2026-11-14 20:30:00.
    target_date = date(2026, 11, 14)
    deadline_utc = next_local_midnight_utc(target_date, "Asia/Tehran")
    assert deadline_utc == datetime(2026, 11, 14, 20, 30, 0, tzinfo=timezone.utc)

