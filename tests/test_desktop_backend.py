"""Offline regression coverage for desktop storage, scheduling and safety boundaries."""

import base64
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import Mock
from xml.etree import ElementTree as ET

import pytest

from swu_checkin import desktop_backend as desktop
from swu_checkin.models import CheckinResult
from swu_checkin.runtime_lock import RuntimeLock, RuntimeLockBusy
from swu_checkin.status import CheckinStatus


class FakeProtector:
    """Opaque in-memory test cipher: no production credentials or DPAPI calls."""

    blobs = {}

    def protect(self, plaintext):
        blob = f"opaque-test-blob-{len(self.blobs)}".encode()
        self.blobs[blob] = plaintext
        return blob

    def unprotect(self, ciphertext):
        return self.blobs[ciphertext]


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop, "WindowsDpapiProtector", FakeProtector)
    monkeypatch.setattr(desktop.subprocess, "run", Mock(side_effect=AssertionError("Unexpected subprocess")))
    monkeypatch.setattr(desktop, "run_checkin", Mock(side_effect=AssertionError("Unexpected submission")))
    monkeypatch.setattr(desktop, "run_probe", Mock(side_effect=AssertionError("Unexpected network")))
    monkeypatch.setattr(desktop, "CheckinService", Mock(side_effect=AssertionError("Unexpected network")))
    monkeypatch.setenv("SWUDK_LOCK_FILE", str(tmp_path / "shared-cli.lock"))
    monkeypatch.delenv("SWUDK_PROBE_ONLY", raising=False)


@pytest.fixture
def backend(tmp_path):
    return desktop.DesktopBackend(tmp_path / "app")


def result(mode="checkin", status=None):
    status = (
        status if status is not None else (CheckinStatus.SUCCESS if mode == "checkin" else CheckinStatus.PROBE_PENDING)
    )
    return CheckinResult.from_status(status, attempts=1, duration_ms=12, mode=mode)


def config(backend, **values):
    backend.root.mkdir(parents=True, exist_ok=True)
    backend.config_path.write_text(json.dumps({"schema_version": 1, **values}), encoding="utf-8")


def command_mock(monkeypatch, backend, *, create_code=0, exists=True):
    calls = []
    deleted = False

    def command(executable, args):
        nonlocal deleted
        calls.append((executable, args))
        if executable == "whoami.exe":
            return SimpleNamespace(returncode=0, stdout='"TEST\\User","S-1-5-21-123"\n')
        if executable.endswith("powershell.exe"):
            script = base64.b64decode(args[-1]).decode("utf-16-le")
            present = desktop.LEGACY_TASK_NAME not in script and exists and not deleted
            return SimpleNamespace(returncode=0, stdout="SWU_TASK_EXISTS" if present else "SWU_TASK_ABSENT", stderr="")
        if args[0] == "/Delete":
            deleted = True
        if args[0] == "/Create":
            xml_path = Path(args[args.index("/XML") + 1])
            ET.fromstring(xml_path.read_bytes())
            return SimpleNamespace(returncode=create_code, stdout="")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(backend, "_system_command", command)
    monkeypatch.setattr(backend, "diagnose", Mock(return_value=True))
    monkeypatch.setattr(desktop.sys, "frozen", True, raising=False)
    return calls


def test_credentials_are_encrypted_and_roundtrip(backend):
    backend.save_credentials("  synthetic-user  ", "synthetic-password")
    assert backend.load_credentials() == ("synthetic-user", "synthetic-password")
    data = backend.credential_path.read_bytes()
    assert b"synthetic-user" not in data
    assert b"synthetic-password" not in data
    assert list(backend.root.iterdir()) == [backend.credential_path]


@pytest.mark.parametrize(("username", "password"), [("", "x"), ("  ", "x"), ("x", "")])
def test_empty_credentials_rejected(backend, username, password):
    with pytest.raises(desktop.DesktopError):
        backend.save_credentials(username, password)
    assert not backend.root.exists()


def test_atomic_credentials_replace_failure_preserves_old_ciphertext(backend, monkeypatch):
    backend.save_credentials("old", "old-secret")
    original = backend.credential_path.read_bytes()
    monkeypatch.setattr(desktop.os, "replace", Mock(side_effect=OSError("synthetic-secret")))
    with pytest.raises(desktop.DesktopError) as error:
        backend.save_credentials("new", "new-secret")
    assert "synthetic-secret" not in str(error.value)
    assert backend.credential_path.read_bytes() == original
    assert list(backend.root.iterdir()) == [backend.credential_path]


def test_failed_encryption_never_writes_plaintext(backend, monkeypatch):
    monkeypatch.setattr(FakeProtector, "protect", Mock(side_effect=ValueError("synthetic-password")))
    with pytest.raises(desktop.DesktopError) as error:
        backend.save_credentials("user", "synthetic-password")
    assert "synthetic-password" not in str(error.value)
    assert not backend.credential_path.exists()


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"schema_version": True, "username": "x", "password": "y"},
        {"schema_version": 1, "username": 4, "password": "x"},
    ],
)
def test_invalid_credential_payload_rejected(backend, payload):
    backend.root.mkdir()
    backend.credential_path.write_bytes(FakeProtector().protect(json.dumps(payload).encode()))
    with pytest.raises(desktop.DesktopError):
        backend.load_credentials()


def test_missing_and_corrupt_credentials(backend):
    assert backend.load_credentials() is None
    backend.root.mkdir()
    backend.credential_path.write_bytes(b"corrupt-ciphertext")
    with pytest.raises(desktop.DesktopError):
        backend.load_credentials()


@pytest.mark.parametrize("raw", ["{", "[]", '{"schema_version":2}', '{"schema_version":true}'])
def test_malformed_config_rejected(backend, raw):
    backend.root.mkdir()
    backend.config_path.write_text(raw)
    with pytest.raises(desktop.DesktopError):
        backend._read_config()


def test_task_xml_escapes_paths_and_has_beijing_daily_triggers():
    executable = '/test/app & "quoted"/checkin.exe'
    xml = ET.fromstring(desktop.task_xml(executable, "S-1-5-21-123", datetime(2026, 10, 1, 13, 30, tzinfo=UTC)))
    ns = {"t": desktop.TASK_NS}
    assert xml.findtext(".//t:Command", namespaces=ns) == executable
    assert xml.findtext(".//t:Arguments", namespaces=ns) == "--scheduled"
    assert xml.findtext(".//t:WorkingDirectory", namespaces=ns) == str(PureWindowsPath(executable).parent)
    assert xml.findtext(".//t:LogonType", namespaces=ns) == "InteractiveToken"
    assert xml.findtext(".//t:RunLevel", namespaces=ns) == "LeastPrivilege"
    assert xml.findtext(".//t:StartWhenAvailable", namespaces=ns) == "false"
    assert [node.text for node in xml.findall(".//t:StartBoundary", ns)] == [
        "2026-10-02T21:15:00+08:00",
        "2026-10-01T21:45:00+08:00",
    ]
    assert [node.text for node in xml.findall(".//t:DaysInterval", ns)] == ["1", "1"]


def test_schedule_defaults_off(backend, monkeypatch):
    calls = command_mock(monkeypatch, backend, exists=False)
    assert backend.schedule_enabled() is False
    assert all(executable.endswith("powershell.exe") for executable, _ in calls)
    assert not backend.config_path.exists()


def test_disabled_config_reports_schedule_off(backend, monkeypatch):
    command_mock(monkeypatch, backend)
    config(backend, enabled=False, mode="checkin")
    assert backend.schedule_mode() is None


@pytest.mark.parametrize("mode", ["probe", "checkin"])
def test_schedule_explicit_mode_selection(backend, monkeypatch, mode):
    backend.save_credentials("test", "test-password")
    calls = command_mock(monkeypatch, backend)
    backend.set_schedule(True, mode)
    assert json.loads(backend.config_path.read_text())["mode"] == mode
    assert backend.schedule_mode() == mode
    assert any(args[0] == "/Create" for _, args in calls)
    assert not list(backend.root.glob(".task-*"))


@pytest.mark.parametrize("previous", [None, {"enabled": True, "mode": "probe"}])
def test_schedule_registration_failure_rolls_back_config(backend, monkeypatch, previous):
    backend.save_credentials("test", "test-password")
    if previous is not None:
        config(backend, **previous)
    original = backend.config_path.read_bytes() if previous is not None else None
    command_mock(monkeypatch, backend, create_code=1)
    with pytest.raises(desktop.DesktopError):
        backend.set_schedule(True, "checkin")
    assert (backend.config_path.read_bytes() if backend.config_path.exists() else None) == original
    assert not list(backend.root.glob(".task-*"))


def test_disable_deletes_only_current_task(backend, monkeypatch):
    calls = command_mock(monkeypatch, backend)
    backend.set_schedule(False)
    assert ("schtasks.exe", ["/Delete", "/TN", desktop.TASK_NAME, "/F"]) in calls
    assert json.loads(backend.config_path.read_text())["enabled"] is False


def test_invalid_schedule_mode_rejected_before_credentials(backend, monkeypatch):
    loader = Mock(side_effect=AssertionError("Unexpected credential read"))
    monkeypatch.setattr(backend, "load_credentials", loader)
    with pytest.raises(desktop.DesktopError):
        backend.set_schedule(True, "invalid")
    loader.assert_not_called()


def test_system_command_uses_system32_list_without_shell(backend, monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setenv("SystemRoot", "/synthetic-windows")
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(desktop.subprocess, "run", runner)
    backend._system_command("schtasks.exe", ["/Query", "/TN", "safe & name"])
    args, kwargs = runner.call_args
    assert args[0] == ["/synthetic-windows/System32/schtasks.exe", "/Query", "/TN", "safe & name"]
    assert not kwargs.get("shell", False)
    assert kwargs["timeout"] == 30


def test_formal_checkin_uses_same_runtime_lock(backend, monkeypatch):
    submit = Mock(return_value=result())
    monkeypatch.setattr(desktop, "run_checkin", submit)
    with RuntimeLock():
        with pytest.raises(RuntimeLockBusy):
            backend.check_in("test", "test-password")
    submit.assert_not_called()
    assert backend.check_in("test", "test-password").code == CheckinStatus.SUCCESS
    submit.assert_called_once()


def test_readonly_safety_switch_blocks_submission(backend, monkeypatch):
    monkeypatch.setenv("SWUDK_PROBE_ONLY", "1")
    with pytest.raises(desktop.DesktopError):
        backend.check_in("test", "test-password")
    desktop.run_checkin.assert_not_called()


def test_probe_only_calls_readonly_service(backend, monkeypatch):
    probe = Mock(return_value=result("probe"))
    monkeypatch.setattr(desktop, "run_probe", probe)
    assert backend.probe("test", "test-password").mode == "probe"
    desktop.run_checkin.assert_not_called()
    probe.assert_called_once()


def test_diagnosis_disables_token_cache_writes(backend, monkeypatch):
    service = Mock()
    service.diagnose.return_value = SimpleNamespace(
        authentication=True, leave_policy=True, student_profile=True, dormitory_schema=True, checkin_api=True
    )
    monkeypatch.setattr(desktop, "CheckinService", Mock(return_value=service))
    assert backend.diagnose("test", "test-password") is True
    service.diagnose.assert_called_once_with("test", "test-password", read_token_cache=False, write_token_cache=False)
    desktop.run_checkin.assert_not_called()


def test_corrupt_status_preserves_successful_remote_outcome(backend, monkeypatch):
    backend.root.mkdir()
    (backend.root / "status.json").write_text("corrupt")
    completed = result()
    monkeypatch.setattr(desktop, "run_checkin", Mock(return_value=completed))
    assert backend.check_in("test", "test-password") is completed
    assert "签到成功" in backend.status_text()
    assert json.loads((backend.root / "status.json").read_text())["successful"] is True


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"enabled": False, "mode": "checkin"},
        {"enabled": "true", "mode": "probe"},
        {"enabled": True, "mode": "invalid"},
    ],
)
def test_inactive_scheduled_run_never_reads_credentials(backend, monkeypatch, values):
    config(backend, **values)
    loader = Mock(side_effect=AssertionError("Unexpected credential read"))
    monkeypatch.setattr(backend, "load_credentials", loader)
    assert backend.run_scheduled() == 1
    loader.assert_not_called()


@pytest.mark.parametrize("mode", ["probe", "checkin"])
def test_scheduled_mode_routes_only_selected_operation(backend, monkeypatch, mode):
    config(backend, enabled=True, mode=mode)
    monkeypatch.setattr(backend, "load_credentials", Mock(return_value=("test", "synthetic-secret")))
    selected = Mock(return_value=result(mode))
    other = Mock(side_effect=AssertionError("Wrong operation"))
    monkeypatch.setattr(backend, mode if mode == "probe" else "check_in", selected)
    monkeypatch.setattr(backend, "check_in" if mode == "probe" else "probe", other)
    assert backend.run_scheduled() == 0
    selected.assert_called_once_with("test", "synthetic-secret")
    other.assert_not_called()
    text = (backend.root / "desktop-last-run.json").read_text()
    assert "synthetic-secret" not in text
    assert json.loads(text)["result"]["mode"] == mode


def test_scheduled_failures_never_log_secrets(backend, monkeypatch, capsys, caplog):
    config(backend, enabled=True, mode="probe")
    monkeypatch.setattr(backend, "load_credentials", Mock(side_effect=ValueError("synthetic-secret")))
    assert backend.run_scheduled() == 1
    captured = capsys.readouterr()
    assert "synthetic-secret" not in captured.out + captured.err + caplog.text


def test_scheduled_record_write_failure_preserves_remote_outcome(backend, monkeypatch):
    config(backend, enabled=True, mode="checkin")
    monkeypatch.setattr(backend, "load_credentials", Mock(return_value=("test", "test-password")))
    monkeypatch.setattr(backend, "check_in", Mock(return_value=result()))
    monkeypatch.setattr(desktop, "_atomic_write", Mock(side_effect=OSError("disk unavailable")))
    assert backend.run_scheduled() == 0


def test_status_write_failure_keeps_success_and_warns(backend, monkeypatch):
    completed = result()
    monkeypatch.setattr(desktop, "run_checkin", Mock(return_value=completed))
    monkeypatch.setattr(desktop, "record_run_status", Mock(side_effect=OSError("synthetic-secret")))
    assert backend.check_in("test", "test-password") is completed
    assert backend.last_warning
    assert "synthetic-secret" not in backend.last_warning


def test_schedule_requires_successful_saved_account_diagnosis(backend, monkeypatch):
    backend.save_credentials("saved-user", "saved-password")
    calls = command_mock(monkeypatch, backend)
    diagnose = Mock(return_value=False)
    monkeypatch.setattr(backend, "diagnose", diagnose)
    with pytest.raises(desktop.DesktopError):
        backend.set_schedule(True, "checkin")
    diagnose.assert_called_once_with("saved-user", "saved-password")
    assert not any(args[0] == "/Create" for _, args in calls)
    assert not backend.config_path.exists()


def test_enabled_schedule_prevents_credential_account_replacement(backend):
    backend.save_credentials("original-user", "original-password")
    config(backend, enabled=True, mode="checkin")
    with pytest.raises(desktop.DesktopError):
        backend.save_credentials("new-user", "new-password")
    assert backend.load_credentials() == ("original-user", "original-password")


@pytest.mark.parametrize("mode", [[], {}, False, 1])
def test_malformed_schedule_mode_is_safe_error(backend, monkeypatch, mode):
    command_mock(monkeypatch, backend)
    config(backend, enabled=True, mode=mode)
    with pytest.raises(desktop.DesktopError):
        backend.schedule_mode()
    assert backend.run_scheduled() == 1


def test_missing_credentials_cannot_enable_schedule(backend, monkeypatch):
    calls = command_mock(monkeypatch, backend)
    with pytest.raises(desktop.DesktopError):
        backend.set_schedule(True, "probe")
    assert not calls


def test_legacy_task_prevents_duplicate_registration(backend, monkeypatch):
    backend.save_credentials("test", "test-password")
    command_mock(monkeypatch, backend)
    monkeypatch.setattr(backend, "_task_exists", Mock(return_value=True))
    command = Mock(side_effect=AssertionError("No registration should happen"))
    monkeypatch.setattr(backend, "_system_command", command)
    with pytest.raises(desktop.DesktopError, match="旧版"):
        backend.set_schedule(True, "checkin")
    command.assert_not_called()


def test_registration_verification_failure_restores_previous_config(backend, monkeypatch):
    backend.save_credentials("test", "test-password")
    config(backend, enabled=False)
    previous = backend.config_path.read_bytes()
    command_mock(monkeypatch, backend, exists=False)
    with pytest.raises(desktop.DesktopError):
        backend.set_schedule(True, "checkin")
    assert backend.config_path.read_bytes() == previous


def test_missing_scheduled_config_never_loads_credentials(backend, monkeypatch):
    loader = Mock(side_effect=AssertionError("No credentials without opt-in"))
    monkeypatch.setattr(backend, "load_credentials", loader)
    assert backend.run_scheduled() == 1
    loader.assert_not_called()


def test_scheduled_formal_mode_respects_readonly_flag(backend, monkeypatch):
    config(backend, enabled=True, mode="checkin")
    monkeypatch.setattr(backend, "load_credentials", Mock(return_value=("test", "test-password")))
    monkeypatch.setenv("SWUDK_PROBE_ONLY", "1")
    assert backend.run_scheduled() == 1
    desktop.run_checkin.assert_not_called()


def test_nonfrozen_build_cannot_register_task(backend, monkeypatch):
    monkeypatch.setattr(desktop.sys, "frozen", False, raising=False)
    with pytest.raises(desktop.DesktopError, match="安装版"):
        backend.set_schedule(True)
    desktop.subprocess.run.assert_not_called()


def test_status_with_corrupt_files_is_safe(backend):
    backend.root.mkdir()
    (backend.root / "status.json").write_text("corrupt-synthetic-secret")
    (backend.root / "desktop-last-run.json").write_text("corrupt-synthetic-secret")
    text = backend.status_text()
    assert "损坏" in text
    assert "定时结果不可读取" in text
    assert "synthetic-secret" not in text


def test_frozen_task_xml_uses_installed_executable(backend, monkeypatch):
    backend.save_credentials("synthetic-user", "synthetic-password")
    command_mock(monkeypatch, backend)
    monkeypatch.setattr(desktop.sys, "executable", r"C:\Program Files\SWUCheckin\SWUCheckin.exe")
    original = backend._system_command
    captured = []

    def capture(executable, args):
        if args[0] == "/Create":
            raw = Path(args[args.index("/XML") + 1]).read_bytes()
            assert raw.startswith((b"\xff\xfe", b"\xfe\xff"))
            assert raw.decode("utf-16").startswith("<?xml version='1.0' encoding='utf-16'?>")
            captured.append(ET.fromstring(raw))
        return original(executable, args)

    monkeypatch.setattr(backend, "_system_command", capture)
    backend.set_schedule(True, "probe")
    assert len(captured) == 1
    ns = {"t": desktop.TASK_NS}
    assert captured[0].findtext(".//t:Command", namespaces=ns) == r"C:\Program Files\SWUCheckin\SWUCheckin.exe"
    assert captured[0].findtext(".//t:Arguments", namespaces=ns) == "--scheduled"
    assert captured[0].findtext(".//t:WorkingDirectory", namespaces=ns) == r"C:\Program Files\SWUCheckin"
    assert "synthetic-password" not in ET.tostring(captured[0], encoding="unicode")
    assert captured[0].findtext(".//t:UserId", namespaces=ns) == "S-1-5-21-123"
    assert captured[0].findtext(".//t:StartWhenAvailable", namespaces=ns) == "false"
    boundaries = [node.text for node in captured[0].findall(".//t:StartBoundary", ns)]
    assert [value[11:] for value in boundaries] == ["21:15:00+08:00", "21:45:00+08:00"]


@pytest.mark.parametrize("entrypoint", ["cli", "gui", "scheduled"])
def test_formal_entrypoints_share_one_lock_owner(backend, monkeypatch, entrypoint):
    from swu_checkin import cli, formal_execution

    wrapper = Mock(wraps=formal_execution.execute_formal_checkin_with_lock)
    monkeypatch.setattr(formal_execution, "execute_formal_checkin_with_lock", wrapper)
    lock_factory = Mock(wraps=RuntimeLock)
    monkeypatch.setattr(formal_execution, "RuntimeLock", lock_factory)

    def submit(*args, **kwargs):
        contender = RuntimeLock()
        assert contender.acquire() is False
        return result()

    monkeypatch.setattr(cli, "run_checkin", submit)
    monkeypatch.setattr(desktop, "run_checkin", submit)
    monkeypatch.setenv("SWUDK_USERNAME", "synthetic-user")
    monkeypatch.setenv("SWUDK_PASSWORD", "synthetic-password")
    monkeypatch.delenv("SWUDK_STATUS_FILE", raising=False)
    if entrypoint == "cli":
        assert cli.main(["run"]) == 0
    elif entrypoint == "gui":
        assert backend.check_in("synthetic-user", "synthetic-password").code == CheckinStatus.SUCCESS
    else:
        config(backend, enabled=True, mode="checkin")
        monkeypatch.setattr(backend, "load_credentials", lambda: ("synthetic-user", "synthetic-password"))
        assert backend.run_scheduled() == 0
    wrapper.assert_called_once()
    lock_factory.assert_called_once_with()
    with RuntimeLock():
        pass


@pytest.mark.parametrize("entrypoint", ["cli", "gui", "scheduled"])
def test_readonly_entrypoints_never_use_formal_wrapper(backend, monkeypatch, entrypoint):
    from swu_checkin import cli, formal_execution

    wrapper = Mock(side_effect=AssertionError("Probe must not acquire formal lock"))
    monkeypatch.setattr(formal_execution, "execute_formal_checkin_with_lock", wrapper)
    monkeypatch.setattr(cli, "run_probe", lambda *args, **kwargs: result("probe"))
    monkeypatch.setattr(desktop, "run_probe", lambda *args, **kwargs: result("probe"))
    monkeypatch.setenv("SWUDK_USERNAME", "synthetic-user")
    monkeypatch.setenv("SWUDK_PASSWORD", "synthetic-password")
    with RuntimeLock():
        if entrypoint == "cli":
            assert cli.main(["probe"]) == 0
        elif entrypoint == "gui":
            assert backend.probe("synthetic-user", "synthetic-password").mode == "probe"
        else:
            config(backend, enabled=True, mode="probe")
            monkeypatch.setattr(backend, "load_credentials", lambda: ("synthetic-user", "synthetic-password"))
            assert backend.run_scheduled() == 0
    wrapper.assert_not_called()


@pytest.mark.parametrize("marker,expected", [("SWU_TASK_EXISTS", True), ("SWU_TASK_ABSENT", False)])
def test_task_query_requires_definite_success_marker(backend, monkeypatch, marker, expected):
    query = Mock(return_value=SimpleNamespace(returncode=0, stdout=marker, stderr=""))
    monkeypatch.setattr(backend, "_system_command", query)
    assert backend._task_exists(desktop.TASK_NAME) is expected
    executable, args = query.call_args.args
    assert executable == r"WindowsPowerShell\v1.0\powershell.exe"
    assert args[:4] == ["-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand"]
    script = base64.b64decode(args[-1]).decode("utf-16-le")
    assert "$ProgressPreference='SilentlyContinue'" in script
    assert "$f.GetTask('SWUCheckin-Desktop')" in script
    assert "$f=$s.GetFolder('\\') } catch { exit 3 }" in script
    assert "if ($e.HResult -eq -2147024894)" in script
    assert "-is [Runtime.InteropServices.COMException]" not in script
    assert "/Create" not in script and "/Delete" not in script


@pytest.mark.parametrize(
    "code,out,err",
    [
        (1, "", "not found"),
        (5, "", "access denied token-secret"),
        (3, "", "service failure"),
        (2, "SWU_TASK_ABSENT", ""),
        (0, "", ""),
        (0, "unrecognized user-path", ""),
        (0, "SWU_TASK_ABSENT", "warning password-secret"),
    ],
)
def test_task_query_unknown_fails_closed_without_leak(backend, monkeypatch, code, out, err):
    monkeypatch.setattr(
        backend, "_system_command", Mock(return_value=SimpleNamespace(returncode=code, stdout=out, stderr=err))
    )
    with pytest.raises(desktop.DesktopError) as caught:
        backend._task_exists(desktop.TASK_NAME)
    assert caught.value.code is desktop.DesktopErrorCode.TASK_QUERY_FAILED
    assert str(caught.value) == "无法确认计划任务状态"


@pytest.mark.parametrize("error", [OSError("sensitive-path"), subprocess.TimeoutExpired("token-secret", 30)])
def test_task_query_process_failure_is_fixed_error(backend, monkeypatch, error):
    monkeypatch.setattr(backend, "_system_command", Mock(side_effect=error))
    with pytest.raises(desktop.DesktopError, match="^无法确认计划任务状态$"):
        backend._task_exists(desktop.TASK_NAME)


@pytest.mark.parametrize("operation", ["mode", "enable", "disable"])
@pytest.mark.parametrize("failed_name", [desktop.TASK_NAME, desktop.LEGACY_TASK_NAME])
def test_unknown_task_state_prevents_schedule_mutation(backend, monkeypatch, operation, failed_name):
    backend.save_credentials("synthetic-user", "synthetic-password")
    calls = command_mock(monkeypatch, backend)
    config(backend, enabled=False)
    previous = backend.config_path.read_bytes()

    def query(name):
        if name == failed_name:
            raise desktop.DesktopError(desktop.DesktopErrorCode.TASK_QUERY_FAILED)
        return False

    monkeypatch.setattr(backend, "_task_exists", query)
    if failed_name == desktop.LEGACY_TASK_NAME and operation != "enable":
        # Mode/disable only concern the current desktop task, not a legacy one.
        if operation == "mode":
            assert backend.schedule_mode() is None
        else:
            backend.set_schedule(False)
    else:
        with pytest.raises(desktop.DesktopError, match="^无法确认计划任务状态$"):
            if operation == "mode":
                backend.schedule_mode()
            else:
                backend.set_schedule(operation == "enable")
        assert backend.config_path.read_bytes() == previous
    assert not any(args[0] in {"/Create", "/Delete"} for _, args in calls)
    assert not list(backend.root.glob(".task-*"))


def mutation_case(backend, monkeypatch, *, enabled, final_exists, outcome):
    backend.save_credentials("synthetic-user", "synthetic-password")
    config(backend, enabled=not enabled, **({"mode": "probe"} if not enabled else {}))
    command_mock(monkeypatch, backend)
    answers = iter([not enabled, final_exists])
    queries = []

    def query(name):
        queries.append(name)
        if name == desktop.LEGACY_TASK_NAME:
            return False
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    calls = []

    def command(executable, args):
        calls.append(args)
        if executable == "whoami.exe":
            return SimpleNamespace(returncode=0, stdout='"CI\\User","S-1-5-21-123"')
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(returncode=outcome, stdout="raw-token-secret", stderr="private-path")

    monkeypatch.setattr(backend, "_task_exists", query)
    monkeypatch.setattr(backend, "_system_command", command)
    return calls, queries


@pytest.mark.parametrize("outcome", [1, OSError("private-path token-secret"), subprocess.TimeoutExpired("secret", 30)])
def test_failed_create_confirmed_absent_is_known_failure(backend, monkeypatch, outcome):
    calls, queries = mutation_case(backend, monkeypatch, enabled=True, final_exists=False, outcome=outcome)
    previous = backend.config_path.read_bytes()
    with pytest.raises(desktop.DesktopError) as caught:
        backend.set_schedule(True, "probe")
    assert caught.value.code is desktop.DesktopErrorCode.TASK_CREATE_FAILED
    assert backend.config_path.read_bytes() == previous
    assert sum(args[0] == "/Create" for args in calls) == 1
    assert queries.count(desktop.TASK_NAME) == 2


@pytest.mark.parametrize("outcome", [1, OSError("token-secret"), subprocess.TimeoutExpired("secret", 30)])
def test_failed_create_that_exists_is_uncertain(backend, monkeypatch, outcome):
    calls, queries = mutation_case(backend, monkeypatch, enabled=True, final_exists=True, outcome=outcome)
    with pytest.raises(desktop.DesktopError) as caught:
        backend.set_schedule(True, "probe")
    assert caught.value.code is desktop.DesktopErrorCode.TASK_STATE_UNCERTAIN
    assert "secret" not in str(caught.value)
    assert sum(args[0] == "/Create" for args in calls) == 1
    assert queries.count(desktop.TASK_NAME) == 2
    assert not any(args[0] == "/Delete" for args in calls)


@pytest.mark.parametrize("enabled", [True, False])
def test_post_mutation_query_failure_is_uncertain(backend, monkeypatch, enabled):
    calls, queries = mutation_case(
        backend,
        monkeypatch,
        enabled=enabled,
        final_exists=desktop.DesktopError(desktop.DesktopErrorCode.TASK_QUERY_FAILED),
        outcome=0,
    )
    with pytest.raises(desktop.DesktopError) as caught:
        backend.set_schedule(enabled, "probe")
    assert caught.value.code is desktop.DesktopErrorCode.TASK_STATE_UNCERTAIN
    assert sum(args[0] in {"/Create", "/Delete"} for args in calls) == 1
    assert queries.count(desktop.TASK_NAME) == 2


def test_create_rollback_failure_is_uncertain(backend, monkeypatch):
    calls, _queries = mutation_case(backend, monkeypatch, enabled=True, final_exists=False, outcome=1)
    original = desktop._atomic_write
    writes = 0

    def writer(path, data):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("private-path token-secret")
        original(path, data)

    monkeypatch.setattr(desktop, "_atomic_write", writer)
    with pytest.raises(desktop.DesktopError) as caught:
        backend.set_schedule(True, "probe")
    assert caught.value.code is desktop.DesktopErrorCode.TASK_STATE_UNCERTAIN
    assert sum(args[0] == "/Create" for args in calls) == 1


@pytest.mark.parametrize("outcome", [1, OSError("private-secret"), subprocess.TimeoutExpired("secret", 30)])
def test_failed_delete_confirmed_present_keeps_known_enabled_state(backend, monkeypatch, outcome):
    calls, queries = mutation_case(backend, monkeypatch, enabled=False, final_exists=True, outcome=outcome)
    previous = backend.config_path.read_bytes()
    with pytest.raises(desktop.DesktopError) as caught:
        backend.set_schedule(False)
    assert caught.value.code is desktop.DesktopErrorCode.TASK_DISABLE_FAILED
    assert backend.config_path.read_bytes() == previous
    assert sum(args[0] == "/Delete" for args in calls) == 1
    assert queries.count(desktop.TASK_NAME) == 2


@pytest.mark.parametrize("outcome", [1, subprocess.TimeoutExpired("secret", 30)])
def test_failed_delete_that_is_absent_is_uncertain(backend, monkeypatch, outcome):
    calls, _queries = mutation_case(backend, monkeypatch, enabled=False, final_exists=False, outcome=outcome)
    with pytest.raises(desktop.DesktopError) as caught:
        backend.set_schedule(False)
    assert caught.value.code is desktop.DesktopErrorCode.TASK_STATE_UNCERTAIN
    assert sum(args[0] == "/Delete" for args in calls) == 1


def test_successful_delete_config_write_failure_is_uncertain(backend, monkeypatch):
    mutation_case(backend, monkeypatch, enabled=False, final_exists=False, outcome=0)
    monkeypatch.setattr(desktop, "_atomic_write", Mock(side_effect=OSError("private-secret")))
    with pytest.raises(desktop.DesktopError) as caught:
        backend.set_schedule(False)
    assert caught.value.code is desktop.DesktopErrorCode.TASK_STATE_UNCERTAIN


@pytest.mark.parametrize("enabled", [True, False])
def test_post_mutation_failure_with_invalid_prior_config_is_uncertain(backend, monkeypatch, enabled):
    mutation_case(backend, monkeypatch, enabled=enabled, final_exists=not enabled, outcome=1)
    backend.config_path.write_text("invalid-private-secret")
    with pytest.raises(desktop.DesktopError) as caught:
        backend.set_schedule(enabled, "probe")
    assert caught.value.code is desktop.DesktopErrorCode.TASK_STATE_UNCERTAIN
    assert "secret" not in str(caught.value)
