import json

import pytest

from swu_checkin import cli
from swu_checkin.models import CheckinResult
from swu_checkin.service import DoctorReport
from swu_checkin.status import CheckinStatus
from swu_checkin.storage import record_run_status


def _result(status: CheckinStatus, *, mode: str) -> CheckinResult:
    return CheckinResult.from_status(status, attempts=1, duration_ms=0, mode=mode)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SWUDK_USERNAME", raising=False)
    monkeypatch.delenv("SWUDK_PASSWORD", raising=False)
    monkeypatch.delenv("SWUDK_PROBE_ONLY", raising=False)
    monkeypatch.delenv("SWUDK_STATUS_FILE", raising=False)


def test_setup_uses_complete_read_only_diagnostics_and_never_prints_password(monkeypatch, capsys):
    password = "never-print-this-password"
    calls = []

    class FakeService:
        def __init__(self, *, timeout):
            assert timeout == 10

        def diagnose(self, username, supplied_password):
            calls.append((username, supplied_password))
            return DoctorReport(True, True, True, True, True)

    monkeypatch.setattr("builtins.input", lambda _prompt: "student")
    monkeypatch.setattr(cli, "getpass", lambda _prompt: password)
    monkeypatch.setattr(cli, "CheckinService", FakeService)
    monkeypatch.setattr(cli, "run_probe", lambda *_args, **_kwargs: pytest.fail("setup must use complete diagnostics"))
    monkeypatch.setattr(cli, "run_checkin", lambda *_args, **_kwargs: pytest.fail("setup must not check in"))

    assert cli.main(["setup"]) == 0

    captured = capsys.readouterr()
    assert calls == [("student", password)]
    assert "配置验证成功" in captured.out
    assert password not in captured.out + captured.err


def test_setup_unexpected_error_does_not_leak_password(monkeypatch, capsys):
    password = "never-print-this-password"
    monkeypatch.setattr("builtins.input", lambda _prompt: "student")
    monkeypatch.setattr(cli, "getpass", lambda _prompt: password)

    class FailingService:
        def __init__(self, *, timeout):
            assert timeout == 10

        def diagnose(self, *_args):
            raise RuntimeError(password)

    monkeypatch.setattr(cli, "CheckinService", FailingService)

    assert cli.main(["setup"]) == 1

    captured = capsys.readouterr()
    assert password not in captured.out + captured.err
    assert "RuntimeError" in captured.err


@pytest.mark.parametrize("failed_index", range(5))
def test_setup_requires_every_read_only_diagnostic(monkeypatch, failed_index, capsys):
    checks = [True, True, True, True, True]
    checks[failed_index] = False

    class FakeService:
        def __init__(self, *, timeout):
            assert timeout == 10

        def diagnose(self, *_args):
            return DoctorReport(*checks)

    monkeypatch.setattr("builtins.input", lambda _prompt: "student")
    monkeypatch.setattr(cli, "getpass", lambda _prompt: "password")
    monkeypatch.setattr(cli, "CheckinService", FakeService)

    assert cli.main(["setup"]) == 1
    assert "配置验证失败" in capsys.readouterr().out


def test_doctor_uses_read_only_service_and_prints_seven_checks(monkeypatch, capsys):
    class FakeService:
        def __init__(self, *, timeout):
            assert timeout == 10

        def diagnose(self, username, password):
            assert (username, password) == ("student", "password")
            return DoctorReport(True, True, True, True, True)

    monkeypatch.setenv("SWUDK_USERNAME", "student")
    monkeypatch.setenv("SWUDK_PASSWORD", "password")
    monkeypatch.setattr(cli, "CheckinService", FakeService)
    monkeypatch.setattr(cli, "run_checkin", lambda *_args, **_kwargs: pytest.fail("doctor must not check in"))

    assert cli.main(["doctor"]) == 0

    output = capsys.readouterr().out
    for label in (
        "Runtime",
        "Credentials",
        "SWU Authentication",
        "Leave API",
        "Student Profile",
        "Dormitory Schema",
        "Check-in API",
    ):
        assert label in output
    assert output.count("✓") == 7


def test_status_reads_local_file_without_network(monkeypatch, tmp_path, capsys):
    status_file = tmp_path / "status.json"
    record_run_status(str(status_file), CheckinStatus.SUCCESS)
    monkeypatch.setattr(cli, "run_checkin", lambda *_args, **_kwargs: pytest.fail("status must not use network"))
    monkeypatch.setattr(cli, "run_probe", lambda *_args, **_kwargs: pytest.fail("status must not use network"))
    monkeypatch.setattr(cli, "CheckinService", lambda *_args, **_kwargs: pytest.fail("status must not use service"))

    assert cli.main(["status", "--file", str(status_file)]) == 0

    output = capsys.readouterr().out
    assert "结果：成功" in output
    assert "[1] 签到成功" in output


def test_run_subcommand_reuses_formal_checkin_path(monkeypatch):
    calls = []
    monkeypatch.setenv("SWUDK_USERNAME", "student")
    monkeypatch.setenv("SWUDK_PASSWORD", "password")
    monkeypatch.setattr(
        cli,
        "run_checkin",
        lambda *args, **kwargs: calls.append((args, kwargs)) or _result(CheckinStatus.SUCCESS, mode="checkin"),
    )

    assert cli.main(["run"]) == 0
    assert calls and calls[0][0] == ("student", "password", 10)


def test_probe_only_environment_rejects_explicit_run_without_execution(monkeypatch, capsys):
    monkeypatch.setenv("SWUDK_PROBE_ONLY", "1")
    monkeypatch.setattr(cli, "run_checkin", lambda *_args, **_kwargs: pytest.fail("run must be blocked"))
    monkeypatch.setattr(cli, "run_probe", lambda *_args, **_kwargs: pytest.fail("run must not be downgraded"))

    assert cli.main(["run"]) != 0

    captured = capsys.readouterr()
    assert "拒绝执行正式签到" in captured.err


def test_probe_subcommand_reuses_read_only_path(monkeypatch):
    calls = []
    monkeypatch.setenv("SWUDK_USERNAME", "student")
    monkeypatch.setenv("SWUDK_PASSWORD", "password")
    monkeypatch.setattr(
        cli,
        "run_probe",
        lambda *args, **_kwargs: calls.append(args) or _result(CheckinStatus.PROBE_PENDING, mode="probe"),
    )
    monkeypatch.setattr(cli, "run_checkin", lambda *_args, **_kwargs: pytest.fail("probe must not check in"))

    assert cli.main(["probe"]) == 0
    assert calls == [("student", "password", 10)]


@pytest.mark.parametrize(("command", "mode"), [("run", "checkin"), ("probe", "probe")])
def test_subcommand_json_keeps_schema_v1(monkeypatch, capsys, command, mode):
    monkeypatch.setenv("SWUDK_USERNAME", "student")
    monkeypatch.setenv("SWUDK_PASSWORD", "password")
    result = _result(CheckinStatus.SUCCESS if mode == "checkin" else CheckinStatus.PROBE_PENDING, mode=mode)
    monkeypatch.setattr(cli, "run_checkin" if mode == "checkin" else "run_probe", lambda *_args, **_kwargs: result)

    assert cli.main([command, "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"schema_version", "mode", "status", "code", "message", "attempts", "duration_ms"}
    assert payload["schema_version"] == 1
    assert payload["mode"] == mode
