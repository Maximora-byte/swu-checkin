import importlib
import json
from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest
import requests

from swu_checkin import check_in as run_check_in
from swu_checkin.cache import CheckinContext
from swu_checkin.check_in import (
    _business_response_succeeded,
    _check_vacation_status,
    _parse_dormitory_data,
    _record_run_status,
    _submit_checkin,
    main,
    probe_check_in,
)
from swu_checkin.notify import _build_message
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


def test_business_response_requires_explicit_success_signal():
    assert _business_response_succeeded({"code": 200, "message": "保存成功"})
    assert _business_response_succeeded({"success": True})
    assert not _business_response_succeeded({"code": 500, "message": "保存失败"})
    assert not _business_response_succeeded({"message": "保存成功"})
    assert not _business_response_succeeded("保存成功")


@patch("swu_checkin.check_in.time.sleep", return_value=None)
@patch("swu_checkin.check_in.get_transition_today")
@patch("swu_checkin.check_in.requests.post")
def test_http_200_business_failure_is_not_success(post: Mock, get_transition: Mock, _sleep: Mock):
    post.return_value = _response({"code": 500, "message": "保存失败"})
    get_transition.return_value = {"qdzt": "未签到"}

    assert _submit_checkin(_context(), 10) == CheckinStatus.DATA_ERROR
    assert get_transition.call_count == 4


@patch("swu_checkin.check_in.time.sleep", return_value=None)
@patch("swu_checkin.check_in.get_transition_today")
@patch("swu_checkin.check_in.requests.post")
def test_submit_success_without_readback_confirmation_is_failure(post: Mock, get_transition: Mock, _sleep: Mock):
    post.return_value = _response({"code": 200, "message": "保存成功"})
    get_transition.return_value = {"qdzt": "未签到"}

    assert _submit_checkin(_context(), 10) == CheckinStatus.DATA_ERROR
    assert get_transition.call_count == 4


@patch("swu_checkin.check_in.time.sleep", return_value=None)
@patch("swu_checkin.check_in.get_transition_today")
@patch("swu_checkin.check_in.requests.post")
def test_submit_succeeds_only_after_readback(post: Mock, get_transition: Mock, _sleep: Mock):
    post.return_value = _response({"code": 200, "message": "保存成功"})
    get_transition.side_effect = [{"qdzt": "未签到"}, {"qdzt": "已签到"}]

    assert _submit_checkin(_context(), 10) == CheckinStatus.SUCCESS
    assert get_transition.call_count == 2


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 9, 17, 12, 59, tzinfo=UTC), VacationStatus.NO_ACTIVE_LEAVE),
        (datetime(2026, 9, 17, 13, 0, tzinfo=UTC), VacationStatus.ACTIVE_LEAVE),
        (datetime(2026, 9, 17, 14, 0, tzinfo=UTC), VacationStatus.ACTIVE_LEAVE),
        (datetime(2026, 9, 17, 14, 1, tzinfo=UTC), VacationStatus.NO_ACTIVE_LEAVE),
    ],
)
@patch("swu_checkin.check_in.requests.get")
def test_vacation_uses_timezone_aware_shanghai_boundaries(get: Mock, now: datetime, expected: VacationStatus):
    get.return_value = _response(
        {"data": {"records": [{"lcztmc": "已同意", "kssj": "2026-09-17 21:00", "jssj": "2026-09-17 22:00"}]}}
    )

    assert _check_vacation_status(_context(), 10, now=now) is expected


@patch("swu_checkin.check_in.requests.get")
def test_vacation_checks_all_approved_records(get: Mock):
    get.return_value = _response(
        {
            "data": {
                "records": [
                    {"lcztmc": "已同意", "kssj": "2026-09-16 08:00", "jssj": "2026-09-16 09:00"},
                    {"lcztmc": "审核中"},
                    {"lcztmc": "已同意", "kssj": "2026-09-17 21:00", "jssj": "2026-09-17 22:00"},
                ]
            }
        }
    )

    result = _check_vacation_status(_context(), 10, now=datetime(2026, 9, 17, 13, 30, tzinfo=UTC))

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
@patch("swu_checkin.check_in.requests.get")
def test_malformed_vacation_response_is_unknown(get: Mock, payload: object):
    get.return_value = _response(payload)

    assert _check_vacation_status(_context(), 10) is VacationStatus.UNKNOWN


@patch("swu_checkin.check_in.requests.get")
def test_invalid_vacation_json_is_unknown(get: Mock):
    get.return_value = _response({"data": {"records": []}})
    get.return_value.json.side_effect = json.JSONDecodeError("invalid", "", 0)

    assert _check_vacation_status(_context(), 10) is VacationStatus.UNKNOWN


@pytest.mark.parametrize("error", [requests.Timeout("timeout"), requests.HTTPError("503")])
@patch("swu_checkin.check_in.requests.get")
def test_vacation_api_failures_are_unknown(get: Mock, error: requests.RequestException):
    if isinstance(error, requests.HTTPError):
        get.return_value = _response({"data": {"records": []}})
        get.return_value.raise_for_status.side_effect = error
    else:
        get.side_effect = error

    assert _check_vacation_status(_context(), 10) is VacationStatus.UNKNOWN


@patch("swu_checkin.check_in.requests.post")
@patch("swu_checkin.check_in.get_transition_today")
@patch("swu_checkin.check_in._check_vacation_status", return_value=VacationStatus.UNKNOWN)
@patch("swu_checkin.check_in.get_token", return_value="test-token")
def test_unknown_vacation_status_stops_checkin_before_task_lookup(
    _token: Mock, _vacation: Mock, get_transition: Mock, post: Mock
):
    assert run_check_in("student", "password") == CheckinStatus.DATA_ERROR
    get_transition.assert_not_called()
    post.assert_not_called()


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


@patch("swu_checkin.check_in.requests.post")
@patch("swu_checkin.check_in.get_transition_today")
@patch("swu_checkin.check_in._check_vacation_status", return_value=VacationStatus.NO_ACTIVE_LEAVE)
@patch("swu_checkin.check_in.get_token", return_value="test-token")
def test_probe_never_submits(_token: Mock, _vacation: Mock, get_transition: Mock, post: Mock):
    get_transition.return_value = {"id": "record-1", "formId": "form-1", "qdzt": "未签到"}

    assert probe_check_in("student", "password") == CheckinStatus.PROBE_PENDING
    post.assert_not_called()


@pytest.mark.parametrize("status", [CheckinStatus.SUCCESS, CheckinStatus.ALREADY_CHECKED_IN, CheckinStatus.ON_LEAVE])
def test_statuses_1_2_5_are_successful_terminal_states(status: CheckinStatus):
    assert is_successful_checkin_status(status)


@pytest.mark.parametrize("status", [CheckinStatus.SUCCESS, CheckinStatus.ALREADY_CHECKED_IN, CheckinStatus.ON_LEAVE])
def test_cli_exits_zero_for_statuses_1_2_5(monkeypatch: pytest.MonkeyPatch, status: CheckinStatus):
    monkeypatch.setenv("SWUDK_USERNAME", "student")
    monkeypatch.setenv("SWUDK_PASSWORD", "secret")
    monkeypatch.delenv("SWUDK_PROBE_ONLY", raising=False)
    monkeypatch.delenv("SWUDK_STATUS_FILE", raising=False)
    check_in_module = importlib.import_module("swu_checkin.check_in")
    monkeypatch.setattr(check_in_module, "check_in_with_retry", lambda *_args: status)

    assert main() == 0


def test_status_record_preserves_an_earlier_success(tmp_path):
    status_file = tmp_path / "status.json"

    _record_run_status(str(status_file), CheckinStatus.SUCCESS)
    _record_run_status(str(status_file), CheckinStatus.DATA_ERROR)

    payload = json.loads(status_file.read_text(encoding="utf-8"))
    assert payload["successful"] is True
    assert [attempt["code"] for attempt in payload["attempts"]] == [1, 4]


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
