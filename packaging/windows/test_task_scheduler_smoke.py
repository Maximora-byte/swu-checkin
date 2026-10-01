"""Only mocked registration tests; real smoke is explicitly CI-only."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from xml.etree import ElementTree as ET

import pytest

spec = importlib.util.spec_from_file_location(
    "task_scheduler_smoke", Path(__file__).with_name("task_scheduler_smoke.py")
)
assert spec is not None and spec.loader is not None
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def test_harmless_xml_reuses_production_bytes_with_future_triggers():
    now = datetime(2026, 10, 1, 12, tzinfo=UTC)
    data = helper.harmless_xml(r"C:\Windows\System32\cmd.exe", "S-1-5-21-123", now)
    assert data.startswith((b"\xff\xfe", b"\xfe\xff"))
    root = ET.fromstring(data)
    helper.validate_xml(root, r"C:\Windows\System32\cmd.exe", "S-1-5-21-123", now)
    assert "--scheduled" not in data.decode("utf-16")
    assert root.findtext(".//t:Arguments", namespaces=helper.NS) == "/d /c exit 0"
    assert root.findtext(".//t:StartWhenAvailable", namespaces=helper.NS) == "false"


def test_non_ci_task_smoke_refuses_before_backend(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    backend = Mock(side_effect=AssertionError("Must not inspect tasks"))
    monkeypatch.setattr(helper, "DesktopBackend", backend)
    with pytest.raises(RuntimeError, match="disposable"):
        helper.run_smoke()
    backend.assert_not_called()


@pytest.mark.parametrize("registration_fails", [False, True])
def test_task_smoke_only_creates_and_cleans_its_random_name(monkeypatch, tmp_path, registration_fails):
    monkeypatch.setattr(helper.sys, "platform", "win32")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("SystemRoot", str(tmp_path / "system"))
    backend = Mock()
    state = {"exists": False, "xml": None}
    backend._task_exists.side_effect = lambda name: state["exists"]
    calls = []

    def command(executable, args):
        calls.append((executable, args))
        if executable == "whoami.exe":
            return SimpleNamespace(returncode=0, stdout='"CI\\User","S-1-5-21-123"')
        name = args[args.index("/TN") + 1]
        assert helper.re.fullmatch(r"SWUCheckin-CI-[0-9a-f]{32}", name)
        assert name not in {"SWUCheckin-Desktop", "SWUCheckin-Daily"}
        if args[0] == "/Create":
            state["xml"] = Path(args[args.index("/XML") + 1]).read_bytes()
            state["exists"] = True
            return SimpleNamespace(returncode=int(registration_fails), stdout="")
        if args[0] == "/Query":
            return SimpleNamespace(returncode=0, stdout=state["xml"].decode("utf-16"))
        assert args[0] == "/Delete"
        state["exists"] = False
        return SimpleNamespace(returncode=0, stdout="")

    backend._system_command.side_effect = command
    monkeypatch.setattr(helper, "DesktopBackend", Mock(return_value=backend))
    if registration_fails:
        with pytest.raises(RuntimeError, match="registration failed"):
            helper.run_smoke()
    else:
        helper.run_smoke()
    assert state["exists"] is False
    names = {args[args.index("/TN") + 1] for _, args in calls if "/TN" in args}
    assert len(names) == 1
    assert not any("/Run" in args for _, args in calls)
    backend.load_credentials.assert_not_called()
    backend.run_scheduled.assert_not_called()
    backend.check_in.assert_not_called()
