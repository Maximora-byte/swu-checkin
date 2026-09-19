from unittest.mock import Mock

import pytest
import requests

from swu_checkin.auth import AuthError, AuthFailureReason, auth_failure_status
from swu_checkin.get_info import _get_token, get_token, recognize_captcha, validate_login_result_text
from swu_checkin.oauth_flow import OAuthDiscoveryError
from swu_checkin.service import CheckinService
from swu_checkin.status import CheckinStatus


def test_auth_failure_reason_taxonomy_is_complete():
    assert {reason.value for reason in AuthFailureReason} == {
        "credential_rejected",
        "captcha_failed",
        "network_error",
        "login_page_changed",
        "oauth_flow_changed",
        "ticket_failed",
        "token_exchange_failed",
        "unknown",
    }


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (AuthFailureReason.CREDENTIAL_REJECTED, CheckinStatus.LOGIN_FAILED),
        (AuthFailureReason.CAPTCHA_FAILED, CheckinStatus.LOGIN_FAILED),
        (AuthFailureReason.NETWORK_ERROR, CheckinStatus.DATA_ERROR),
        (AuthFailureReason.LOGIN_PAGE_CHANGED, CheckinStatus.DATA_ERROR),
        (AuthFailureReason.OAUTH_FLOW_CHANGED, CheckinStatus.DATA_ERROR),
        (AuthFailureReason.TICKET_FAILED, CheckinStatus.DATA_ERROR),
        (AuthFailureReason.TOKEN_EXCHANGE_FAILED, CheckinStatus.DATA_ERROR),
        (AuthFailureReason.UNKNOWN, CheckinStatus.DATA_ERROR),
    ],
)
def test_auth_failures_map_to_unchanged_public_statuses(reason: AuthFailureReason, expected: CheckinStatus):
    assert auth_failure_status(reason) is expected


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (AuthFailureReason.CREDENTIAL_REJECTED, CheckinStatus.LOGIN_FAILED),
        (AuthFailureReason.CAPTCHA_FAILED, CheckinStatus.LOGIN_FAILED),
        (AuthFailureReason.NETWORK_ERROR, CheckinStatus.DATA_ERROR),
        (AuthFailureReason.LOGIN_PAGE_CHANGED, CheckinStatus.DATA_ERROR),
        (AuthFailureReason.OAUTH_FLOW_CHANGED, CheckinStatus.DATA_ERROR),
        (AuthFailureReason.TICKET_FAILED, CheckinStatus.DATA_ERROR),
        (AuthFailureReason.TOKEN_EXCHANGE_FAILED, CheckinStatus.DATA_ERROR),
        (AuthFailureReason.UNKNOWN, CheckinStatus.DATA_ERROR),
    ],
)
def test_service_maps_auth_error_without_changing_legacy_status(reason: AuthFailureReason, expected: CheckinStatus):
    store = Mock()
    store.get.return_value = None
    service = CheckinService(
        token_provider=Mock(side_effect=AuthError(reason)),
        token_store=store,
    )

    assert service.check_in_once("student", "password") is expected


def test_network_timeout_is_classified(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "swu_checkin.get_info.discover_login_flow",
        Mock(side_effect=requests.Timeout("token=t password=p ticket=t state=s")),
    )

    with pytest.raises(AuthError) as caught:
        _get_token("student", "password", timeout=1, max_login_attempts=1)

    assert caught.value.reason is AuthFailureReason.NETWORK_ERROR
    assert "token=" not in str(caught.value)
    assert "password=" not in str(caught.value)


def test_auth_network_retry_has_one_full_login_per_outer_attempt(monkeypatch: pytest.MonkeyPatch):
    discovery = Mock(side_effect=requests.Timeout("timeout"))
    monkeypatch.setattr("swu_checkin.get_info.discover_login_flow", discovery)
    store = Mock()
    store.get.return_value = None
    sleep = Mock()
    service = CheckinService(token_store=store, sleep=sleep)

    result = service.run_checkin("student", "password", max_attempts=3, retry_delay=2)

    assert result.attempts == 3
    assert discovery.call_count == 3
    assert sleep.call_count == 2


@pytest.mark.parametrize(
    "reason",
    [
        AuthFailureReason.CREDENTIAL_REJECTED,
        AuthFailureReason.CAPTCHA_FAILED,
        AuthFailureReason.TICKET_FAILED,
        AuthFailureReason.TOKEN_EXCHANGE_FAILED,
        AuthFailureReason.UNKNOWN,
    ],
)
def test_terminal_auth_failure_does_not_repeat_full_login(
    monkeypatch: pytest.MonkeyPatch,
    reason: AuthFailureReason,
):
    discovery = Mock(side_effect=AuthError(reason))
    monkeypatch.setattr("swu_checkin.get_info.discover_login_flow", discovery)

    with pytest.raises(AuthError) as caught:
        _get_token("student", "password", timeout=1, max_login_attempts=3)

    assert caught.value.reason is reason
    discovery.assert_called_once()


def _captcha_response(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.url = "https://idm.swu.edu.cn/am/validate.code"
    response._content = b"synthetic-image"
    return response


@pytest.mark.parametrize("status_code", [408, 425, 429, 503])
def test_transient_captcha_http_status_is_network_error(status_code: int):
    session = Mock()
    session.get.return_value = _captcha_response(status_code)

    with pytest.raises(AuthError) as caught:
        recognize_captcha(session, "https://idm.swu.edu.cn/am/validate.code", timeout=1, max_attempts=1)

    assert caught.value.reason is AuthFailureReason.NETWORK_ERROR


@pytest.mark.parametrize("error", [requests.Timeout("timeout"), requests.ConnectionError("reset")])
def test_captcha_transport_failure_is_network_error(error: requests.RequestException):
    session = Mock()
    session.get.side_effect = error

    with pytest.raises(AuthError) as caught:
        recognize_captcha(session, "https://idm.swu.edu.cn/am/validate.code", timeout=1, max_attempts=1)

    assert caught.value.reason is AuthFailureReason.NETWORK_ERROR


def test_captcha_ocr_exhaustion_remains_captcha_failed(monkeypatch: pytest.MonkeyPatch):
    session = Mock()
    session.get.return_value = _captcha_response(200)
    ocr = Mock()
    ocr.classification.return_value = ""
    monkeypatch.setattr("swu_checkin.get_info.ddddocr.DdddOcr", Mock(return_value=ocr))
    monkeypatch.setattr("swu_checkin.get_info.Image.open", Mock(return_value=object()))
    monkeypatch.setattr("swu_checkin.get_info.time.sleep", Mock())

    with pytest.raises(AuthError) as caught:
        recognize_captcha(session, "https://idm.swu.edu.cn/am/validate.code", timeout=1, max_attempts=3)

    assert caught.value.reason is AuthFailureReason.CAPTCHA_FAILED
    assert session.get.call_count == 3


def test_login_page_change_is_classified(monkeypatch: pytest.MonkeyPatch):
    page_error = OAuthDiscoveryError(
        "missing hidden input state=secret",
        reason=AuthFailureReason.LOGIN_PAGE_CHANGED,
    )
    discovery = Mock(side_effect=page_error)
    monkeypatch.setattr("swu_checkin.get_info.discover_login_flow", discovery)

    with pytest.raises(AuthError) as caught:
        _get_token("student", "password", timeout=1, max_login_attempts=3)

    assert caught.value.reason is AuthFailureReason.LOGIN_PAGE_CHANGED
    assert "state=secret" not in str(caught.value)
    discovery.assert_called_once()


def test_explicit_captcha_rejection_is_classified():
    with pytest.raises(AuthError) as caught:
        validate_login_result_text("<div>验证码错误</div>")

    assert caught.value.reason is AuthFailureReason.CAPTCHA_FAILED


def test_explicit_credential_rejection_is_not_a_network_error():
    with pytest.raises(AuthError) as caught:
        validate_login_result_text("<div>用户名或密码错误</div>")

    assert caught.value.reason is AuthFailureReason.CREDENTIAL_REJECTED


def test_auth_error_discards_unreviewed_sensitive_message():
    sensitive_values = (
        "password-secret",
        "token-secret",
        "ticket-secret",
        "state-secret",
        "captcha-secret",
        "https://example.invalid/?code=secret",
    )
    secrets = " ".join(sensitive_values)

    error = AuthError(AuthFailureReason.UNKNOWN, secrets)

    assert all(value not in str(error) for value in sensitive_values)
    assert str(error) == "认证过程发生未知错误"


def test_legacy_get_token_still_returns_empty_string_on_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "swu_checkin.get_info.authenticate_token",
        Mock(side_effect=AuthError(AuthFailureReason.CREDENTIAL_REJECTED)),
    )

    assert get_token("student", "wrong-password") == ""
