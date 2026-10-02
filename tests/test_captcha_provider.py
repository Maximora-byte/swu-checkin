"""Offline coverage of the image-only seam used by manual front ends."""

import json
import os
import subprocess
import sys
from functools import partial
from pathlib import Path
from unittest.mock import Mock, call

import pytest
import requests

from swu_checkin import get_info
from swu_checkin.auth import AuthError, AuthFailureReason
from swu_checkin.oauth_flow import OAuthFlow
from swu_checkin.service import CheckinService

CAPTCHA_URL = "https://idm.swu.edu.cn/am/validate.code"
LOGIN_URL = "https://idm.swu.edu.cn/am/UI/Login"
CALLBACK_URL = "https://of.swu.edu.cn/cas/oauth/callback/SWU_CAS2_FEDERAL"


def _response(url: str, content: bytes = b"", status: int = 200) -> requests.Response:
    response = requests.Response()
    response.url = url
    response.status_code = status
    response._content = content
    response.encoding = "utf-8"
    return response


@pytest.fixture
def login(monkeypatch):
    """Only transport/discovery are synthetic; post-discovery checks stay real."""
    session = Mock(spec=requests.Session)
    session.cookies = requests.cookies.RequestsCookieJar()
    flow = OAuthFlow(
        login_page_url=LOGIN_URL,
        form_action=LOGIN_URL,
        hidden_fields={"goto": "synthetic-goto", "serverNonce": "synthetic-nonce"},
        state="synthetic-state-0123456789",
        code_random="synthetic-random",
        captcha_url=CAPTCHA_URL,
        cas_callback_url=CALLBACK_URL,
    )
    factory = Mock(return_value=session)
    discovery = Mock(return_value=flow)
    ocr = Mock(side_effect=AssertionError("manual authentication must not use OCR"))
    sleep = Mock()
    monkeypatch.setattr(get_info.requests, "Session", factory)
    monkeypatch.setattr(get_info, "discover_login_flow", discovery)
    monkeypatch.setattr(get_info, "recognize_captcha", ocr)
    monkeypatch.setattr(get_info.time, "sleep", sleep)
    session.post.return_value = _response(
        "https://uaaap.swu.edu.cn/cas/oauth2.0/callbackAuthorize?ticket=synthetic-identity", status=412
    )
    challenges = []

    def respond(url, **kwargs):
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] == 7
        if url == CAPTCHA_URL:
            image = f"synthetic-image-{len(challenges) + 1}".encode()
            challenges.append(image)
            session.cookies.set("challenge", image.decode())
            return _response(url, image)
        if url.startswith(CALLBACK_URL + "?"):
            return _response("https://of.swu.edu.cn/&ticket=synthetic-token-ticket", status=404)
        assert url == get_info.TOKEN_EXCHANGE_URL
        assert kwargs["params"] == {"token": "synthetic-token-ticket", "remember": "true"}
        return _response(url, json.dumps({"data": "synthetic-token"}).encode())

    session.get.side_effect = respond
    return session, discovery, factory, ocr, sleep, challenges


def test_core_import_and_manual_challenge_work_without_native_ocr():
    script = """
import importlib.abc
import os
import sys

forbidden = {"ddddocr", "PIL", "onnxruntime", "numpy", "cv2"}
class RejectOCR(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in forbidden:
            raise AssertionError("OCR import attempted: " + fullname)
sys.meta_path.insert(0, RejectOCR())
from swu_checkin import get_info, service, cli, desktop_backend
from unittest.mock import Mock
import requests
def response(url, content=b"", status=200):
    result = requests.Response()
    result.url, result._content, result.status_code = url, content, status
    return result
from swu_checkin.oauth_flow import OAuthFlow
flow = OAuthFlow(
    login_page_url="https://idm.swu.edu.cn/am/UI/Login",
    form_action="https://idm.swu.edu.cn/am/UI/Login",
    hidden_fields={"goto": "synthetic-goto"},
    state="synthetic-state-0123456789",
    code_random="synthetic-random",
    captcha_url="https://idm.swu.edu.cn/am/validate.code",
    cas_callback_url="https://of.swu.edu.cn/cas/oauth/callback/SWU_CAS2_FEDERAL",
)
session = Mock()
session.get.side_effect = [
    response(flow.captcha_url, b"synthetic-image"),
    response("https://of.swu.edu.cn/&ticket=synthetic-token-ticket", status=404),
    response(get_info.TOKEN_EXCHANGE_URL, b'{"data": "synthetic-token"}'),
]
session.post.return_value = response(
    "https://uaaap.swu.edu.cn/cas/oauth2.0/callbackAuthorize?ticket=synthetic-identity", status=412
)
get_info.requests.Session = Mock(return_value=session)
get_info.discover_login_flow = Mock(return_value=flow)
provider = Mock(return_value="Ab12")
assert get_info.authenticate_token("synthetic-user", "synthetic-password", 7, captcha_provider=provider) == "synthetic-token"
provider.assert_called_once_with(b"synthetic-image")
assert os.environ["ORT_DISABLE_TELEMETRY"] == "1"
assert not {name.split(".")[0] for name in sys.modules} & forbidden
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_provider_uses_current_challenge_and_same_login_session(login):
    session, discovery, factory, ocr, _sleep, challenges = login

    def answer(image):
        assert image == b"synthetic-image-1"
        assert session.cookies["challenge"] == image.decode()
        return "Ab12"

    provider = Mock(side_effect=answer)
    assert get_info.authenticate_token("synthetic-user", "synthetic-password", 7, captcha_provider=provider) == (
        "synthetic-token"
    )

    factory.assert_called_once_with()
    discovery.assert_called_once_with(session, 7)
    provider.assert_called_once_with(challenges[0])
    ocr.assert_not_called()
    session.post.assert_called_once()
    post = session.post.call_args
    assert post.args == (LOGIN_URL,)
    assert post.kwargs["timeout"] == 7
    assert post.kwargs["allow_redirects"] is False
    assert post.kwargs["data"]["validateCode"] == "Ab12"
    assert post.kwargs["data"]["serverNonce"] == "synthetic-nonce"
    assert session.get.call_args_list[0] == call(CAPTCHA_URL, timeout=7, allow_redirects=False)
    callback = session.get.call_args_list[1].args[0]
    assert "state=synthetic-state-0123456789" in callback
    assert len(challenges) == 1


@pytest.mark.parametrize("answer", [None, "", "ab", "    ", "A\n12", "ＡＢ１２", "A-12", b"Ab12", 1234])
def test_invalid_or_cancelled_answer_stops_before_login(login, answer):
    session, discovery, _factory, ocr, sleep, challenges = login
    provider = Mock(return_value=answer)
    with pytest.raises(AuthError) as caught:
        get_info.authenticate_token("synthetic-user", "synthetic-password", 7, captcha_provider=provider)

    assert caught.value.reason is AuthFailureReason.CAPTCHA_FAILED
    assert len(challenges) == 1
    assert discovery.call_count == 1
    assert provider.call_count == 1
    session.post.assert_not_called()
    ocr.assert_not_called()
    sleep.assert_not_called()


@pytest.mark.parametrize("error_type", [TimeoutError, requests.Timeout, RuntimeError, ValueError])
def test_provider_exception_is_terminal_and_sanitized(login, error_type, monkeypatch, capsys):
    session, _discovery, _factory, ocr, sleep, challenges = login
    monkeypatch.setenv("SWUDK_DEBUG_CREDENTIALS", "1")
    provider = Mock(side_effect=error_type("captcha=private-answer password=private-password"))
    with pytest.raises(AuthError) as caught:
        get_info.authenticate_token("synthetic-user", "synthetic-password", 7, captcha_provider=provider)

    assert caught.value.reason is AuthFailureReason.CAPTCHA_FAILED
    assert "private" not in str(caught.value)
    assert "private" not in capsys.readouterr().out
    assert len(challenges) == 1
    session.post.assert_not_called()
    ocr.assert_not_called()
    sleep.assert_not_called()


def test_server_captcha_rejection_requests_fresh_image_without_rediscovery(login):
    session, discovery, _factory, ocr, sleep, challenges = login
    success = session.post.return_value
    session.post.side_effect = [_response(LOGIN_URL, "验证码错误".encode()), success]
    provider = Mock(side_effect=["Ab12", "Cd34"])

    assert get_info.authenticate_token("synthetic-user", "synthetic-password", 7, captcha_provider=provider) == (
        "synthetic-token"
    )

    assert provider.call_args_list == [call(b"synthetic-image-1"), call(b"synthetic-image-2")]
    assert len(challenges) == 2
    discovery.assert_called_once_with(session, 7)
    assert [item.kwargs["data"]["validateCode"] for item in session.post.call_args_list] == ["Ab12", "Cd34"]
    sleep.assert_called_once_with(1)
    ocr.assert_not_called()


def test_server_captcha_rejections_remain_bounded_and_terminal(login):
    session, discovery, _factory, _ocr, sleep, challenges = login
    session.post.return_value = _response(LOGIN_URL, "验证码错误".encode())
    provider = Mock(return_value="Ab12")
    store = Mock()
    store.get.return_value = None
    outer_sleep = Mock()
    service = CheckinService(
        timeout=7,
        token_provider=partial(get_info.authenticate_token, captcha_provider=provider),
        token_store=store,
        sleep=outer_sleep,
    )

    result = service.run_checkin("synthetic-user", "synthetic-password", max_attempts=3)

    assert result.status == "login_failed"
    assert result.attempts == 1
    assert len(challenges) == 3
    assert provider.call_count == session.post.call_count == 3
    assert discovery.call_count == 1
    assert sleep.call_count == 2
    outer_sleep.assert_not_called()


@pytest.mark.parametrize("answer", [None, "", TimeoutError("private")])
def test_service_does_not_retry_provider_cancellation_or_failure(login, answer):
    session, discovery, _factory, _ocr, _sleep, challenges = login
    provider = Mock(side_effect=answer) if isinstance(answer, Exception) else Mock(return_value=answer)
    store = Mock()
    store.get.return_value = None
    outer_sleep = Mock()
    service = CheckinService(
        timeout=7,
        token_provider=partial(get_info.authenticate_token, captcha_provider=provider),
        token_store=store,
        sleep=outer_sleep,
    )
    result = service.run_checkin("synthetic-user", "synthetic-password", max_attempts=3)
    assert result.status == "login_failed"
    assert result.attempts == 1
    assert len(challenges) == discovery.call_count == 1
    session.post.assert_not_called()
    outer_sleep.assert_not_called()


@pytest.mark.parametrize(
    ("response_text", "reason"),
    [
        ("用户名或密码错误", AuthFailureReason.CREDENTIAL_REJECTED),
        ("unrecognized login response", AuthFailureReason.TICKET_FAILED),
    ],
)
def test_other_login_failures_do_not_refresh_challenge(login, response_text, reason):
    session, discovery, _factory, _ocr, sleep, challenges = login
    session.post.return_value = _response(LOGIN_URL, response_text.encode())
    provider = Mock(return_value="Ab12")
    with pytest.raises(AuthError) as caught:
        get_info.authenticate_token("synthetic-user", "synthetic-password", 7, captcha_provider=provider)
    assert caught.value.reason is reason
    assert len(challenges) == provider.call_count == session.post.call_count == discovery.call_count == 1
    sleep.assert_not_called()


def test_login_timeout_does_not_refresh_or_replay_manual_answer(login):
    session, discovery, _factory, _ocr, sleep, challenges = login
    session.post.side_effect = requests.Timeout("password=private")
    provider = Mock(return_value="Ab12")
    with pytest.raises(AuthError) as caught:
        get_info.authenticate_token("synthetic-user", "synthetic-password", 7, captcha_provider=provider)
    assert caught.value.reason is AuthFailureReason.NETWORK_ERROR
    assert len(challenges) == provider.call_count == session.post.call_count == discovery.call_count == 1
    sleep.assert_not_called()


def test_challenge_timeout_never_calls_provider_or_submits_form(login):
    session, discovery, _factory, ocr, sleep, _challenges = login
    session.get.side_effect = requests.Timeout("captcha=private")
    provider = Mock(return_value="Ab12")
    with pytest.raises(AuthError) as caught:
        get_info.authenticate_token("synthetic-user", "synthetic-password", 7, captcha_provider=provider)
    assert caught.value.reason is AuthFailureReason.NETWORK_ERROR
    session.get.assert_called_once_with(CAPTCHA_URL, timeout=7, allow_redirects=False)
    assert discovery.call_count == 1
    provider.assert_not_called()
    session.post.assert_not_called()
    ocr.assert_not_called()
    sleep.assert_not_called()


@pytest.mark.parametrize("status", [204, 302, 400, 403, 404, 408, 425, 429, 500, 503])
def test_non_200_challenge_never_reaches_provider(login, status):
    session, _discovery, _factory, _ocr, _sleep, _challenges = login
    session.get.side_effect = None
    session.get.return_value = _response(CAPTCHA_URL, b"untrusted-challenge", status)
    session.get.return_value.headers["Location"] = "https://outside.invalid/collect"
    provider = Mock(return_value="Ab12")
    with pytest.raises(AuthError) as caught:
        get_info.authenticate_token("synthetic-user", "synthetic-password", 7, captcha_provider=provider)
    expected = (
        AuthFailureReason.NETWORK_ERROR
        if status in {408, 425, 429} or status >= 500
        else AuthFailureReason.OAUTH_FLOW_CHANGED
    )
    assert caught.value.reason is expected
    session.get.assert_called_once_with(CAPTCHA_URL, timeout=7, allow_redirects=False)
    provider.assert_not_called()
    session.post.assert_not_called()


def test_manual_answer_does_not_bypass_untrusted_login_redirect(login):
    session, _discovery, _factory, _ocr, _sleep, challenges = login
    response = _response(LOGIN_URL, status=302)
    response.headers["Location"] = "https://outside.invalid/collect?ticket=private"
    session.post.return_value = response
    with pytest.raises(AuthError) as caught:
        get_info.authenticate_token("synthetic-user", "synthetic-password", 7, captcha_provider=lambda _: "Ab12")
    assert caught.value.reason is AuthFailureReason.OAUTH_FLOW_CHANGED
    assert len(challenges) == session.get.call_count == session.post.call_count == 1


def test_legacy_wrapper_accepts_provider_and_keeps_empty_failure_result(login):
    session, _discovery, _factory, _ocr, _sleep, _challenges = login
    assert get_info.get_token("synthetic-user", "synthetic-password", 7, captcha_provider=lambda _: None) == ""
    session.post.assert_not_called()


def test_legacy_positional_authenticate_call_does_not_add_keyword(monkeypatch):
    authenticate = Mock(return_value="synthetic-token")
    monkeypatch.setattr(get_info, "authenticate_token", authenticate)
    assert get_info.get_token("synthetic-user", "synthetic-password", 7) == "synthetic-token"
    authenticate.assert_called_once_with("synthetic-user", "synthetic-password", 7)


def test_empty_challenge_stops_before_provider_or_login(login):
    session, _discovery, _factory, _ocr, _sleep, _challenges = login
    session.get.side_effect = None
    session.get.return_value = _response(CAPTCHA_URL)
    provider = Mock(return_value="Ab12")
    with pytest.raises(AuthError) as caught:
        get_info.authenticate_token("synthetic-user", "synthetic-password", 7, captcha_provider=provider)
    assert caught.value.reason is AuthFailureReason.CAPTCHA_FAILED
    provider.assert_not_called()
    session.post.assert_not_called()
