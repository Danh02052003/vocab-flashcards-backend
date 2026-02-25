from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings


def _load_zone():
    tz_name = get_settings().tz
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")


LOCAL_TZ = _load_zone()


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def day_bounds(target: datetime) -> tuple[datetime, datetime]:
    start = datetime.combine(target.date(), time.min, tzinfo=LOCAL_TZ)
    end = start + timedelta(days=1)
    return start, end


def today_bounds() -> tuple[datetime, datetime]:
    return day_bounds(now_local())


def yesterday_bounds() -> tuple[datetime, datetime]:
    return day_bounds(now_local() - timedelta(days=1))
