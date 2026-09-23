"""Check-in policy, orchestration, retry, and result construction."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict, Unpack, cast

import requests

from .api_models import (
    ApiSchemaError,
    CheckinSubmission,
    DormitoryInfo,
    DormitorySchemaError,
    LeaveRecords,
    StudentProfile,
    Transition,
    parse_coordinate,
)
from .auth import AuthError, AuthFailureReason, auth_failure_status
from .cache import CheckinContext
from .client import SessionExpiredError, SwuClient
from .get_info import authenticate_token
from .models import CheckinResult
from .status import CheckinStatus, VacationStatus, status_message
from .time_utils import epoch_milliseconds, today_shanghai
from .token_store import TokenStore, TokenStoreError, TokenStoreProtocol

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_DELAY = 8
SUCCESS_CODES = {"0", "200", "20000", "00000", "success", "ok", "true"}
EXPECTED_DATA_ERRORS = (
    requests.exceptions.RequestException,
    json.JSONDecodeError,
    KeyError,
    ValueError,
    TypeError,
    ApiSchemaError,
)


class _TokenInvalid(Exception):
    """The validation endpoint explicitly rejected a bearer token."""


@dataclass(frozen=True)
class _AttemptOutcome:
    """Internal single-attempt result with an explicit retry decision."""

    status: CheckinStatus
    retryable: bool


@dataclass(frozen=True)
class _AuthenticatedSession:
    """An authenticated client and whether it came from the token cache."""

    client: SwuClient
    from_cache: bool


@dataclass(frozen=True)
class DoctorReport:
    """Non-sensitive results from read-only SWU diagnostics."""

    authentication: bool
    leave_policy: bool
    student_profile: bool
    dormitory_schema: bool
    checkin_api: bool


def evaluate_vacation_records(
    records: Sequence[object],
    *,
    now: datetime | None = None,
) -> VacationStatus:
    """Evaluate approved leave records and fail closed on malformed data."""

    return LeaveRecords.from_items(records).evaluate(now=now)


def parse_dormitory_data(dormitory_list: list[dict[str, object]]) -> tuple[dict[str, float], str, str]:
    info = DormitoryInfo.from_columns(dormitory_list)
    return {"latitude": info.latitude, "longitude": info.longitude}, info.building, info.room


def parse_dormitory_response(dormitory: object) -> tuple[dict[str, float], str, str]:
    """Validate the response envelope before parsing its non-sensitive schema."""

    info = DormitoryInfo.from_response(dormitory)
    return {"latitude": info.latitude, "longitude": info.longitude}, info.building, info.room


def business_response_succeeded(payload: object) -> bool:
    """Return true only when the response contains an explicit success signal."""

    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        return False
    root = cast("Mapping[str, object]", payload)
    nested_value = root.get("data")
    nested = cast("Mapping[str, object]", nested_value) if isinstance(nested_value, dict) else {}
    code_value = root.get("code", root.get("status", nested.get("code", nested.get("status"))))
    result_value = root.get(
        "success",
        root.get("result", root.get("ok", nested.get("success", nested.get("result", nested.get("ok"))))),
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


def _business_response_diagnostic(payload: object) -> str:
    """Classify a submit response without logging its body or message."""

    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        return "响应结构异常"
    root = cast("Mapping[str, object]", payload)
    nested_value = root.get("data")
    nested = cast("Mapping[str, object]", nested_value) if isinstance(nested_value, dict) else {}
    code_value = root.get("code", root.get("status", nested.get("code", nested.get("status"))))
    if code_value is not None:
        if isinstance(code_value, bool):
            return "业务码类型异常"
        if isinstance(code_value, int):
            normalized = str(code_value)
            return f"业务码={normalized}" if len(normalized) <= 16 else "业务码已返回但不可安全记录"
        if isinstance(code_value, str):
            normalized = code_value.strip()
            if re.fullmatch(r"[A-Za-z0-9_.:-]{1,32}", normalized):
                return f"业务码={normalized}"
        return "业务码已返回但不可安全记录"

    result_value = root.get(
        "success",
        root.get("result", root.get("ok", nested.get("success", nested.get("result", nested.get("ok"))))),
    )
    if result_value is False or result_value == 0:
        return "显式失败标志"
    if isinstance(result_value, str) and result_value.strip().lower() in {"false", "0", "fail", "failed", "error"}:
        return "显式失败标志"
    return "缺少明确业务码或成功标志"


def _request_failure_diagnostic(error: requests.exceptions.RequestException) -> str:
    """Return a fixed, non-sensitive transport failure classification."""

    if isinstance(error, requests.exceptions.HTTPError) and error.response is not None:
        return f"HTTP {error.response.status_code}"
    if isinstance(error, requests.exceptions.Timeout):
        return "请求超时"
    if isinstance(error, requests.exceptions.ConnectionError):
        return "连接异常"
    return "请求异常"


def _build_typed_checkin_payload(submission: CheckinSubmission) -> dict[str, object]:
    """Build the existing check-in payload from validated API models."""

    return {
        "id": submission.transition.record_id,
        "formId": submission.transition.form_id,
        "tsrq": today_shanghai(),
        "xh": submission.student.student_id,
        "qdsj": ["21:00", "23:30"],
        "qsqddd": submission.dormitory.building,
        "qdbj": submission.dormitory.room,
        "qddz": {
            "latitude": submission.dormitory.latitude,
            "longitude": submission.dormitory.longitude,
            "address": submission.dormitory.building,
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


def submission_from_legacy_context(ctx: CheckinContext) -> CheckinSubmission:
    """Validate the historical mutable context before entering the typed core."""

    if ctx.transition is None:
        raise ValueError("transition is missing")
    transition_payload = dict(ctx.transition)
    transition_payload.setdefault("qdzt", "未签到")
    transition = Transition.from_record(transition_payload)
    student = StudentProfile(student_id=ctx.student_id) if isinstance(ctx.student_id, str) else None
    if student is None or not student.student_id:
        raise ValueError("student id is missing")
    if (
        not isinstance(ctx.building, str)
        or not ctx.building.strip()
        or not isinstance(ctx.room, str)
        or not ctx.room.strip()
        or ctx.latitude is None
        or ctx.longitude is None
    ):
        raise ValueError("dormitory data is incomplete")
    dormitory = DormitoryInfo(
        latitude=parse_coordinate(ctx.latitude, name="latitude", minimum=-90, maximum=90),
        longitude=parse_coordinate(ctx.longitude, name="longitude", minimum=-180, maximum=180),
        building=ctx.building.strip(),
        room=ctx.room.strip(),
    )
    return CheckinSubmission(student=student, dormitory=dormitory, transition=transition.require_pending())


def build_checkin_payload(ctx: CheckinContext) -> dict[str, object]:
    """Backward-compatible payload builder over the typed validation layer."""

    return _build_typed_checkin_payload(submission_from_legacy_context(ctx))


class ServiceOptions(TypedDict, total=False):
    token_provider: Callable[[str, str, int], str]
    client_factory: Callable[[str, int], SwuClient]
    sleep: Callable[[float], None]
    clock: Callable[[], float]
    diagnostic: Callable[[str], None]
    token_store: TokenStoreProtocol


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
        token_store: TokenStoreProtocol | None = None,
    ):
        self.timeout = timeout
        self._token_provider = token_provider or authenticate_token
        self._client_factory = client_factory or (lambda token, timeout: SwuClient(token, timeout))
        self._sleep = sleep
        self._clock = clock
        self._diagnostic = diagnostic
        self._token_store = token_store or TokenStore()

    def _delete_cached_token(self, username: str) -> None:
        try:
            self._token_store.delete(username)
        except (OSError, TokenStoreError):
            pass

    @staticmethod
    def _is_transient_request_error(error: requests.exceptions.RequestException) -> bool:
        if isinstance(error, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
            return True
        if isinstance(error, requests.exceptions.HTTPError):
            status_code = error.response.status_code if error.response is not None else None
            return status_code in {408, 425, 429} or (status_code is not None and 500 <= status_code <= 599)
        return False

    @staticmethod
    def _auth_outcome(error: AuthError) -> _AttemptOutcome:
        return _AttemptOutcome(
            status=auth_failure_status(error.reason),
            retryable=error.reason is AuthFailureReason.NETWORK_ERROR,
        )

    @staticmethod
    def _status_outcome(status: CheckinStatus) -> _AttemptOutcome:
        return _AttemptOutcome(status=status, retryable=status is CheckinStatus.NO_TASK)

    def _validate_token(self, token: str) -> tuple[SwuClient, str]:
        client = self._client_factory(token, self.timeout)
        try:
            student_id = client.get_student_id()
        except SessionExpiredError:
            raise _TokenInvalid from None
        except requests.exceptions.HTTPError as error:
            status_code = error.response.status_code if error.response is not None else None
            if status_code in {401, 403}:
                raise _TokenInvalid from None
            reason = (
                AuthFailureReason.NETWORK_ERROR
                if self._is_transient_request_error(error)
                else AuthFailureReason.TOKEN_EXCHANGE_FAILED
            )
            raise AuthError(reason) from None
        except requests.exceptions.RequestException as error:
            reason = (
                AuthFailureReason.NETWORK_ERROR
                if self._is_transient_request_error(error)
                else AuthFailureReason.TOKEN_EXCHANGE_FAILED
            )
            raise AuthError(reason) from None
        except EXPECTED_DATA_ERRORS:
            raise AuthError(AuthFailureReason.TOKEN_EXCHANGE_FAILED) from None
        return client, student_id

    def _authenticated_session(
        self,
        username: str,
        password: str,
        *,
        read_token_cache: bool = True,
        write_token_cache: bool = True,
    ) -> _AuthenticatedSession:
        cached = None
        if read_token_cache:
            try:
                cached = self._token_store.get(username)
            except (OSError, TokenStoreError):
                cached = None
        if cached is not None:
            try:
                client, student_id = self._validate_token(cached.token)
            except _TokenInvalid:
                self._delete_cached_token(username)
            else:
                if student_id == cached.student_id == username:
                    return _AuthenticatedSession(client=client, from_cache=True)
                self._delete_cached_token(username)

        token = self._token_provider(username, password, self.timeout)
        if not token:
            raise AuthError(AuthFailureReason.UNKNOWN)
        try:
            client, student_id = self._validate_token(token)
        except _TokenInvalid:
            raise AuthError(AuthFailureReason.TOKEN_EXCHANGE_FAILED) from None
        if student_id != username:
            raise AuthError(AuthFailureReason.TOKEN_EXCHANGE_FAILED)
        if write_token_cache:
            try:
                self._token_store.save(username, token, student_id)
            except (OSError, TokenStoreError):
                pass
        return _AuthenticatedSession(client=client, from_cache=False)

    def _authenticated_client(
        self,
        username: str,
        password: str,
        *,
        read_token_cache: bool = True,
        write_token_cache: bool = True,
    ) -> SwuClient:
        return self._authenticated_session(
            username,
            password,
            read_token_cache=read_token_cache,
            write_token_cache=write_token_cache,
        ).client

    @staticmethod
    def _prepare_context(client: SwuClient, transition: Transition) -> CheckinSubmission:
        pending = transition.require_pending()
        return CheckinSubmission(
            student=client.get_student_profile(),
            dormitory=client.get_dormitory_info(),
            transition=pending,
        )

    def diagnose(
        self,
        username: str,
        password: str,
        *,
        read_token_cache: bool = False,
        write_token_cache: bool = False,
    ) -> DoctorReport:
        """Run staged read-only diagnostics without reaching the submit endpoint."""

        try:
            client = self._authenticated_client(
                username,
                password,
                read_token_cache=read_token_cache,
                write_token_cache=write_token_cache,
            )
        except (AuthError, *EXPECTED_DATA_ERRORS):
            client = None
        if client is None:
            return DoctorReport(False, False, False, False, False)

        try:
            leave_status = client.get_leave_record_set().evaluate()
            leave_policy = leave_status in {VacationStatus.NO_ACTIVE_LEAVE, VacationStatus.ACTIVE_LEAVE}
        except EXPECTED_DATA_ERRORS:
            leave_policy = False

        try:
            client.get_student_profile()
            student_profile = True
        except EXPECTED_DATA_ERRORS:
            student_profile = False

        try:
            client.get_dormitory_info()
            dormitory_schema = True
        except EXPECTED_DATA_ERRORS:
            dormitory_schema = False

        try:
            client.get_transition()
            checkin_api = True
        except EXPECTED_DATA_ERRORS:
            checkin_api = False

        return DoctorReport(True, leave_policy, student_profile, dormitory_schema, checkin_api)

    def _confirm_checkin(self, client: SwuClient) -> bool:
        for delay in (0, 0.3, 0.6, 1.0):
            if delay:
                self._sleep(delay)
            try:
                transition = client.get_transition()
            except EXPECTED_DATA_ERRORS:
                continue
            if transition and transition.is_checked_in:
                return True
        return False

    def _submit_checkin(self, client: SwuClient, submission: CheckinSubmission) -> CheckinStatus:
        payload = _build_typed_checkin_payload(submission)
        try:
            response_payload = client.submit_checkin_form(form_id=submission.transition.form_id, payload=payload)
        except requests.exceptions.RequestException as error:
            if self._confirm_checkin(client):
                return CheckinStatus.SUCCESS
            classification = _request_failure_diagnostic(error)
            self._diagnostic(f"签到请求结果不明确（{classification}），且未能确认服务端签到状态")
            return CheckinStatus.DATA_ERROR
        business_success = business_response_succeeded(response_payload)
        if self._confirm_checkin(client):
            return CheckinStatus.SUCCESS
        if business_success:
            self._diagnostic("签到请求已提交，但未能确认服务端签到状态")
        else:
            classification = _business_response_diagnostic(response_payload)
            self._diagnostic(f"签到接口未返回明确成功状态（{classification}），且服务端状态未变更")
        return CheckinStatus.DATA_ERROR

    def _prepare_pre_submit_with_client(
        self, client: SwuClient
    ) -> tuple[CheckinStatus | None, SwuClient, CheckinSubmission | None]:
        vacation_status = client.get_leave_record_set().evaluate()
        if vacation_status is VacationStatus.UNKNOWN:
            return CheckinStatus.DATA_ERROR, client, None
        if vacation_status is VacationStatus.ACTIVE_LEAVE:
            return CheckinStatus.ON_LEAVE, client, None
        transition = client.get_transition()
        if not transition:
            return CheckinStatus.NO_TASK, client, None
        if transition.is_checked_in:
            return CheckinStatus.ALREADY_CHECKED_IN, client, None
        return None, client, self._prepare_context(client, transition)

    def _prepare_pre_submit(
        self,
        username: str,
        password: str,
        *,
        allow_cached_session_recovery: bool,
    ) -> tuple[CheckinStatus | None, SwuClient, CheckinSubmission | None]:
        session = self._authenticated_session(username, password)
        try:
            return self._prepare_pre_submit_with_client(session.client)
        except SessionExpiredError:
            if not session.from_cache or not allow_cached_session_recovery:
                raise AuthError(AuthFailureReason.TOKEN_EXCHANGE_FAILED) from None

        self._delete_cached_token(username)
        fresh = self._authenticated_session(username, password, read_token_cache=False)
        try:
            return self._prepare_pre_submit_with_client(fresh.client)
        except SessionExpiredError:
            self._delete_cached_token(username)
            raise AuthError(AuthFailureReason.TOKEN_EXCHANGE_FAILED) from None

    def _check_in_attempt(self, username: str, password: str) -> _AttemptOutcome:
        try:
            status, client, submission = self._prepare_pre_submit(
                username,
                password,
                allow_cached_session_recovery=True,
            )
            if status is not None:
                return self._status_outcome(status)
            if submission is None:
                return _AttemptOutcome(CheckinStatus.DATA_ERROR, retryable=False)
            return self._status_outcome(self._submit_checkin(client, submission))
        except (KeyboardInterrupt, SystemExit):
            raise
        except AuthError as error:
            return self._auth_outcome(error)
        except DormitorySchemaError:
            self._diagnostic("宿舍数据结构异常")
            return _AttemptOutcome(CheckinStatus.DATA_ERROR, retryable=False)
        except requests.exceptions.RequestException as error:
            return _AttemptOutcome(CheckinStatus.DATA_ERROR, retryable=self._is_transient_request_error(error))
        except EXPECTED_DATA_ERRORS:
            return _AttemptOutcome(CheckinStatus.DATA_ERROR, retryable=False)

    def check_in_once(self, username: str, password: str) -> CheckinStatus:
        """Execute one attempt while preserving the historical status-only API."""

        return self._check_in_attempt(username, password).status

    def probe_once(self, username: str, password: str) -> CheckinStatus:
        try:
            status, _client, submission = self._prepare_pre_submit(
                username,
                password,
                allow_cached_session_recovery=False,
            )
            if status is not None:
                return status
            if submission is None:
                return CheckinStatus.DATA_ERROR
            return CheckinStatus.PROBE_PENDING
        except (KeyboardInterrupt, SystemExit):
            raise
        except AuthError as error:
            return auth_failure_status(error.reason)
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
        last_outcome = _AttemptOutcome(CheckinStatus.DATA_ERROR, retryable=False)
        completed_attempts = 0
        for attempt in range(1, max_attempts + 1):
            completed_attempts = attempt
            last_outcome = self._check_in_attempt(username, password)
            if not last_outcome.retryable or attempt >= max_attempts:
                break
            wait = retry_delay * (2 ** (attempt - 1))
            self._diagnostic(
                f"第 {attempt}/{max_attempts} 次失败（{status_message(last_outcome.status)}），{wait} 秒后重试"
            )
            self._sleep(wait)
        duration_ms = max(0, int((self._clock() - started) * 1000))
        return CheckinResult.from_status(
            last_outcome.status,
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
    **service_options: Unpack[ServiceOptions],
) -> CheckinResult:
    return CheckinService(timeout=timeout, **service_options).run_checkin(
        username,
        password,
        max_attempts=max_attempts,
        retry_delay=retry_delay,
    )


def run_probe(
    username: str,
    password: str,
    timeout: int = 10,
    **service_options: Unpack[ServiceOptions],
) -> CheckinResult:
    return CheckinService(timeout=timeout, **service_options).run_probe(username, password)
