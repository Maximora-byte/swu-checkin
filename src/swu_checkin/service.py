"""Check-in policy, orchestration, retry, and result construction."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import requests

from .cache import CheckinContext
from .client import SwuClient
from .get_info import get_token
from .models import CheckinResult
from .status import RETRYABLE_STATUSES, CheckinStatus, VacationStatus, status_message
from .time_utils import epoch_milliseconds, now_shanghai, parse_swu_datetime, today_shanghai

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_DELAY = 8
SUCCESS_CODES = {"0", "200", "20000", "00000", "success", "ok", "true"}
CURRENT_LOCATION_FIELDS = frozenset({"address", "latitude", "longitude", "qdbj"})
EXPECTED_DATA_ERRORS = (
    requests.exceptions.RequestException,
    json.JSONDecodeError,
    KeyError,
    ValueError,
    TypeError,
)


class DormitorySchemaError(ValueError):
    """The dormitory response cannot be interpreted without ambiguity."""


def evaluate_vacation_records(
    records: list[dict[str, Any] | object],
    *,
    now: datetime | None = None,
) -> VacationStatus:
    """Evaluate approved leave records and fail closed on malformed data."""

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
                raise ValueError("leave time is not a string")
            start = parse_swu_datetime(start_raw)
            end = parse_swu_datetime(end_raw)
            if end < start:
                raise ValueError("leave end precedes start")
        except (KeyError, TypeError, ValueError):
            malformed_record = True
            continue
        if start <= current.astimezone(start.tzinfo) <= end:
            return VacationStatus.ACTIVE_LEAVE
    return VacationStatus.UNKNOWN if malformed_record else VacationStatus.NO_ACTIVE_LEAVE


def parse_coordinate(value: object, *, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} is not a valid coordinate")
    try:
        coordinate = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} is not a valid coordinate") from error
    if not math.isfinite(coordinate) or not minimum <= coordinate <= maximum:
        raise ValueError(f"{name} is outside the valid range")
    return coordinate


def parse_dormitory_data(dormitory_list: list[dict[str, object]]) -> tuple[dict[str, float], str, str]:
    location_candidates: list[dict[str, object]] = []
    building = None
    room = None
    for item in dormitory_list:
        if not isinstance(item, dict):
            continue
        prop = item.get("prop", "")
        if prop == "qddz":
            location_candidates.append(item)
        elif "prop" not in item and CURRENT_LOCATION_FIELDS.issubset(item):
            location_candidates.append(item)
        elif prop == "qsqddd":
            building = item.get("value")
        elif prop == "qdbj":
            room = item.get("value")
    if (
        len(location_candidates) != 1
        or not isinstance(building, str)
        or not building.strip()
        or not isinstance(room, str)
        or not room.strip()
    ):
        raise DormitorySchemaError("dormitory response has an invalid or ambiguous schema")
    location = location_candidates[0]
    try:
        coordinates = {
            "latitude": parse_coordinate(location.get("latitude"), name="latitude", minimum=-90, maximum=90),
            "longitude": parse_coordinate(location.get("longitude"), name="longitude", minimum=-180, maximum=180),
        }
    except ValueError as error:
        raise DormitorySchemaError(str(error)) from error
    return coordinates, building.strip(), room.strip()


def business_response_succeeded(payload: object) -> bool:
    """Return true only when the response contains an explicit success signal."""

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


def build_checkin_payload(ctx: CheckinContext) -> dict[str, Any]:
    """Build the existing check-in payload without changing any field semantics."""

    return {
        "id": ctx.transition["id"],
        "formId": ctx.transition["formId"],
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


class CheckinService:
    """Business orchestration over an authenticated SWU client."""

    def __init__(
        self,
        *,
        timeout: int = 10,
        token_provider: Callable[[str, str, int], str] | None = None,
        client_factory: Callable[[str, int], SwuClient] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.perf_counter,
        diagnostic: Callable[[str], None] = print,
    ):
        self.timeout = timeout
        self._token_provider = token_provider or get_token
        self._client_factory = client_factory or (lambda token, timeout: SwuClient(token, timeout))
        self._sleep = sleep
        self._clock = clock
        self._diagnostic = diagnostic

    def _authenticated_client(self, username: str, password: str) -> SwuClient | None:
        token = self._token_provider(username, password, self.timeout)
        return self._client_factory(token, self.timeout) if token else None

    def _prepare_context(self, client: SwuClient, ctx: CheckinContext) -> None:
        if not ctx.has_dormitory_info():
            dormitory = client.get_dormitory()
            data = dormitory.get("data")
            if not isinstance(data, dict):
                raise DormitorySchemaError("dormitory response is missing data")
            column_list = data.get("columnList")
            if not isinstance(column_list, list):
                raise DormitorySchemaError("dormitory columns are invalid")
            location, building, room = parse_dormitory_data(column_list)
            ctx.dormitory_data = dormitory
            ctx.building = building
            ctx.room = room
            ctx.latitude = location["latitude"]
            ctx.longitude = location["longitude"]
        if not ctx.has_student_id():
            ctx.student_id = client.get_student_id()

    def _confirm_checkin(self, client: SwuClient) -> bool:
        for delay in (0, 0.3, 0.6, 1.0):
            if delay:
                self._sleep(delay)
            try:
                transition = client.get_transition_today()
            except EXPECTED_DATA_ERRORS:
                continue
            if transition and transition.get("qdzt") == "已签到":
                return True
        return False

    def _submit_checkin(self, client: SwuClient, ctx: CheckinContext) -> CheckinStatus:
        self._prepare_context(client, ctx)
        payload = build_checkin_payload(ctx)
        response_payload = client.submit_checkin_form(form_id=ctx.transition["formId"], payload=payload)
        business_success = business_response_succeeded(response_payload)
        if self._confirm_checkin(client):
            return CheckinStatus.SUCCESS
        if business_success:
            self._diagnostic("签到请求已提交，但未能确认服务端签到状态")
        else:
            self._diagnostic("签到接口未返回明确成功状态，且服务端状态未变更")
        return CheckinStatus.DATA_ERROR

    def _common_status(
        self, username: str, password: str
    ) -> tuple[CheckinStatus | None, SwuClient | None, dict | None]:
        client = self._authenticated_client(username, password)
        if client is None:
            return CheckinStatus.LOGIN_FAILED, None, None
        vacation_status = evaluate_vacation_records(client.get_leave_records())
        if vacation_status is VacationStatus.UNKNOWN:
            return CheckinStatus.DATA_ERROR, client, None
        if vacation_status is VacationStatus.ACTIVE_LEAVE:
            return CheckinStatus.ON_LEAVE, client, None
        transition = client.get_transition_today()
        if not transition:
            return CheckinStatus.NO_TASK, client, None
        if transition.get("qdzt") == "已签到":
            return CheckinStatus.ALREADY_CHECKED_IN, client, transition
        return None, client, transition

    def check_in_once(self, username: str, password: str) -> CheckinStatus:
        try:
            status, client, transition = self._common_status(username, password)
            if status is not None:
                return status
            ctx = CheckinContext(transition=transition)
            return self._submit_checkin(client, ctx)
        except (KeyboardInterrupt, SystemExit):
            raise
        except DormitorySchemaError:
            self._diagnostic("宿舍数据结构异常")
            return CheckinStatus.DATA_ERROR
        except EXPECTED_DATA_ERRORS:
            return CheckinStatus.DATA_ERROR

    def probe_once(self, username: str, password: str) -> CheckinStatus:
        try:
            status, client, transition = self._common_status(username, password)
            if status is not None:
                return status
            self._prepare_context(client, CheckinContext(transition=transition))
            return CheckinStatus.PROBE_PENDING
        except (KeyboardInterrupt, SystemExit):
            raise
        except DormitorySchemaError:
            self._diagnostic("宿舍数据结构异常")
            return CheckinStatus.DATA_ERROR
        except EXPECTED_DATA_ERRORS:
            return CheckinStatus.DATA_ERROR

    def run_checkin(
        self,
        username: str,
        password: str,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_delay: int = DEFAULT_RETRY_DELAY,
    ) -> CheckinResult:
        started = self._clock()
        last_status = CheckinStatus.DATA_ERROR
        completed_attempts = 0
        for attempt in range(1, max_attempts + 1):
            completed_attempts = attempt
            last_status = self.check_in_once(username, password)
            if last_status not in RETRYABLE_STATUSES or attempt >= max_attempts:
                break
            wait = retry_delay * (2 ** (attempt - 1))
            self._diagnostic(f"第 {attempt}/{max_attempts} 次失败（{status_message(last_status)}），{wait} 秒后重试")
            self._sleep(wait)
        duration_ms = max(0, int((self._clock() - started) * 1000))
        return CheckinResult.from_status(
            last_status,
            attempts=completed_attempts,
            duration_ms=duration_ms,
            mode="checkin",
        )

    def run_probe(self, username: str, password: str) -> CheckinResult:
        started = self._clock()
        status = self.probe_once(username, password)
        duration_ms = max(0, int((self._clock() - started) * 1000))
        return CheckinResult.from_status(status, attempts=1, duration_ms=duration_ms, mode="probe")


def run_checkin(
    username: str,
    password: str,
    timeout: int = 10,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_delay: int = DEFAULT_RETRY_DELAY,
    **service_options: Any,
) -> CheckinResult:
    return CheckinService(timeout=timeout, **service_options).run_checkin(
        username,
        password,
        max_attempts=max_attempts,
        retry_delay=retry_delay,
    )


def run_probe(username: str, password: str, timeout: int = 10, **service_options: Any) -> CheckinResult:
    return CheckinService(timeout=timeout, **service_options).run_probe(username, password)
