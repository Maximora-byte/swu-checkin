"""Persistent attempt quarantine: no platform receipt is inferred from CLI exit."""

import os
import subprocess
import sys
from unittest.mock import Mock

import pytest

from swu_checkin import notify


@pytest.fixture
def isolated_send(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    for key in ("OPENAI_API_KEY", "OPENCLAW_GATEWAY_TOKEN", "TELEGRAM_BOT_TOKEN"):
        monkeypatch.setenv(key, "synthetic-not-a-real-key")
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("SWUDK_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("SWUDK_NOTIFY_TARGET", "synthetic-target")
    monkeypatch.setattr(notify, "today_shanghai", lambda: "2026-09-17")
    return tmp_path


def test_legacy_cli_marker_does_not_claim_platform_delivery(isolated_send, monkeypatch, capsys):
    (isolated_send / "notified-2026-09-17").write_text("sent\n")
    launch = Mock()
    monkeypatch.setattr(notify.subprocess, "Popen", launch)
    assert notify.main() == 0
    launch.assert_not_called()
    assert "CLI 完成标记已存在，跳过；平台送达未核验" in capsys.readouterr().out


def test_exit_zero_reports_cli_completion_not_platform_receipt(isolated_send, monkeypatch, capsys):
    process = Mock()
    process.wait.return_value = 0
    monkeypatch.setattr(notify.subprocess, "Popen", Mock(return_value=process))
    assert notify.main() == 0
    assert "CLI 已退出 0；平台送达未核验" in capsys.readouterr().out
    assert (isolated_send / "notify-attempt-2026-09-17").read_text() == "delivery_unverified\n"


def test_success_marker_write_error_is_safe_and_never_replays(isolated_send, monkeypatch, capsys):
    process = Mock()
    process.wait.return_value = 0
    launch = Mock(return_value=process)
    monkeypatch.setattr(notify.subprocess, "Popen", launch)
    write = type(isolated_send).write_text

    def fail_success_marker(path, *args, **kwargs):
        if path.name.startswith("notified-"):
            raise OSError("synthetic-private-state-path")
        return write(path, *args, **kwargs)

    monkeypatch.setattr(type(isolated_send), "write_text", fail_success_marker)
    assert notify.main() == 1
    assert notify.main() == 1
    launch.assert_called_once()
    diagnostic = capsys.readouterr().err
    assert "reason=marker_error outcome=delivery_unverified" in diagnostic
    assert "synthetic-private-state-path" not in diagnostic


def test_guard_failure_fails_closed_without_disclosing_state(isolated_send, monkeypatch, capsys):
    launch = Mock()
    monkeypatch.setattr(notify.subprocess, "Popen", launch)
    monkeypatch.setattr(notify.os, "open", Mock(side_effect=OSError("synthetic-private-path")))
    assert notify.main() == 1
    launch.assert_not_called()
    diagnostic = capsys.readouterr().err
    assert "reason=state_error outcome=not_sent" in diagnostic
    assert "synthetic-private-path" not in diagnostic


def test_existing_empty_attempt_is_not_treated_as_permission_to_send(isolated_send, monkeypatch):
    (isolated_send / "notify-attempt-2026-09-17").touch()
    launch = Mock()
    monkeypatch.setattr(notify.subprocess, "Popen", launch)
    assert notify.main() == 1
    launch.assert_not_called()


def test_nonposix_direct_child_fallback_keeps_quarantine(isolated_send, monkeypatch):
    class NonPosixOS:
        name = "nt"

        def __getattr__(self, name):
            return getattr(os, name)

    process = Mock()
    process.wait.side_effect = [subprocess.TimeoutExpired("synthetic", 60), -9]
    launch = Mock(return_value=process)
    monkeypatch.setattr(notify, "os", NonPosixOS())
    monkeypatch.setattr(notify.subprocess, "Popen", launch)
    assert notify.main() == 1
    assert notify.main() == 1
    process.kill.assert_called_once()
    launch.assert_called_once()
    assert launch.call_args.kwargs["start_new_session"] is False
    assert not (isolated_send / "notified-2026-09-17").exists()


def test_independent_processes_claim_one_attempt(isolated_send):
    fake = isolated_send / "fake_cli.py"
    fake.write_text(
        "import os, time\nfrom pathlib import Path\n"
        "with (Path(os.environ['SWUDK_STATE_DIR']) / 'send-count').open('a') as f: f.write('attempt\\n')\n"
        "time.sleep(0.1)\n"
    )
    wrapper = isolated_send / "invoke.py"
    wrapper.write_text(
        "import subprocess, sys\nfrom swu_checkin import notify\n"
        "notify.today_shanghai = lambda: '2026-09-17'\n"
        "popen = subprocess.Popen\n"
        f"notify.subprocess.Popen = lambda command, **kw: popen([sys.executable, {str(fake)!r}], **kw)\n"
        "sys.exit(notify.main())\n"
    )
    children = [
        subprocess.Popen([sys.executable, str(wrapper)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(2)
    ]
    try:
        assert sorted(child.wait(timeout=10) for child in children) == [0, 1]
        assert (isolated_send / "send-count").read_text() == "attempt\n"
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)


def test_unknown_send_is_quarantined_across_invocations(isolated_send, monkeypatch, capsys):
    root = isolated_send
    script = root / "fake_send.py"
    script.write_text(
        "from pathlib import Path\nimport os, time\n"
        "root = Path(os.environ['SWUDK_STATE_DIR'])\n"
        "with (root / 'synthetic-send-count').open('a') as f: f.write('attempt\\n')\n"
        "time.sleep(30)\n"
    )
    popen = subprocess.Popen
    calls = []

    def launch(command, **kwargs):
        calls.append(command)
        return popen([sys.executable, str(script)], **kwargs)

    monkeypatch.setattr(notify.subprocess, "Popen", launch)
    monkeypatch.setattr(notify, "SEND_TIMEOUT", 0.3)
    monkeypatch.setattr(notify, "TERMINATE_GRACE", 0.05)
    assert notify.main() == 1
    assert notify.main() == 1
    assert len(calls) == 1, "an unknown send must not be replayed by another invocation"
    assert (root / "synthetic-send-count").read_text() == "attempt\n"
    assert not (root / "notified-2026-09-17").exists()
    attempt = root / "notify-attempt-2026-09-17"
    assert attempt.read_text() == "delivery_unverified\n"
    if os.name == "posix":
        assert attempt.stat().st_mode & 0o777 == 0o600
    assert "reason=attempt_exists outcome=delivery_unverified" in capsys.readouterr().err
