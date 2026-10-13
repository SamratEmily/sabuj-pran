from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings


def business_tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def today() -> date:
    """Business "today" in the configured time zone (Asia/Dhaka)."""
    return datetime.now(business_tz()).date()


def local_day_start_utc(day: date) -> datetime:
    """Naive UTC datetime of local midnight at the start of `day`."""
    local = datetime.combine(day, time.min, tzinfo=business_tz())
    return local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def local_day_end_utc(day: date) -> datetime:
    """Naive UTC datetime of local midnight at the end of `day` (exclusive bound)."""
    return local_day_start_utc(day + timedelta(days=1))
