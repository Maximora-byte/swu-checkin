import json
import math
import os
import tempfile
import time
from datetime import datetime
from getpass import getpass
from pathlib import Path

import requests

from .cache import CheckinContext
from .get_info import get_dormitory, get_student_id, get_token, get_transition_today
from .status import (
    RETRYABLE_STATUSES,
    SUCCESSFUL_CHECKIN_STATUSES,
    SUCCESSFUL_PROBE_STATUSES,
    CheckinStatus,
    VacationStatus,
    is_successful_checkin_status,
    status_message,
)
from .time_utils import epoch_milliseconds, now_shanghai, parse_swu_datetime, today_shanghai

# 终态不重试：成功 / 已签到 / 请假
# 其余（无记录、登录失败、网络异常）可能是抖动，打满次数才算失败
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_DELAY = 8
SUCCESS_CODES = {"0", "200", "20000", "00000", "success", "ok", "true"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _check_vacation_status(
    ctx: CheckinContext,
    timeout: int,
    *,
    now: datetime | None = None,
) -> VacationStatus:
    """Fail closed when the approved-leave state cannot be confirmed."""
    headers = {"fighter-auth-token": ctx.token}
    url = "https://of.swu.edu.cn/gateway/fighter-baida/api/xsqjxj/listSelfLeaveData?pageNum=1&pageSize=10"

    try:
        response = requests.get(url=url, headers=headers, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("请假接口响应不是对象")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("请假接口缺少 data 对象")
        records = data.get("records")
        if not isinstance(records, list):
            raise ValueError("请假接口 records 不是列表")

        if not records:
            return VacationStatus.NO_ACTIVE_LEAVE

        current = now or now_shanghai()
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        malformed_record = False
        for record in records:
            if not isinstance(record, dict):
                malformed_record = True
                continue
            approval_status = record.get("lcztmc")
            if not isinstance(approval_status, str):
                malformed_record = True
                continue
            if approval_status != "已同意":
                continue
            try:
                start_raw = record["kssj"]
                end_raw = record["jssj"]
                if not isinstance(start_raw, str) or not isinstance(end_raw, str):
                    raise ValueError("请假时间不是字符串")
                start = parse_swu_datetime(start_raw)
                end = parse_swu_datetime(end_raw)
                if end < start:
                    raise ValueError("请假结束时间早于开始时间")
            except (KeyError, TypeError, ValueError):
                malformed_record = True
                continue
            if start <= current.astimezone(start.tzinfo) <= end:
                return VacationStatus.ACTIVE_LEAVE

        if malformed_record:
            return VacationStatus.UNKNOWN
        return VacationStatus.NO_ACTIVE_LEAVE
    except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError, ValueError, TypeError):
        return VacationStatus.UNKNOWN


def _parse_coordinate(value: object, *, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不是有效坐标")
    try:
        coordinate = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} 不是有效坐标") from error
    if not math.isfinite(coordinate) or not minimum <= coordinate <= maximum:
        raise ValueError(f"{name} 超出有效范围")
    return coordinate


def _parse_dormitory_data(dormitory_list: list[dict[str, object]]) -> tuple[dict[str, float], str, str]:
    """
    从 getDormitory 返回的 columnList 解析签到数据
    返回: (位置信息, 宿舍楼名, 房间号)
    """
    location = None
    building = None
    room = None

    for item in dormitory_list:
        if not isinstance(item, dict):
            continue
        prop = item.get("prop", "")
        if prop == "qddz":
            location = {"latitude": item.get("latitude"), "longitude": item.get("longitude")}
        elif prop == "qsqddd":
            building = item.get("value")
        elif prop == "qdbj":
            room = item.get("value")

    if (
        not location
        or not isinstance(building, str)
        or not building.strip()
        or not isinstance(room, str)
        or not room.strip()
    ):
        raise ValueError("宿舍信息不完整")

    validated_location = {
        "latitude": _parse_coordinate(location.get("latitude"), name="latitude", minimum=-90, maximum=90),
        "longitude": _parse_coordinate(location.get("longitude"), name="longitude", minimum=-180, maximum=180),
    }
    return validated_location, building.strip(), room.strip()


def _business_response_succeeded(payload: object) -> bool:
    """仅在响应包含明确成功信号时返回 True。"""
    if not isinstance(payload, dict):
        return False

    nested = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    code_value = payload.get("code", payload.get("status", nested.get("code", nested.get("status"))))
    result_value = payload.get(
        "success",
        payload.get("result", payload.get("ok", nested.get("success", nested.get("result", nested.get("ok"))))),
    )

    if code_value is not None and str(code_value).strip().lower() not in SUCCESS_CODES:
        return False
    if result_value is False or result_value == 0:
        return False
    if isinstance(result_value, str) and result_value.strip().lower() in {"false", "0", "fail", "failed", "error"}:
        return False

    return (
        code_value is not None
        or result_value is True
        or result_value == 1
        or (isinstance(result_value, str) and result_value.strip().lower() in {"success", "ok", "true", "1"})
    )


def _confirm_checkin(token: str, timeout: int) -> bool:
    """提交后短暂轮询，确认服务端状态确实变为“已签到”。"""
    for delay in (0, 0.3, 0.6, 1.0):
        if delay:
            time.sleep(delay)
        try:
            transition = get_transition_today(token, timeout)
        except (requests.exceptions.RequestException, KeyError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if transition and transition.get("qdzt") == "已签到":
            return True
    return False


def _submit_checkin(ctx: CheckinContext, timeout: int) -> CheckinStatus:
    """
    执行签到请求（使用上下文中已缓存的数据，避免重复调用）
    返回: 1=成功, 4=网络错误
    """
    try:
        # 从上下文获取已缓存的数据
        form_id = ctx.transition["formId"]
        record_id = ctx.transition["id"]

        # 如果宿舍信息未缓存，则获取
        if not ctx.has_dormitory_info():
            dorm_response = get_dormitory(ctx.token, timeout)
            column_list = dorm_response.get("data", {}).get("columnList", [])
            location, building, room = _parse_dormitory_data(column_list)

            # 缓存到上下文
            ctx.dormitory_data = dorm_response
            ctx.building = building
            ctx.room = room
            ctx.latitude = location["latitude"]
            ctx.longitude = location["longitude"]

        # 如果学号未缓存，则获取
        if not ctx.has_student_id():
            ctx.student_id = get_student_id(ctx.token, timeout)

        headers = {"fighter-auth-token": ctx.token, "Content-Type": "application/json;charset=UTF-8"}
        url = "https://of.swu.edu.cn/gateway/fighter-baida/api/form-instance/save"
        params = {"formId": form_id, "isSubmitProcess": False}

        payload = {
            "id": record_id,
            "formId": form_id,
            "tsrq": today_shanghai(),
            "xh": ctx.student_id,
            "qdsj": ["21:00", "23:30"],
            "qsqddd": ctx.building,
            "qdbj": ctx.room,
            "qddz": {
                "latitude": ctx.latitude,
                "longitude": ctx.longitude,
                "address": ctx.building,
                "netType": "wifi",
                "operatorType": "unknown",
                "imei": "imei",
                "time": epoch_milliseconds(),
                "provider": "lbs",
                "isFromMock": False,
                "isGpsEnabled": True,
                "isWifiEnabled": True,
                "isMobileEnabled": False,
                "isOffset": True,
                "cityAdCode": "023",
                "districtAdCode": "500109",
                "isArea": True,
                "tip": "当前在签到范围内",
            },
        }

        response = requests.post(url, headers=headers, params=params, data=json.dumps(payload), timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        business_success = _business_response_succeeded(payload)
        confirmed = _confirm_checkin(ctx.token, timeout)
        if confirmed:
            return CheckinStatus.SUCCESS
        if business_success:
            print("签到请求已提交，但未能确认服务端签到状态")
        else:
            print("签到接口未返回明确成功状态，且服务端状态未变更")
        return CheckinStatus.DATA_ERROR

    except requests.exceptions.RequestException:
        return CheckinStatus.DATA_ERROR
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return CheckinStatus.DATA_ERROR


def check_in(username: str, password: str, timeout: int = 10) -> CheckinStatus:
    """
    执行一次宿舍签到。

    返回值:
        0: 今日无签到记录
        1: 签到成功
        2: 已签到
        3: 登录失败
        4: 网络错误或数据异常
        5: 请假期间无需签到
    """
    try:
        # 创建会话上下文，避免一次 action 中重复调用
        ctx = CheckinContext()

        # 步骤1: 登录获取 token（只调用一次）
        ctx.token = get_token(username, password, timeout)
        if not ctx.token:
            return CheckinStatus.LOGIN_FAILED

        # 步骤2: 检查请假状态（只调用一次）
        vacation_status = _check_vacation_status(ctx, timeout)
        if vacation_status is VacationStatus.UNKNOWN:
            return CheckinStatus.DATA_ERROR
        if vacation_status is VacationStatus.ACTIVE_LEAVE:
            return CheckinStatus.ON_LEAVE

        # 步骤3: 获取今日签到任务（只调用一次，存入上下文）
        ctx.transition = get_transition_today(ctx.token, timeout)
        if not ctx.transition:
            return CheckinStatus.NO_TASK

        # 步骤4: 检查是否已签到
        if ctx.transition.get("qdzt") == "已签到":
            return CheckinStatus.ALREADY_CHECKED_IN

        # 步骤5: 执行签到（使用上下文中已缓存的数据）
        result = _submit_checkin(ctx, timeout)
        return result

    except (KeyboardInterrupt, SystemExit):
        raise
    except (requests.exceptions.RequestException, KeyError, ValueError, TypeError, json.JSONDecodeError):
        return CheckinStatus.DATA_ERROR


def probe_check_in(username: str, password: str, timeout: int = 10) -> CheckinStatus:
    """只验证登录并读取任务状态，绝不提交签到。"""
    try:
        ctx = CheckinContext()
        ctx.token = get_token(username, password, timeout)
        if not ctx.token:
            return CheckinStatus.LOGIN_FAILED
        vacation_status = _check_vacation_status(ctx, timeout)
        if vacation_status is VacationStatus.UNKNOWN:
            return CheckinStatus.DATA_ERROR
        if vacation_status is VacationStatus.ACTIVE_LEAVE:
            return CheckinStatus.ON_LEAVE
        ctx.transition = get_transition_today(ctx.token, timeout)
        if not ctx.transition:
            return CheckinStatus.NO_TASK
        if ctx.transition.get("qdzt") == "已签到":
            return CheckinStatus.ALREADY_CHECKED_IN
        return CheckinStatus.PROBE_PENDING
    except (KeyboardInterrupt, SystemExit):
        raise
    except (requests.exceptions.RequestException, KeyError, ValueError, TypeError, json.JSONDecodeError):
        return CheckinStatus.DATA_ERROR


def check_in_with_retry(
    username: str,
    password: str,
    timeout: int = 10,
    max_attempts: int | None = None,
    retry_delay: int | None = None,
) -> CheckinStatus:
    """
    执行签到，瞬时失败自动重试。

    可通过环境变量覆盖：
        SWUDK_MAX_ATTEMPTS  总尝试次数，默认 3
        SWUDK_RETRY_DELAY   首次重试等待秒数，之后指数退避，默认 8
    """
    attempts = max_attempts or _env_int("SWUDK_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)
    delay = retry_delay or _env_int("SWUDK_RETRY_DELAY", DEFAULT_RETRY_DELAY)
    last_result = CheckinStatus.DATA_ERROR

    for attempt in range(1, attempts + 1):
        last_result = check_in(username, password, timeout)
        if last_result not in RETRYABLE_STATUSES or attempt >= attempts:
            return last_result

        wait = delay * (2 ** (attempt - 1))
        reason = status_message(last_result)
        print(f"第 {attempt}/{attempts} 次失败（{reason}），{wait} 秒后重试")
        time.sleep(wait)

    return last_result


def _record_run_status(status_path: str, result: CheckinStatus | int) -> None:
    """Record non-sensitive per-day results for the Telegram summary job."""
    path = Path(status_path)
    now = now_shanghai()
    today = now.date().isoformat()
    current: dict = {}
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        pass

    attempts = current.get("attempts", []) if current.get("date") == today else []
    if not isinstance(attempts, list):
        attempts = []
    attempts.append(
        {
            "at": now.isoformat(timespec="seconds"),
            "code": int(result),
            "message": status_message(result),
        }
    )
    attempts = attempts[-10:]
    payload = {
        "date": today,
        "attempts": attempts,
        "successful": any(
            is_successful_checkin_status(attempt.get("code")) for attempt in attempts if isinstance(attempt, dict)
        ),
    }

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".status.", dir=path.parent, text=True)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    username = os.getenv("SWUDK_USERNAME") or input("校园网账号：").strip()
    password = os.getenv("SWUDK_PASSWORD") or getpass("校园网密码：")
    probe_only = os.getenv("SWUDK_PROBE_ONLY") == "1"
    try:
        result = probe_check_in(username, password, 10) if probe_only else check_in_with_retry(username, password, 10)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        result = CheckinStatus.DATA_ERROR
        print(f"未预期错误：{type(error).__name__}")
    print(f"[{int(result)}] {status_message(result)}")
    status_file = os.getenv("SWUDK_STATUS_FILE")
    if status_file and not probe_only:
        try:
            _record_run_status(status_file, result)
        except OSError as error:
            print(f"状态记录失败：{type(error).__name__}")
    successful_results = SUCCESSFUL_PROBE_STATUSES if probe_only else SUCCESSFUL_CHECKIN_STATUSES
    return 0 if result in successful_results else 1


if __name__ == "__main__":
    raise SystemExit(main())
