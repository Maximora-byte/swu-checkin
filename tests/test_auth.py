from unittest.mock import Mock

import pytest
import requests

from swu_checkin.auth import AuthError, AuthFailureReason, auth_failure_status
from swu_checkin.get_info import _get_token, get_token, validate_login_result_text
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


def test_login_page_change_is_classified(monkeypatch: pytest.MonkeyPatch):
    page_error = OAuthDiscoveryError(
        "missing hidden input state=secret",
        reason=AuthFailureReason.LOGIN_PAGE_CHANGED,
    )
    monkeypatch.setattr("swu_checkin.get_info.discover_login_flow", Mock(side_effect=page_error))

    with pytest.raises(AuthError) as caught:
        _get_token("student", "password", timeout=1, max_login_attempts=1)

    assert caught.value.reason is AuthFailureReason.LOGIN_PAGE_CHANGED
    assert "state=secret" not in str(caught.value)


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
