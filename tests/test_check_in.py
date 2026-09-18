import json
import stat
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
import requests

from swu_checkin.cache import CheckinContext
from swu_checkin.check_in import (
    _business_response_succeeded,
    _parse_dormitory_data,
    _record_run_status,
)
from swu_checkin.client import SwuClient
from swu_checkin.models import CheckinResult
from swu_checkin.notify import _build_message
from swu_checkin.service import EXPECTED_DATA_ERRORS, CheckinService, evaluate_vacation_records
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

    def get_transition_today(self):
        return self.transitions.pop(0) if self.transitions else {"qdzt": "未签到"}

    def get_dormitory(self):
        return {"data": {"columnList": _dormitory(29, 106)}}

    def get_student_id(self):
        return "20260000000"

    def submit_checkin_form(self, **_kwargs):
        self.submit_calls += 1
        return self.submit_response


def _service(client: _FakeClient) -> CheckinService:
    return CheckinService(
        token_provider=lambda *_args: "test-token",
        client_factory=lambda *_args: client,
        sleep=lambda _seconds: None,
        clock=lambda: 0.0,
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


def test_http_200_business_failure_is_not_success():
    pending = {"id": "record-1", "formId": "form-1", "qdzt": "未签到"}
    client = _FakeClient([pending] * 5, submit_response={"code": 500, "message": "保存失败"})

    assert _service(client).check_in_once("student", "password") == CheckinStatus.DATA_ERROR
    assert client.submit_calls == 1


def test_submit_success_without_readback_confirmation_is_failure():
    pending = {"id": "record-1", "formId": "form-1", "qdzt": "未签到"}
    client = _FakeClient([pending] * 5, submit_response={"code": 200, "message": "保存成功"})

    assert _service(client).check_in_once("student", "password") == CheckinStatus.DATA_ERROR


def test_submit_succeeds_only_after_readback():
    pending = {"id": "record-1", "formId": "form-1", "qdzt": "未签到"}
    client = _FakeClient([pending, {"qdzt": "未签到"}, {"qdzt": "已签到"}])

    assert _service(client).check_in_once("student", "password") == CheckinStatus.SUCCESS
    assert client.submit_calls == 1


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
    client.get_leave_records = Mock(side_effect=error)

    assert _service(client).check_in_once("student", "password") is CheckinStatus.DATA_ERROR


def test_unknown_vacation_status_stops_checkin_before_task_lookup():
    client = _FakeClient([])
    client.get_leave_records = Mock(return_value=[None])
    client.get_transition_today = Mock()

    assert _service(client).check_in_once("student", "password") == CheckinStatus.DATA_ERROR
    client.get_transition_today.assert_not_called()


def test_valid_dormitory_coordinates_are_normalized():
    location, building, room = _parse_dormitory_data(_dormitory("29.123", "106.456"))

    assert location == {"latitude": 29.123, "longitude": 106.456}
    assert building == "橘园"
    assert room == "001"


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


@pytest.mark.parametrize("status", [CheckinStatus.SUCCESS, CheckinStatus.ALREADY_CHECKED_IN, CheckinStatus.ON_LEAVE])
def test_statuses_1_2_5_are_successful_terminal_states(status: CheckinStatus):
    assert is_successful_checkin_status(status)


@pytest.mark.parametrize("status", [CheckinStatus.SUCCESS, CheckinStatus.ALREADY_CHECKED_IN, CheckinStatus.ON_LEAVE])
def test_cli_exits_zero_for_statuses_1_2_5(monkeypatch: pytest.MonkeyPatch, status: CheckinStatus):
    monkeypatch.setenv("SWUDK_USERNAME", "student")
    monkeypatch.setenv("SWUDK_PASSWORD", "secret")
    monkeypatch.delenv("SWUDK_PROBE_ONLY", raising=False)
    monkeypatch.delenv("SWUDK_STATUS_FILE", raising=False)
    monkeypatch.setattr(
        "swu_checkin.cli.run_checkin",
        lambda *_args, **_kwargs: CheckinResult.from_status(status, attempts=1, duration_ms=0, mode="checkin"),
    )

    from swu_checkin.check_in import main

    assert main() == 0


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
