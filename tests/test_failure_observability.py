import json
from unittest.mock import Mock, call

import pytest
import requests

from swu_checkin.api_models import (
    ApiSchemaError,
    DormitoryInfo,
    DormitorySchemaError,
    LeaveRecords,
    StudentProfile,
    Transition,
)
from swu_checkin.auth import AuthError, AuthFailureReason
from swu_checkin.client import SessionExpiredError
from swu_checkin.service import CheckinService
from swu_checkin.status import VacationStatus


def _http_error(status_code: int, secret: str = "") -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    response.url = f"https://example.invalid/?token={secret}"
    response._content = secret.encode()
    return requests.HTTPError(secret, response=response)


def _store() -> Mock:
    store = Mock()
    store.get.return_value = None
    return store


def _pending_client() -> Mock:
    client = Mock()
    client.get_student_id.return_value = "student"
    client.get_leave_record_set.return_value = LeaveRecords.from_items([])
    client.get_transition.return_value = Transition("record", "form", "未签到")
    client.get_student_profile.return_value = StudentProfile("student")
    client.get_dormitory_info.return_value = DormitoryInfo(29.0, 106.0, "building", "room")
    client.submit_checkin_form.return_value = {"code": 200}
    return client


def _service(client: Mock, *, diagnostic: Mock, sleep: Mock | None = None) -> CheckinService:
    return CheckinService(
        token_provider=Mock(return_value="token"),
        client_factory=Mock(return_value=client),
        token_store=_store(),
        diagnostic=diagnostic,
        sleep=sleep or Mock(),
    )


@pytest.mark.parametrize(
    ("stage", "method_name"),
    [
        ("leave", "get_leave_record_set"),
        ("transition", "get_transition"),
        ("student_profile", "get_student_profile"),
        ("dormitory", "get_dormitory_info"),
    ],
)
@pytest.mark.parametrize(
    ("error", "classification", "attempts", "sleeps"),
    [
        (requests.Timeout("secret"), "请求超时", 3, [call(8), call(16)]),
        (requests.ConnectionError("secret"), "连接异常", 3, [call(8), call(16)]),
        (_http_error(503, "secret"), "HTTP 503", 3, [call(8), call(16)]),
        (requests.RequestException("secret"), "请求异常", 1, []),
        (ApiSchemaError("secret"), "数据结构异常", 1, []),
    ],
)
def test_pre_submit_stages_preserve_classification_status_and_retryability(
    stage: str,
    method_name: str,
    error: Exception,
    classification: str,
    attempts: int,
    sleeps: list[object],
):
    client = _pending_client()
    getattr(client, method_name).side_effect = error
    diagnostic = Mock()
    sleep = Mock()

    result = _service(client, diagnostic=diagnostic, sleep=sleep).run_checkin(
        "student", "password", max_attempts=3, retry_delay=8
    )

    assert result.status == "data_error"
    assert result.attempts == attempts
    assert sleep.call_args_list == sleeps
    assert call(f"签到失败（stage={stage}，{classification}）") in diagnostic.call_args_list


@pytest.mark.parametrize(
    ("error", "classification", "attempts"),
    [
        (requests.Timeout("secret"), "请求超时", 3),
        (requests.ConnectionError("secret"), "连接异常", 3),
        (_http_error(503, "secret"), "HTTP 503", 3),
        (json.JSONDecodeError("secret", "", 0), "JSON 解析异常", 1),
    ],
)
def test_token_validation_stage_is_safe_and_keeps_retry_semantics(error: Exception, classification: str, attempts: int):
    client = _pending_client()
    client.get_student_id.side_effect = error
    diagnostic = Mock()

    result = _service(client, diagnostic=diagnostic).run_checkin("student", "password")

    assert result.status == "data_error"
    assert result.attempts == attempts
    assert call(f"签到失败（stage=token_validation，{classification}）") in diagnostic.call_args_list


@pytest.mark.parametrize(
    ("reason", "category", "status", "attempts"),
    [
        (AuthFailureReason.NETWORK_ERROR, "认证网络异常", "data_error", 3),
        (AuthFailureReason.CREDENTIAL_REJECTED, "账号凭据未通过认证", "login_failed", 1),
    ],
)
def test_auth_stage_preserves_public_status_and_retryability(
    reason: AuthFailureReason, category: str, status: str, attempts: int
):
    diagnostic = Mock()
    service = CheckinService(
        token_provider=Mock(side_effect=AuthError(reason, "token-secret")),
        token_store=_store(),
        diagnostic=diagnostic,
        sleep=Mock(),
    )

    result = service.run_checkin("student-20260000000", "password-secret")

    assert result.status == status
    assert result.attempts == attempts
    assert call(f"签到失败（stage=auth，{category}）") in diagnostic.call_args_list


def test_dormitory_schema_uses_fixed_stage_and_category():
    client = _pending_client()
    client.get_dormitory_info.side_effect = DormitorySchemaError("building-secret")
    diagnostic = Mock()

    result = _service(client, diagnostic=diagnostic).run_checkin("student", "password")

    assert result.status == "data_error"
    assert result.attempts == 1
    assert diagnostic.call_args_list == [call("签到失败（stage=dormitory，宿舍数据结构异常）")]


def test_unknown_leave_status_emits_fixed_safe_stage():
    client = _pending_client()
    leave_records = Mock()
    leave_records.evaluate.return_value = VacationStatus.UNKNOWN
    client.get_leave_record_set.return_value = leave_records
    diagnostic = Mock()

    result = _service(client, diagnostic=diagnostic).run_checkin("student", "password")

    assert result.status == "data_error"
    assert result.attempts == 1
    diagnostic.assert_called_once_with("签到失败（stage=leave，请假状态无法安全确认）")
    client.submit_checkin_form.assert_not_called()


@pytest.mark.parametrize("status_code", [401, 403])
def test_token_validation_rejection_keeps_token_validation_stage(status_code: int):
    client = _pending_client()
    client.get_student_id.side_effect = _http_error(status_code, "token-secret")
    diagnostic = Mock()

    result = _service(client, diagnostic=diagnostic).run_checkin("student", "password", max_attempts=3, retry_delay=8)

    assert result.status == "data_error"
    assert result.attempts == 1
    diagnostic.assert_called_once_with("签到失败（stage=token_validation，认证令牌校验异常）")
    assert "token-secret" not in diagnostic.call_args.args[0]


@pytest.mark.parametrize(
    ("submit_error", "classification"),
    [
        (requests.Timeout("token-secret"), "请求超时"),
        (requests.ConnectionError("cookie-secret"), "连接异常"),
        (_http_error(503, "ticket-secret"), "HTTP 503"),
    ],
)
def test_ambiguous_submit_and_confirm_are_distinct_and_never_post_twice(
    submit_error: requests.RequestException, classification: str
):
    client = _pending_client()
    client.get_transition.side_effect = [
        Transition("record", "form", "未签到"),
        *([requests.Timeout("confirm-token-secret")] * 4),
    ]
    client.submit_checkin_form.side_effect = submit_error
    diagnostic = Mock()
    sleep = Mock()

    result = _service(client, diagnostic=diagnostic, sleep=sleep).run_checkin(
        "student", "password", max_attempts=3, retry_delay=8
    )

    assert result.status == "data_error"
    assert result.attempts == 1
    assert client.submit_checkin_form.call_count == 1
    assert call(f"签到失败（stage=submit，{classification}）") in diagnostic.call_args_list
    assert diagnostic.call_args_list.count(call("签到状态确认失败（stage=confirm，请求超时）")) == 4
    assert sleep.call_args_list == [call(0.3), call(0.6), call(1.0)]


def test_confirm_session_expiry_is_safe_readback_failure_without_resubmit():
    client = _pending_client()
    client.get_transition.side_effect = [
        Transition("record", "form", "未签到"),
        *([SessionExpiredError("token-secret response-secret")] * 4),
    ]
    diagnostic = Mock()
    service = _service(client, diagnostic=diagnostic)

    result = service.run_checkin("student", "password", max_attempts=3, retry_delay=8)

    assert result.status == "data_error"
    assert result.attempts == 1
    assert client.submit_checkin_form.call_count == 1
    service._token_provider.assert_called_once_with("student", "password", 10)
    service._token_store.delete.assert_not_called()
    expected = call("签到状态确认失败（stage=confirm，认证会话失效）")
    assert diagnostic.call_args_list.count(expected) == 4
    output = "\n".join(item.args[0] for item in diagnostic.call_args_list)
    assert "token-secret" not in output
    assert "response-secret" not in output


def test_ambiguous_submit_with_confirm_session_expiry_remains_single_post():
    client = _pending_client()
    client.get_transition.side_effect = [
        Transition("record", "form", "未签到"),
        *([SessionExpiredError("cookie-secret")] * 4),
    ]
    client.submit_checkin_form.side_effect = requests.Timeout("ticket-secret")
    diagnostic = Mock()
    service = _service(client, diagnostic=diagnostic)

    result = service.run_checkin("student", "password", max_attempts=3, retry_delay=8)

    assert result.status == "data_error"
    assert result.attempts == 1
    assert client.submit_checkin_form.call_count == 1
    service._token_provider.assert_called_once_with("student", "password", 10)
    service._token_store.delete.assert_not_called()
    assert call("签到失败（stage=submit，请求超时）") in diagnostic.call_args_list
    expected = call("签到状态确认失败（stage=confirm，认证会话失效）")
    assert diagnostic.call_args_list.count(expected) == 4
    output = "\n".join(item.args[0] for item in diagnostic.call_args_list)
    assert "ticket-secret" not in output
    assert "cookie-secret" not in output


@pytest.mark.parametrize(
    ("confirm_error", "classification"),
    [
        (requests.Timeout("token-secret"), "请求超时"),
        (requests.ConnectionError("cookie-secret"), "连接异常"),
        (_http_error(503, "ticket-secret"), "HTTP 503"),
        (ApiSchemaError("form-secret"), "数据结构异常"),
        (json.JSONDecodeError("token-secret", "", 0), "JSON 解析异常"),
    ],
)
def test_confirm_stage_classifies_failures_without_resubmitting(confirm_error: Exception, classification: str):
    client = _pending_client()
    client.get_transition.side_effect = [
        Transition("record", "form", "未签到"),
        *([confirm_error] * 4),
    ]
    diagnostic = Mock()

    result = _service(client, diagnostic=diagnostic).run_checkin("student", "password", max_attempts=3, retry_delay=8)

    assert result.status == "data_error"
    assert result.attempts == 1
    assert client.submit_checkin_form.call_count == 1
    expected = call(f"签到状态确认失败（stage=confirm，{classification}）")
    assert diagnostic.call_args_list.count(expected) == 4


@pytest.mark.parametrize(
    ("submit_error", "classification"),
    [
        (ApiSchemaError("form-secret"), "数据结构异常"),
        (json.JSONDecodeError("token-secret", "", 0), "JSON 解析异常"),
        (ValueError("student-20260000000"), "数据解析异常"),
    ],
)
def test_submit_data_failure_keeps_existing_no_retry_no_readback_semantics(
    submit_error: Exception, classification: str
):
    client = _pending_client()
    client.submit_checkin_form.side_effect = submit_error
    diagnostic = Mock()

    result = _service(client, diagnostic=diagnostic).run_checkin("student", "password", max_attempts=3, retry_delay=8)

    assert result.status == "data_error"
    assert result.attempts == 1
    assert client.submit_checkin_form.call_count == 1
    assert client.get_transition.call_count == 1
    assert diagnostic.call_args_list == [call(f"签到失败（stage=submit，{classification}）")]


def test_pre_submit_timeout_keeps_three_attempts_and_exponential_backoff():
    client = _pending_client()
    client.get_leave_record_set.side_effect = requests.Timeout("secret")
    diagnostic = Mock()
    sleep = Mock()

    result = _service(client, diagnostic=diagnostic, sleep=sleep).run_checkin(
        "student", "password", max_attempts=3, retry_delay=8
    )

    assert result.status == "data_error"
    assert result.attempts == 3
    assert sleep.call_args_list == [call(8), call(16)]


def test_diagnostics_never_include_exception_or_payload_secrets():
    secrets = [
        "student-20260000000",
        "password-secret",
        "token-secret",
        "ticket-secret",
        "cookie-secret",
        "106.123456",
        "29.123456",
        "building-secret",
        "form-secret",
        "https://example.invalid/?token=secret",
    ]
    secret_blob = " ".join(secrets)
    client = _pending_client()
    client.get_student_id.return_value = "student-20260000000"
    client.get_student_profile.return_value = StudentProfile("student-20260000000")
    client.submit_checkin_form.return_value = {"code": secret_blob, "message": secret_blob}
    client.get_transition.side_effect = [Transition("record", "form", "未签到")] * 5
    diagnostic = Mock()

    result = _service(client, diagnostic=diagnostic).run_checkin("student-20260000000", "password-secret")

    assert result.status == "data_error"

    exception_client = _pending_client()
    exception_client.get_student_id.return_value = "student-20260000000"
    exception_client.get_leave_record_set.side_effect = requests.Timeout(secret_blob)
    _service(exception_client, diagnostic=diagnostic).run_checkin("student-20260000000", "password-secret")

    output = "\n".join(item.args[0] for item in diagnostic.call_args_list)
    for secret in secrets:
        assert secret not in output


def test_probe_keeps_read_only_semantics_with_safe_stage_diagnostic():
    client = _pending_client()
    client.get_student_profile.side_effect = requests.ConnectionError("token-secret")
    diagnostic = Mock()

    result = _service(client, diagnostic=diagnostic).run_probe("student", "password")

    assert result.status == "data_error"
    assert result.attempts == 1
    assert diagnostic.call_args_list == [call("签到检测失败（stage=student_profile，连接异常）")]
    client.submit_checkin_form.assert_not_called()
