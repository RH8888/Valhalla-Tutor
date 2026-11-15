from datetime import date, datetime, time, timezone
from typing import Optional
from zoneinfo import ZoneInfo
from app.core.config import settings


def get_timezone(tz_name: Optional[str] = None) -> ZoneInfo:
    """Return ZoneInfo instance for given timezone name or default timezone."""
    name = tz_name or settings.DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(settings.DEFAULT_TIMEZONE)


def now_utc() -> datetime:
    """Return current timezone-aware datetime in UTC."""
    return datetime.now(timezone.utc)


def today_local(tz_name: Optional[str] = None) -> date:
    """Return the current date in the target local timezone (default Asia/Tehran)."""
    return to_local(now_utc(), tz_name).date()


def to_local(dt: datetime, tz_name: Optional[str] = None) -> datetime:
    """Convert a UTC or timezone-aware datetime to the target local timezone."""
    tz = get_timezone(tz_name)
    if dt.tzinfo is None:
        # If naive, assume UTC as per system storage standard
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def to_utc(dt: datetime) -> datetime:
    """Convert any timezone-aware datetime to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def next_local_midnight_utc(scheduled_date: date, tz_name: Optional[str] = None) -> datetime:
    """
    Calculate the next local midnight deadline in UTC for a scheduled date.
    Per DATABASE.md: scheduled_date + 1 day at 00:00:00 local time, converted to UTC.
    """
    tz = get_timezone(tz_name)
    next_day = scheduled_date.fromordinal(scheduled_date.toordinal() + 1)
    local_midnight = datetime.combine(next_day, time.min, tzinfo=tz)
    return local_midnight.astimezone(timezone.utc)

