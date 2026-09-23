import json
import stat
from datetime import UTC, datetime
from unittest.mock import Mock, call

import pytest
import requests

from swu_checkin.api_models import DormitoryInfo, LeaveRecords, StudentProfile, Transition
from swu_checkin.cache import CheckinContext
from swu_checkin.check_in import (
    _business_response_succeeded,
    _parse_dormitory_data,
    _record_run_status,
)
from swu_checkin.client import SwuClient
from swu_checkin.models import CheckinResult
from swu_checkin.notify import _build_message
from swu_checkin.runtime_lock import RuntimeLock
from swu_checkin.service import (
    EXPECTED_DATA_ERRORS,
    CheckinService,
    DormitorySchemaError,
    _business_response_diagnostic,
    evaluate_vacation_records,
)
from swu_checkin.status import CheckinStatus, VacationStatus, is_successful_checkin_status


def _context() -> CheckinContext:
    return CheckinContext(
        token="test-token",
        student_id="20260000000",
        building="橘园",
        room="001",
        latitude=29.0,
        longitude=106.0,
        transition={"formId": "form-1", "id": "record-1", "qdzt": "未签到"},
    )


def _response(payload: object) -> Mock:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def _dormitory(latitude: object, longitude: object) -> list[dict[str, object]]:
    return [
        {"prop": "qddz", "latitude": latitude, "longitude": longitude},
        {"prop": "qsqddd", "value": " 橘园 "},
        {"prop": "qdbj", "value": " 001 "},
    ]


def _current_dormitory(latitude: object, longitude: object) -> list[dict[str, object]]:
    return [
        {
            "address": "示例地址",
            "latitude": latitude,
            "longitude": longitude,
            "qdbj": "范围标记",
        },
        {"prop": "qsqddd", "value": " 橘园 "},
        {"prop": "qdbj", "value": " 001 "},
    ]


class _FakeClient:
    def __init__(
        self,
        transitions: list[dict | None],
        *,
        leave_records: list[dict | object] | None = None,
        submit_response: object | None = None,
    ):
        self.transitions = list(transitions)
        self.leave_records = [] if leave_records is None else leave_records
        self.submit_response = {"code": 200} if submit_response is None else submit_response
        self.submit_calls = 0

    def get_leave_records(self):
        return self.leave_records

    def get_leave_record_set(self):
        return LeaveRecords.from_items(self.leave_records)

    def get_transition_today(self):
        return self.transitions.pop(0) if self.transitions else {"qdzt": "未签到"}

    def get_transition(self):
        value = self.get_transition_today()
        if value is None:
            return None
        return Transition.from_record(value)

    def get_dormitory(self):
        return {"data": {"columnList": _dormitory(29, 106)}}

    def get_dormitory_info(self):
        return DormitoryInfo.from_response(self.get_dormitory())

    def get_student_id(self):
        return "student"

    def get_student_profile(self):
        return StudentProfile(self.get_student_id())

    def submit_checkin_form(self, **_kwargs):
        self.submit_calls += 1
        return self.submit_response


def _service(client: _FakeClient, *, diagnostic=print, sleep=lambda _seconds: None) -> CheckinService:
    token_store = Mock()
    token_store.get.return_value = None
    return CheckinService(
        token_provider=lambda *_args: "test-token",
        client_factory=lambda *_args: client,
        sleep=sleep,
        clock=lambda: 0.0,
        diagnostic=diagnostic,
        token_store=token_store,
    )


def _vacation_status(payload: object) -> VacationStatus:
    session = Mock()
    session.get.return_value = _response(payload)
    try:
        records = SwuClient("test-token", session=session).get_leave_records()
        return evaluate_vacation_records(records)
    except EXPECTED_DATA_ERRORS:
        return VacationStatus.UNKNOWN


def test_business_response_requires_explicit_success_signal():
    assert _business_response_succeeded({"code": 200, "message": "保存成功"})
    assert _business_response_succeeded({"success": True})
    assert not _business_response_succeeded({"code": 500, "message": "保存失败"})
    assert not _business_response_succeeded({"message": "保存成功"})
    assert not _business_response_succeeded("保存成功")


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"code": 500, "message": "保存失败"}, "业务码=500"),
        ({"data": {"status": "DENIED"}}, "业务码=DENIED"),
        ({"success": False}, "显式失败标志"),
        ({"message": "保存失败"}, "缺少明确业务码或成功标志"),
        ("保存失败", "响应结构异常"),
        ({"code": "token=secret"}, "业务码已返回但不可安全记录"),
    ],
)
def test_business_response_diagnostic_is_non_sensitive(payload: object, expected: str):
    diagnostic = _business_response_diagnostic(payload)

    assert diagnostic == expected
    assert "secret" not in diagnostic


def test_http_200_business_failure_is_not_success():
    pending = {"id": "record-1", "formId": "form-1", "qdzt": "未签到"}
    client = _FakeClient([pending] * 5, submit_response={"code": 500, "message": "保存失败"})
    diagnostic = Mock()

    assert _service(client, diagnostic=diagnostic).check_in_once("student", "password") == CheckinStatus.DATA_ERROR
    assert client.submit_calls == 1
    diagnostic.assert_called_once_with("签到接口未返回明确成功状态（业务码=500），且服务端状态未变更")


def test_submit_success_without_readback_confirmation_is_failure():
    pending = {"id": "record-1", "formId": "form-1", "qdzt": "未签到"}
    client = _FakeClient([pending] * 5, submit_response={"code": 200, "message": "保存成功"})

    assert _service(client).check_in_once("student", "password") == CheckinStatus.DATA_ERROR


def test_submit_succeeds_only_after_readback():
    pending = {"id": "record-1", "formId": "form-1", "qdzt": "未签到"}
    client = _FakeClient([pending, {"qdzt": "未签到"}, {"qdzt": "已签到"}])

    assert _service(client).check_in_once("student", "password") == CheckinStatus.SUCCESS
    assert client.submit_calls == 1


def _http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(response=response)


@pytest.mark.parametrize(
    ("error", "classification"),
    [
        (requests.Timeout("token=secret"), "请求超时"),
        (requests.ConnectionError("token=secret"), "连接异常"),
        (_http_error(503), "HTTP 503"),
    ],
)
@pytest.mark.parametrize(("confirmed", "expected"), [(True, "success"), (False, "data_error")])
def test_ambiguous_submit_is_read_back_without_outer_retry(
    error: requests.RequestException,
    classification: str,
    confirmed: bool,
    expected: str,
):
    pending = {"id": "record-1", "formId": "form-1", "qdzt": "未签到"}
    readback = {"qdzt": "已签到"} if confirmed else pending
    client = _FakeClient([pending, *([readback] * 4)])
    client.submit_checkin_form = Mock(side_effect=error)
    sleep = Mock()
    diagnostic = Mock()
    service = _service(client, sleep=sleep, diagnostic=diagnostic)

    result = service.run_checkin("student", "password", max_attempts=3, retry_delay=8)

    assert result.status == expected
    assert result.attempts == 1
    assert client.submit_checkin_form.call_count == 1
    if confirmed:
        sleep.assert_not_called()
        diagnostic.assert_not_called()
    else:
        assert sleep.call_args_list == [call(0.3), call(0.6), call(1.0)]
        diagnostic.assert_called_once_with(f"签到请求结果不明确（{classification}），且未能确认服务端签到状态")
        assert "secret" not in diagnostic.call_args.args[0]


def test_already_checked_in_transition_needs_only_status():
    client = _FakeClient([{"qdzt": "已签到"}])

    assert _service(client).check_in_once("student", "password") == CheckinStatus.ALREADY_CHECKED_IN
    assert client.submit_calls == 0


@pytest.mark.parametrize(
    "pending",
    [
        {"qdzt": "未签到"},
        {"id": "record-1", "qdzt": "未签到"},
        {"formId": "form-1", "qdzt": "未签到"},
    ],
)
def test_pending_transition_without_submission_ids_fails_closed(pending: dict[str, object]):
    client = _FakeClient([pending])

    assert _service(client).check_in_once("student", "password") == CheckinStatus.DATA_ERROR
    assert client.submit_calls == 0


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 9, 17, 12, 59, tzinfo=UTC), VacationStatus.NO_ACTIVE_LEAVE),
        (datetime(2026, 9, 17, 13, 0, tzinfo=UTC), VacationStatus.ACTIVE_LEAVE),
        (datetime(2026, 9, 17, 14, 0, tzinfo=UTC), VacationStatus.ACTIVE_LEAVE),
        (datetime(2026, 9, 17, 14, 1, tzinfo=UTC), VacationStatus.NO_ACTIVE_LEAVE),
    ],
)
def test_vacation_uses_timezone_aware_shanghai_boundaries(now: datetime, expected: VacationStatus):
    records = [{"lcztmc": "已同意", "kssj": "2026-09-17 21:00", "jssj": "2026-09-17 22:00"}]

    assert evaluate_vacation_records(records, now=now) is expected


def test_vacation_checks_all_approved_records():
    records = [
        {"lcztmc": "已同意", "kssj": "2026-09-16 08:00", "jssj": "2026-09-16 09:00"},
        {"lcztmc": "审核中"},
        {"lcztmc": "已同意", "kssj": "2026-09-17 21:00", "jssj": "2026-09-17 22:00"},
    ]

    result = evaluate_vacation_records(records, now=datetime(2026, 9, 17, 13, 30, tzinfo=UTC))

    assert result is VacationStatus.ACTIVE_LEAVE


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"data": None},
        {"data": {}},
        {"data": {"records": None}},
        {"data": {"records": [None]}},
        {"data": {"records": [{"lcztmc": "已同意", "kssj": "invalid", "jssj": "invalid"}]}},
        {"data": {"records": [{"lcztmc": "已同意", "kssj": "2026-09-18 22:00", "jssj": "2026-09-18 21:00"}]}},
    ],
)
def test_malformed_vacation_response_is_unknown(payload: object):
    assert _vacation_status(payload) is VacationStatus.UNKNOWN


def test_invalid_vacation_json_is_unknown():
    session = Mock()
    session.get.return_value = _response({"data": {"records": []}})
    session.get.return_value.json.side_effect = json.JSONDecodeError("invalid", "", 0)

    with pytest.raises(json.JSONDecodeError):
        SwuClient("test-token", session=session).get_leave_records()


@pytest.mark.parametrize("error", [requests.Timeout("timeout"), requests.HTTPError("503")])
def test_vacation_api_failures_are_data_errors(error: requests.RequestException):
    client = _FakeClient([])
    client.get_leave_record_set = Mock(side_effect=error)

    assert _service(client).check_in_once("student", "password") is CheckinStatus.DATA_ERROR


def test_unknown_vacation_status_stops_checkin_before_task_lookup():
    client = _FakeClient([])
    client.get_leave_record_set = Mock(return_value=LeaveRecords.from_items([None]))
    client.get_transition = Mock()

    assert _service(client).check_in_once("student", "password") == CheckinStatus.DATA_ERROR
    client.get_transition.assert_not_called()


def test_valid_dormitory_coordinates_are_normalized():
    location, building, room = _parse_dormitory_data(_dormitory("29.123", "106.456"))

    assert location == {"latitude": 29.123, "longitude": 106.456}
    assert building == "橘园"
    assert room == "001"


def test_current_dormitory_location_shape_is_accepted():
    location, building, room = _parse_dormitory_data(_current_dormitory("29.123", "106.456"))

    assert location == {"latitude": 29.123, "longitude": 106.456}
    assert building == "橘园"
    assert room == "001"


def test_dormitory_without_location_candidate_fails_closed():
    columns = [
        {"prop": "qsqddd", "value": "橘园"},
        {"prop": "qdbj", "value": "001"},
    ]

    with pytest.raises(DormitorySchemaError, match="invalid or ambiguous"):
        _parse_dormitory_data(columns)


def test_dormitory_with_two_location_candidates_fails_closed():
    columns = _dormitory(29, 106)
    columns.insert(1, {"prop": "qddz", "latitude": 29, "longitude": 106})

    with pytest.raises(DormitorySchemaError, match="invalid or ambiguous"):
        _parse_dormitory_data(columns)


def test_dormitory_with_legacy_and_current_location_candidates_fails_closed():
    columns = _dormitory(29, 106)
    columns.insert(1, _current_dormitory(29, 106)[0])

    with pytest.raises(DormitorySchemaError, match="invalid or ambiguous"):
        _parse_dormitory_data(columns)


@pytest.mark.parametrize("missing", ["latitude", "longitude"])
def test_current_dormitory_location_missing_coordinate_fails_closed(missing: str):
    columns = _current_dormitory(29, 106)
    del columns[0][missing]

    with pytest.raises(DormitorySchemaError):
        _parse_dormitory_data(columns)


@pytest.mark.parametrize("missing", ["address", "qdbj"])
def test_no_prop_location_missing_shape_marker_fails_closed(missing: str):
    columns = _current_dormitory(29, 106)
    del columns[0][missing]

    with pytest.raises(DormitorySchemaError):
        _parse_dormitory_data(columns)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (None, 106),
        (True, 106),
        ("invalid", 106),
        (float("nan"), 106),
        (float("inf"), 106),
        (91, 106),
        (-91, 106),
        (29, None),
        (29, "invalid"),
        (29, 181),
        (29, -181),
    ],
)
def test_invalid_dormitory_coordinates_are_rejected(latitude: object, longitude: object):
    with pytest.raises(ValueError, match="latitude|longitude"):
        _parse_dormitory_data(_dormitory(latitude, longitude))


def test_probe_never_submits():
    client = _FakeClient([{"id": "record-1", "formId": "form-1", "qdzt": "未签到"}])

    assert _service(client).probe_once("student", "password") == CheckinStatus.PROBE_PENDING
    assert client.submit_calls == 0


def test_probe_reports_dormitory_schema_failure_without_submitting():
    pending = {"id": "record-1", "formId": "form-1", "qdzt": "未签到"}
    client = _FakeClient([pending])
    client.get_dormitory_info = Mock(side_effect=DormitorySchemaError("invalid schema"))
    diagnostics = Mock()

    assert _service(client, diagnostic=diagnostics).probe_once("student", "password") == CheckinStatus.DATA_ERROR
    diagnostics.assert_called_once_with("宿舍数据结构异常")
    assert client.submit_calls == 0


def test_probe_preflight_validates_dormitory_and_student_without_submitting():
    pending = {"id": "record-1", "formId": "form-1", "qdzt": "未签到"}
    client = _FakeClient([pending])
    client.get_dormitory_info = Mock(return_value=DormitoryInfo(29.0, 106.0, "橘园", "001"))
    client.get_student_profile = Mock(return_value=StudentProfile("20260000000"))

    assert _service(client).probe_once("student", "password") == CheckinStatus.PROBE_PENDING
    client.get_dormitory_info.assert_called_once_with()
    client.get_student_profile.assert_called_once_with()
    assert client.submit_calls == 0


@pytest.mark.parametrize("status", [CheckinStatus.SUCCESS, CheckinStatus.ALREADY_CHECKED_IN, CheckinStatus.ON_LEAVE])
def test_statuses_1_2_5_are_successful_terminal_states(status: CheckinStatus):
    assert is_successful_checkin_status(status)


@pytest.mark.parametrize("status", [CheckinStatus.SUCCESS, CheckinStatus.ALREADY_CHECKED_IN, CheckinStatus.ON_LEAVE])
def test_cli_exits_zero_for_statuses_1_2_5(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    status: CheckinStatus,
):
    monkeypatch.setenv("SWUDK_USERNAME", "student")
    monkeypatch.setenv("SWUDK_PASSWORD", "secret")
    monkeypatch.delenv("SWUDK_PROBE_ONLY", raising=False)
    monkeypatch.delenv("SWUDK_STATUS_FILE", raising=False)
    monkeypatch.setenv("SWUDK_LOCK_FILE", str(tmp_path / "checkin.lock"))
    monkeypatch.setattr(
        "swu_checkin.cli.run_checkin",
        lambda *_args, **_kwargs: CheckinResult.from_status(status, attempts=1, duration_ms=0, mode="checkin"),
    )

    from swu_checkin.check_in import main

    assert main() == 0


def test_legacy_formal_main_uses_the_same_runtime_lock(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys):
    lock_path = tmp_path / "checkin.lock"
    monkeypatch.setenv("SWUDK_LOCK_FILE", str(lock_path))
    monkeypatch.setattr(
        "swu_checkin.cli.run_checkin",
        lambda *_args, **_kwargs: pytest.fail("legacy busy path must not use SWU"),
    )

    from swu_checkin.check_in import main

    with RuntimeLock(lock_path):
        assert main() == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "已有签到任务正在运行，本次跳过" in captured.err


def test_status_record_preserves_an_earlier_success(tmp_path):
    status_file = tmp_path / "status.json"

    _record_run_status(str(status_file), CheckinStatus.SUCCESS)
    _record_run_status(str(status_file), CheckinStatus.DATA_ERROR)

    payload = json.loads(status_file.read_text(encoding="utf-8"))
    assert payload["successful"] is True
    assert [attempt["code"] for attempt in payload["attempts"]] == [1, 4]
    assert stat.S_IMODE(status_file.stat().st_mode) == 0o640


@pytest.mark.parametrize(
    ("code", "prefix"),
    [
        (CheckinStatus.SUCCESS, "✅ SWU 宿舍签到成功"),
        (CheckinStatus.ALREADY_CHECKED_IN, "✅ SWU 宿舍签到成功"),
        (CheckinStatus.ON_LEAVE, "ℹ️ SWU 宿舍签到：今日无需签到"),
    ],
)
def test_telegram_summary_for_terminal_statuses(code: CheckinStatus, prefix: str):
    attempts = [{"code": int(code), "message": "测试结果"}]

    assert _build_message(attempts, "2026-09-17", "").startswith(prefix)


def test_notification_prefers_any_successful_attempt():
    attempts = [
        {"code": 1, "message": "签到成功"},
        {"code": 4, "message": "网络错误或数据异常"},
    ]

    message = _build_message(attempts, "2026-09-17", "")

    assert message.startswith("✅ SWU 宿舍签到成功")
    assert "今日执行：2 次" in message
