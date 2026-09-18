import json

import pytest

from swu_checkin import cli
from swu_checkin.models import CheckinResult
from swu_checkin.status import CheckinStatus


def _result(status: CheckinStatus, *, mode: str = "checkin", attempts: int = 1) -> CheckinResult:
    return CheckinResult.from_status(status, attempts=attempts, duration_ms=0, mode=mode)


@pytest.fixture(autouse=True)
def credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SWUDK_USERNAME", "student")
    monkeypatch.setenv("SWUDK_PASSWORD", "password")
    monkeypatch.delenv("SWUDK_PROBE_ONLY", raising=False)
    monkeypatch.delenv("SWUDK_STATUS_FILE", raising=False)


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [
        (CheckinStatus.NO_TASK, 1),
        (CheckinStatus.SUCCESS, 0),
        (CheckinStatus.ALREADY_CHECKED_IN, 0),
        (CheckinStatus.LOGIN_FAILED, 1),
        (CheckinStatus.DATA_ERROR, 1),
        (CheckinStatus.ON_LEAVE, 0),
    ],
)
def test_checkin_exit_codes(monkeypatch: pytest.MonkeyPatch, status: CheckinStatus, expected_exit: int):
    monkeypatch.setattr(cli, "run_checkin", lambda *_args, **_kwargs: _result(status))

    assert cli.main([]) == expected_exit


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [
        (CheckinStatus.NO_TASK, 0),
        (CheckinStatus.ALREADY_CHECKED_IN, 0),
        (CheckinStatus.LOGIN_FAILED, 1),
        (CheckinStatus.DATA_ERROR, 1),
        (CheckinStatus.ON_LEAVE, 0),
        (CheckinStatus.PROBE_PENDING, 0),
    ],
)
def test_probe_exit_codes(monkeypatch: pytest.MonkeyPatch, status: CheckinStatus, expected_exit: int):
    monkeypatch.setattr(cli, "run_probe", lambda *_args, **_kwargs: _result(status, mode="probe"))

    assert cli.main(["--probe"]) == expected_exit


@pytest.mark.parametrize(
    ("status", "mode"),
    [
        (CheckinStatus.SUCCESS, "checkin"),
        (CheckinStatus.ALREADY_CHECKED_IN, "checkin"),
        (CheckinStatus.ON_LEAVE, "checkin"),
        (CheckinStatus.NO_TASK, "checkin"),
        (CheckinStatus.LOGIN_FAILED, "checkin"),
        (CheckinStatus.DATA_ERROR, "checkin"),
        (CheckinStatus.PROBE_PENDING, "probe"),
    ],
)
def test_json_cli_emits_exactly_one_document(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: CheckinStatus,
    mode: str,
):
    def fake_run(*_args, **_kwargs):
        print("第 1/3 次失败（测试诊断）")
        return _result(status, mode=mode)

    monkeypatch.setattr(cli, "run_probe" if mode == "probe" else "run_checkin", fake_run)
    arguments = ["--json", "--probe"] if mode == "probe" else ["--json"]

    cli.main(arguments)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert captured.out.count("\n") == 1
    assert payload["schema_version"] == 1
    assert payload["code"] == int(status)
    assert payload["mode"] == mode
    assert "第 1/3 次失败" not in captured.out
    assert "第 1/3 次失败" in captured.err


def test_probe_environment_variable_matches_flag(monkeypatch: pytest.MonkeyPatch):
    def probe(*_args, **_kwargs):
        return _result(CheckinStatus.PROBE_PENDING, mode="probe")

    monkeypatch.setattr(cli, "run_probe", probe)
    monkeypatch.setenv("SWUDK_PROBE_ONLY", "1")

    assert cli.main([]) == 0


def test_json_unexpected_error_does_not_leak_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    secret = "password-token-ticket-state-captcha-code"
    monkeypatch.setattr(cli, "run_checkin", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(secret)))

    assert cli.main(["--json"]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "data_error"
    assert secret not in captured.out + captured.err
    assert "RuntimeError" in captured.err
