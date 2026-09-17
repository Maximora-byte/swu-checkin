"""Timezone-aware time helpers used across CLI, services, and tests."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")
SWU_DATETIME_FORMAT = "%Y-%m-%d %H:%M"


def now_shanghai() -> datetime:
    return datetime.now(SHANGHAI_TIMEZONE)


def parse_swu_datetime(value: str) -> datetime:
    return datetime.strptime(value, SWU_DATETIME_FORMAT).replace(tzinfo=SHANGHAI_TIMEZONE)


def today_shanghai() -> str:
    return now_shanghai().date().isoformat()


def epoch_milliseconds() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)
