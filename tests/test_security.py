import pytest

from swu_checkin.get_info import debug_print, mask_sensitive_data, safe_print


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
