"""Shared check-in status definitions for every execution environment."""

from enum import Enum, IntEnum


class VacationStatus(Enum):
    NO_ACTIVE_LEAVE = "no_active_leave"
    ACTIVE_LEAVE = "active_leave"
    UNKNOWN = "unknown"


class CheckinStatus(IntEnum):
    NO_TASK = 0
    SUCCESS = 1
    ALREADY_CHECKED_IN = 2
    LOGIN_FAILED = 3
    DATA_ERROR = 4
    ON_LEAVE = 5
    PROBE_PENDING = 6


STATUS_MESSAGES = {
    CheckinStatus.NO_TASK: "今日无签到记录",
    CheckinStatus.SUCCESS: "签到成功",
    CheckinStatus.ALREADY_CHECKED_IN: "已签到",
    CheckinStatus.LOGIN_FAILED: "登录失败",
    CheckinStatus.DATA_ERROR: "网络错误或数据异常",
    CheckinStatus.ON_LEAVE: "请假期间无需签到",
    CheckinStatus.PROBE_PENDING: "检测到待签到任务（未提交）",
}

SUCCESSFUL_CHECKIN_STATUSES = frozenset(
    {CheckinStatus.SUCCESS, CheckinStatus.ALREADY_CHECKED_IN, CheckinStatus.ON_LEAVE}
)
SUCCESSFUL_PROBE_STATUSES = frozenset(
    {
        CheckinStatus.NO_TASK,
        CheckinStatus.ALREADY_CHECKED_IN,
        CheckinStatus.ON_LEAVE,
        CheckinStatus.PROBE_PENDING,
    }
)
RETRYABLE_STATUSES = frozenset({CheckinStatus.NO_TASK, CheckinStatus.LOGIN_FAILED, CheckinStatus.DATA_ERROR})


def status_message(status: CheckinStatus | int) -> str:
    try:
        normalized = CheckinStatus(status)
    except (TypeError, ValueError):
        return "未知状态"
    return STATUS_MESSAGES[normalized]


def is_successful_checkin_status(status: object) -> bool:
    if not isinstance(status, int):
        return False
    try:
        return CheckinStatus(status) in SUCCESSFUL_CHECKIN_STATUSES
    except (TypeError, ValueError):
        return False
