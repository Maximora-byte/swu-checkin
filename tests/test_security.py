from unittest.mock import Mock

import pytest
import requests

from swu_checkin.get_info import (
    debug_print,
    mask_sensitive_data,
    safe_print,
    validate_cas_callback_response,
    validate_idm_login_response,
)


def test_safe_print_suppresses_sensitive_values(capsys: pytest.CaptureFixture[str]):
    safe_print("获取到 token: abc123xyz")
    safe_print("ticket=ST-secret")
    safe_print("token 交换失败：HTTPError")
    safe_print("这是普通日志")

    output = capsys.readouterr().out
    assert "abc123xyz" not in output
    assert "ST-secret" not in output
    assert "token 交换失败：HTTPError" in output
    assert "普通日志" in output


def test_debug_mode_never_bypasses_sensitive_filter(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("SWUDK_DEBUG_CREDENTIALS", "1")

    debug_print("普通诊断信息")
    debug_print("token=abc123")
    debug_print("password=secret")
    debug_print("回调 URL: https://example.invalid/?ticket=secret")

    output = capsys.readouterr().out
    assert "[DEBUG] 普通诊断信息" in output
    assert "abc123" not in output
    assert "secret" not in output
    assert "example.invalid" not in output


def test_debug_output_disabled_by_default(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.delenv("SWUDK_DEBUG_CREDENTIALS", raising=False)

    debug_print("普通诊断信息")

    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("value", "show_chars", "expected_prefix", "expected_suffix"),
    [
        ("abcdefghijklmnopqrstuvwxyz123456", 4, "ab", "56"),
        ("eyJhbGciOiJIUzI1NiJ9.payload", 8, "eyJh", "load"),
    ],
)
def test_mask_sensitive_data(value: str, show_chars: int, expected_prefix: str, expected_suffix: str):
    masked = mask_sensitive_data(value, show_chars=show_chars)

    assert masked.startswith(expected_prefix)
    assert masked.endswith(expected_suffix)
    assert "*" in masked
    assert masked != value


def test_short_and_empty_values_are_fully_masked():
    assert mask_sensitive_data("abc") == "****"
    assert mask_sensitive_data("") == "****"


@pytest.mark.parametrize(
    "url",
    [
        "https://uaaap.swu.edu.cn/cas/oauth2.0/callbackAuthorize?ticket=ST-test",
        "https://uaaap.swu.edu.cn:443/cas/oauth2.0/callbackAuthorize?ticket=ST-test",
    ],
)
def test_ticket_bearing_swu_412_callback_is_accepted(url: str):
    response = Mock(status_code=412, url=url)

    validate_idm_login_response(response)

    response.raise_for_status.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "https://uaaap.swu.edu.cn/cas/oauth2.0/callbackAuthorize",
        "http://uaaap.swu.edu.cn/cas/oauth2.0/callbackAuthorize?ticket=ST-test",
        "https://example.invalid/cas/oauth2.0/callbackAuthorize?ticket=ST-test",
        "https://uaaap.swu.edu.cn/unexpected?ticket=ST-test",
        "https://uaaap.swu.edu.cn:444/cas/oauth2.0/callbackAuthorize?ticket=ST-test",
    ],
)
def test_untrusted_or_ticketless_412_callback_is_rejected(url: str):
    response = Mock(status_code=412, url=url)
    response.raise_for_status.side_effect = requests.HTTPError("412")

    with pytest.raises(requests.HTTPError):
        validate_idm_login_response(response)


@pytest.mark.parametrize(
    "url",
    [
        "https://of.swu.edu.cn/&ticket=ST-test",
        "https://of.swu.edu.cn:443/&ticket=ST-test",
    ],
)
def test_ticket_bearing_swu_404_landing_page_is_accepted(url: str):
    response = Mock(status_code=404, url=url)

    validate_cas_callback_response(response)

    response.raise_for_status.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "https://of.swu.edu.cn/",
        "http://of.swu.edu.cn/&ticket=ST-test",
        "https://example.invalid/&ticket=ST-test",
        "https://of.swu.edu.cn/unexpected?ticket=ST-test",
        "https://of.swu.edu.cn/cas/oauth/callback?ticket=ST-test",
        "https://of.swu.edu.cn:444/&ticket=ST-test",
    ],
)
def test_untrusted_or_ticketless_404_landing_page_is_rejected(url: str):
    response = Mock(status_code=404, url=url)
    response.raise_for_status.side_effect = requests.HTTPError("404")

    with pytest.raises(requests.HTTPError):
        validate_cas_callback_response(response)
