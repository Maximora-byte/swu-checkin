from unittest.mock import Mock, call

import pytest
import requests

from swu_checkin.api_models import ApiSchemaError, DormitoryInfo, LeaveRecords, StudentProfile
from swu_checkin.auth import AuthError, AuthFailureReason
from swu_checkin.cache import CheckinContext
from swu_checkin.service import CheckinService, _AttemptOutcome, build_checkin_payload
from swu_checkin.status import CheckinStatus


def _empty_token_store() -> Mock:
    store = Mock()
    store.get.return_value = None
    return store


def _http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(response=response)


@pytest.mark.parametrize(
    ("outcomes", "expected", "attempts"),
    [
        (
            [
                _AttemptOutcome(CheckinStatus.DATA_ERROR, True),
                _AttemptOutcome(CheckinStatus.DATA_ERROR, True),
                _AttemptOutcome(CheckinStatus.SUCCESS, False),
            ],
            "success",
            3,
        ),
        ([_AttemptOutcome(CheckinStatus.DATA_ERROR, True)] * 3, "data_error", 3),
    ],
)
def test_retry_result_tracks_attempts_without_real_sleep(outcomes, expected, attempts):
    sleep = Mock()
    diagnostics = Mock()
    times = iter([10.0, 10.25])
    service = CheckinService(sleep=sleep, clock=lambda: next(times), diagnostic=diagnostics)
    service._check_in_attempt = Mock(side_effect=outcomes)

    result = service.run_checkin("student", "password", max_attempts=3, retry_delay=8)

    assert result.status == expected
    assert result.attempts == attempts
    assert result.duration_ms == 250
    assert sleep.call_args_list == [call(8), call(16)]


@pytest.mark.parametrize(
    "reason",
    [
        AuthFailureReason.CREDENTIAL_REJECTED,
        AuthFailureReason.CAPTCHA_FAILED,
        AuthFailureReason.LOGIN_PAGE_CHANGED,
        AuthFailureReason.OAUTH_FLOW_CHANGED,
        AuthFailureReason.TICKET_FAILED,
        AuthFailureReason.TOKEN_EXCHANGE_FAILED,
        AuthFailureReason.UNKNOWN,
    ],
)
def test_non_retryable_auth_failures_stop_after_one_outer_attempt(reason: AuthFailureReason):
    login = Mock(side_effect=AuthError(reason))
    sleep = Mock()
    service = CheckinService(token_provider=login, token_store=_empty_token_store(), sleep=sleep)

    result = service.run_checkin("student", "password", max_attempts=3, retry_delay=8)

    assert result.attempts == 1
    assert result.code == int(
        CheckinStatus.LOGIN_FAILED
        if reason
        in {
            AuthFailureReason.CREDENTIAL_REJECTED,
            AuthFailureReason.CAPTCHA_FAILED,
        }
        else CheckinStatus.DATA_ERROR
    )
    login.assert_called_once_with("student", "password", 10)
    sleep.assert_not_called()


def test_auth_network_failure_retries_to_configured_maximum():
    login = Mock(side_effect=AuthError(AuthFailureReason.NETWORK_ERROR))
    sleep = Mock()
    service = CheckinService(token_provider=login, token_store=_empty_token_store(), sleep=sleep)

    result = service.run_checkin("student", "password", max_attempts=3, retry_delay=4)

    assert result.status == "data_error"
    assert result.attempts == 3
    assert login.call_count == 3
    assert sleep.call_args_list == [call(4), call(8)]


def _runtime_service(client: Mock, *, sleep: Mock) -> CheckinService:
    return CheckinService(
        token_provider=Mock(return_value="token"),
        client_factory=Mock(return_value=client),
        token_store=_empty_token_store(),
        sleep=sleep,
    )


def _runtime_client() -> Mock:
    client = Mock()
    client.get_student_id.return_value = "student"
    client.get_leave_record_set.return_value = LeaveRecords.from_items([])
    client.get_transition.return_value = None
    return client


def test_no_task_remains_retryable():
    client = _runtime_client()
    sleep = Mock()
    service = _runtime_service(client, sleep=sleep)

    result = service.run_checkin("student", "password", max_attempts=3, retry_delay=2)

    assert result.status == "no_task"
    assert result.attempts == 3
    assert sleep.call_args_list == [call(2), call(4)]


@pytest.mark.parametrize(
    "error",
    [
        requests.Timeout("timeout"),
        requests.ConnectionError("connection reset"),
        _http_error(503),
    ],
)
def test_transient_business_transport_failure_retries(error: requests.RequestException):
    client = _runtime_client()
    client.get_leave_record_set.side_effect = error
    sleep = Mock()
    service = _runtime_service(client, sleep=sleep)

    result = service.run_checkin("student", "password", max_attempts=3, retry_delay=3)

    assert result.status == "data_error"
    assert result.attempts == 3
    assert sleep.call_args_list == [call(3), call(6)]


def test_malformed_business_schema_is_not_retried():
    client = _runtime_client()
    client.get_leave_record_set.side_effect = ApiSchemaError("malformed")
    sleep = Mock()
    service = _runtime_service(client, sleep=sleep)

    result = service.run_checkin("student", "password", max_attempts=3, retry_delay=3)

    assert result.status == "data_error"
    assert result.attempts == 1
    client.get_leave_record_set.assert_called_once_with()
    sleep.assert_not_called()


def test_non_transient_business_http_error_is_not_retried():
    client = _runtime_client()
    client.get_leave_record_set.side_effect = _http_error(400)
    sleep = Mock()
    service = _runtime_service(client, sleep=sleep)

    result = service.run_checkin("student", "password", max_attempts=3, retry_delay=3)

    assert result.status == "data_error"
    assert result.attempts == 1
    sleep.assert_not_called()


def test_probe_result_is_single_attempt_and_non_negative_duration():
    times = iter([4.0, 3.5])
    service = CheckinService(clock=lambda: next(times))
    service.probe_once = Mock(return_value=CheckinStatus.PROBE_PENDING)

    result = service.run_probe("student", "password")

    assert result.mode == "probe"
    assert result.status == "probe_pending"
    assert result.attempts == 1
    assert result.duration_ms == 0


def test_payload_fields_and_values_remain_unchanged(monkeypatch):
    monkeypatch.setattr("swu_checkin.service.today_shanghai", lambda: "2026-09-18")
    monkeypatch.setattr("swu_checkin.service.epoch_milliseconds", lambda: 123456789)
    ctx = CheckinContext(
        student_id="20260000000",
        building="橘园",
        room="001",
        latitude=29.0,
        longitude=106.0,
        transition={"formId": "form-1", "id": "record-1"},
    )

    assert build_checkin_payload(ctx) == {
        "id": "record-1",
        "formId": "form-1",
        "tsrq": "2026-09-18",
        "xh": "20260000000",
        "qdsj": ["21:00", "23:30"],
        "qsqddd": "橘园",
        "qdbj": "001",
        "qddz": {
            "latitude": 29.0,
            "longitude": 106.0,
            "address": "橘园",
            "netType": "wifi",
            "operatorType": "unknown",
            "imei": "imei",
            "time": 123456789,
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


def test_doctor_diagnostics_are_read_only_and_never_submit():
    client = Mock()
    client.get_student_id.return_value = "20260000000"
    client.get_leave_record_set.return_value = LeaveRecords.from_items([])
    client.get_student_profile.return_value = StudentProfile("20260000000")
    client.get_dormitory_info.return_value = DormitoryInfo(29.0, 106.0, "building", "room")
    client.get_transition.return_value = None
    service = CheckinService(
        token_provider=lambda *_args: "token",
        client_factory=lambda *_args: client,
        token_store=_empty_token_store(),
    )

    report = service.diagnose("20260000000", "password")

    assert report.authentication is True
    assert report.leave_policy is True
    assert report.student_profile is True
    assert report.dormitory_schema is True
    assert report.checkin_api is True
    client.submit_checkin_form.assert_not_called()


def test_doctor_accepts_active_valid_leave_without_submit():
    client = Mock()
    client.get_student_id.return_value = "20260000000"
    client.get_leave_record_set.return_value = LeaveRecords.from_items(
        [{"lcztmc": "已同意", "kssj": "2000-01-01 00:00", "jssj": "2100-01-01 00:00"}]
    )
    client.get_student_profile.return_value = StudentProfile("20260000000")
    client.get_dormitory_info.return_value = DormitoryInfo(29.0, 106.0, "building", "room")
    client.get_transition.return_value = None
    service = CheckinService(
        token_provider=lambda *_args: "token",
        client_factory=lambda *_args: client,
        token_store=_empty_token_store(),
    )

    report = service.diagnose("20260000000", "password")

    assert report.leave_policy is True
    client.submit_checkin_form.assert_not_called()


def test_doctor_rejects_unknown_leave_policy_without_submit():
    client = Mock()
    client.get_student_id.return_value = "20260000000"
    client.get_leave_record_set.return_value = LeaveRecords.from_items([None])
    client.get_student_profile.return_value = StudentProfile("20260000000")
    client.get_dormitory_info.return_value = DormitoryInfo(29.0, 106.0, "building", "room")
    client.get_transition.return_value = None
    service = CheckinService(
        token_provider=lambda *_args: "token",
        client_factory=lambda *_args: client,
        token_store=_empty_token_store(),
    )

    report = service.diagnose("20260000000", "password")

    assert report.leave_policy is False
    client.submit_checkin_form.assert_not_called()
