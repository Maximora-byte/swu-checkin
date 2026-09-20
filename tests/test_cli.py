import json

import pytest

from swu_checkin import cli
from swu_checkin.models import CheckinResult
from swu_checkin.runtime_lock import RuntimeLock
from swu_checkin.status import CheckinStatus


def _result(status: CheckinStatus, *, mode: str = "checkin", attempts: int = 1) -> CheckinResult:
    return CheckinResult.from_status(status, attempts=attempts, duration_ms=0, mode=mode)


@pytest.fixture(autouse=True)
def credentials(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("SWUDK_USERNAME", "student")
    monkeypatch.setenv("SWUDK_PASSWORD", "password")
    monkeypatch.setenv("SWUDK_LOCK_FILE", str(tmp_path / "checkin.lock"))
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


@pytest.mark.parametrize("arguments", [[], ["run"], ["run", "--json"]])
def test_busy_formal_run_skips_before_credentials_network_and_status(monkeypatch, tmp_path, capsys, arguments):
    lock_path = tmp_path / "checkin.lock"
    status_path = tmp_path / "status.json"
    monkeypatch.setenv("SWUDK_LOCK_FILE", str(lock_path))
    monkeypatch.setenv("SWUDK_STATUS_FILE", str(status_path))
    monkeypatch.setenv("SWUDK_PASSWORD", "secret-password-token")
    monkeypatch.setattr(cli, "_credentials", lambda **_kwargs: pytest.fail("busy run must not read credentials"))
    monkeypatch.setattr(cli, "run_checkin", lambda *_args, **_kwargs: pytest.fail("busy run must not use SWU"))
    monkeypatch.setattr(
        cli, "record_run_status", lambda *_args, **_kwargs: pytest.fail("busy run must not write status")
    )

    with RuntimeLock(lock_path):
        assert cli.main(arguments) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"{cli.LOCK_BUSY_MESSAGE}\n"
    assert "secret-password-token" not in captured.err
    assert not status_path.exists()


def test_formal_run_acquires_lock_before_credentials(monkeypatch, tmp_path):
    lock_path = tmp_path / "checkin.lock"
    monkeypatch.setenv("SWUDK_LOCK_FILE", str(lock_path))

    def credentials_while_locked(*, json_output):
        assert json_output is False
        contender = RuntimeLock(lock_path)
        assert contender.acquire() is False
        return "student", "password"

    monkeypatch.setattr(cli, "_credentials", credentials_while_locked)
    monkeypatch.setattr(cli, "run_checkin", lambda *_args, **_kwargs: _result(CheckinStatus.SUCCESS))

    assert cli.main(["run"]) == 0


def test_formal_run_releases_lock_after_internal_exception(monkeypatch, tmp_path):
    lock_path = tmp_path / "checkin.lock"
    monkeypatch.setenv("SWUDK_LOCK_FILE", str(lock_path))
    monkeypatch.setattr(cli, "run_checkin", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("failure")))

    assert cli.main(["run"]) == 1
    contender = RuntimeLock(lock_path)
    assert contender.acquire() is True
    contender.release()


def test_probe_runs_while_formal_lock_is_held(monkeypatch, tmp_path):
    lock_path = tmp_path / "checkin.lock"
    monkeypatch.setenv("SWUDK_LOCK_FILE", str(lock_path))
    monkeypatch.setattr(
        cli,
        "run_probe",
        lambda *_args, **_kwargs: _result(CheckinStatus.PROBE_PENDING, mode="probe"),
    )

    with RuntimeLock(lock_path):
        assert cli.main(["probe"]) == 0
