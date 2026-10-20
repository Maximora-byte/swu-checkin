import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from swu_checkin import notify

SECRET = "synthetic-token-target-message"


@pytest.fixture
def fake_cli(monkeypatch, tmp_path):
    """Only run a synthetic CLI, with no inherited user configuration."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("SWUDK_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("SWUDK_NOTIFY_TARGET", SECRET)
    monkeypatch.setattr(notify, "today_shanghai", lambda: "2026-09-17")
    script = tmp_path / "fake_cli.py"
    popen = subprocess.Popen
    calls = []

    def launch(command, **kwargs):
        calls.append(command)
        return popen([sys.executable, str(script)], **kwargs)

    monkeypatch.setattr(notify.subprocess, "Popen", launch)

    def configure(source):
        script.write_text(source, encoding="utf-8")
        return calls

    return configure


def test_nonzero_has_bounded_safe_diagnostic(fake_cli, tmp_path, capsys):
    calls = fake_cli(f"import sys\nprint({SECRET!r} * 10000)\nprint({SECRET!r}, file=sys.stderr)\nsys.exit(7)\n")
    assert notify.main() == 1
    diagnostic = capsys.readouterr().err
    assert "stage=send" in diagnostic
    assert "reason=nonzero_exit" in diagnostic
    assert "outcome=unknown_after_send" in diagnostic
    assert "exit=7" in diagnostic
    assert "elapsed_ms=" in diagnostic
    assert SECRET not in diagnostic
    assert len(diagnostic) < 256
    assert len(calls) == 1
    assert not (tmp_path / "notified-2026-09-17").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal exit status")
def test_signal_exit_is_classified_without_output(fake_cli, tmp_path, capsys):
    calls = fake_cli(f"import os, signal\nprint({SECRET!r}, flush=True)\nos.kill(os.getpid(), signal.SIGTERM)\n")
    assert notify.main() == 1
    diagnostic = capsys.readouterr().err
    assert "reason=signal_exit outcome=unknown_after_send" in diagnostic
    assert "signal=15" in diagnostic
    assert SECRET not in diagnostic
    assert len(calls) == 1
    assert not (tmp_path / "notified-2026-09-17").exists()


def test_spawn_failure_is_safe_and_not_retried(fake_cli, monkeypatch, tmp_path, capsys):
    fake_cli("raise AssertionError('must not run')")
    launch = Mock(side_effect=OSError(SECRET))
    monkeypatch.setattr(notify.subprocess, "Popen", launch)
    assert notify.main() == 1
    diagnostic = capsys.readouterr().err
    assert "stage=spawn reason=spawn_error outcome=not_sent" in diagnostic
    assert "elapsed_ms=" in diagnostic
    assert SECRET not in diagnostic
    assert len(diagnostic) < 256
    launch.assert_called_once()
    assert not (tmp_path / "notified-2026-09-17").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux /proc and subreaper integration")
@pytest.mark.parametrize("root_exits_on_term", [False, True])
def test_timeout_stops_descendants_with_inherited_output(fake_cli, monkeypatch, tmp_path, capsys, root_exits_on_term):
    # Adopt only our orphaned fake descendants so the test can reap them too.
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0
    assert libc.prctl(36, 1, 0, 0, 0) == 0
    source = f"""import os, signal, subprocess, sys, time
from pathlib import Path
root = Path({str(tmp_path)!r})
role = int(sys.argv[1]) if len(sys.argv) > 1 else 0
signal.signal(signal.SIGTERM, signal.SIG_IGN)
if role == 0 and {root_exits_on_term!r}:
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
(root / ("pid-" + str(role))).write_text(str(os.getpid()))
if role < 2:
    subprocess.Popen([sys.executable, __file__, str(role + 1)])
# Simulate a potentially delivered send; stdout/stderr are inherited by descendants.
if role == 2:
    (root / "send-attempted").write_text("unknown")
while True:
    time.sleep(0.05)
"""
    calls = fake_cli(source)
    monkeypatch.setattr(notify, "SEND_TIMEOUT", 0.6, raising=False)
    monkeypatch.setattr(notify, "TERMINATE_GRACE", 0.1, raising=False)
    # Keep the pre-fix reproduction bounded without changing its cleanup behavior.
    run = subprocess.run

    def short_run(*args, **kwargs):
        kwargs["timeout"] = 0.6
        return run(*args, **kwargs)

    monkeypatch.setattr(notify.subprocess, "run", short_run)
    pids = []
    try:
        started = time.monotonic()
        assert notify.main() == 1
        assert time.monotonic() - started < 3
        pids = [int((tmp_path / f"pid-{role}").read_text()) for role in range(3)]
        assert (tmp_path / "send-attempted").exists()
        assert len(calls) == 1
        assert not (tmp_path / "notified-2026-09-17").exists()
        # KILL delivery is asynchronous for non-child descendants: allow scheduling.
        # A zombie is terminated, not a live worker; finally reaps adopted children.
        for pid in pids:
            stat = Path(f"/proc/{pid}/stat")
            deadline = time.monotonic() + 0.5
            while stat.exists() and stat.read_text().split()[2] != "Z" and time.monotonic() < deadline:
                time.sleep(0.01)
            assert not stat.exists() or stat.read_text().split()[2] == "Z", f"live fake descendant: {pid}"
        diagnostic = capsys.readouterr().err
        assert "reason=timeout outcome=unknown_after_send" in diagnostic
        assert "elapsed_ms=" in diagnostic
        assert SECRET not in diagnostic
    finally:
        for pidfile in tmp_path.glob("pid-*"):
            pid = int(pidfile.read_text())
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        assert libc.prctl(36, previous.value, 0, 0, 0) == 0


def test_cleanup_wait_is_bounded(fake_cli, monkeypatch, tmp_path, capsys):
    fake_cli("raise AssertionError('must not run')")
    process = Mock(pid=12345)
    process.wait.side_effect = subprocess.TimeoutExpired(SECRET, 60)
    monkeypatch.setattr(notify.subprocess, "Popen", Mock(return_value=process))
    if os.name == "posix":
        monkeypatch.setattr(notify.os, "killpg", Mock())
    monkeypatch.setattr(notify.time, "sleep", Mock())
    assert notify.main() == 1
    assert all(call.kwargs.get("timeout") for call in process.wait.call_args_list)
    diagnostic = capsys.readouterr().err
    assert "reason=cleanup_timeout outcome=unknown_after_send" in diagnostic
    assert SECRET not in diagnostic
    assert not (tmp_path / "notified-2026-09-17").exists()


@pytest.mark.parametrize("dry_run", [False, True])
def test_exit_zero_preserves_cli_marker_contract(fake_cli, monkeypatch, tmp_path, capsys, dry_run):
    calls = fake_cli(f"print({SECRET!r})\n")
    monkeypatch.setenv("SWUDK_NOTIFY_DRY_RUN", "1" if dry_run else "0")
    assert notify.main() == 0
    marker = tmp_path / "notified-2026-09-17"
    assert marker.read_text() == "sent\n"
    if os.name == "posix":
        assert marker.stat().st_mode & 0o777 == 0o600
    assert ("--dry-run" in calls[0]) is dry_run
    assert "--json" in calls[0]
    assert notify.main() == 0  # An existing marker skips a second launch.
    assert len(calls) == 1
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err


def _write_status(state_dir, *, code: int = 1, message: str = "签到成功") -> None:
    payload = {"date": "2026-09-17", "attempts": [{"code": code, "message": message}]}
    (state_dir / "status.json").write_text(json.dumps(payload), encoding="utf-8")


def test_notifier_requires_external_target(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys):
    _write_status(tmp_path)
    monkeypatch.setenv("SWUDK_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("SWUDK_NOTIFY_TARGET", raising=False)
    monkeypatch.setattr(notify, "today_shanghai", lambda: "2026-09-17")
    run = Mock()
    monkeypatch.setattr(notify.subprocess, "Popen", run)

    assert notify.main() == 2
    run.assert_not_called()
    assert "缺少 SWUDK_NOTIFY_TARGET" in capsys.readouterr().err


def test_notifier_timeout_does_not_mark_day_as_sent(fake_cli, monkeypatch, tmp_path, capsys):
    _write_status(tmp_path)
    fake_cli("import time\ntime.sleep(30)\n")
    monkeypatch.setattr(notify, "SEND_TIMEOUT", 0.1)
    monkeypatch.setattr(notify, "TERMINATE_GRACE", 0.05)

    assert notify.main() == 1
    assert "reason=timeout outcome=unknown_after_send" in capsys.readouterr().err
    assert not (tmp_path / "notified-2026-09-17").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")
@pytest.mark.parametrize("probe_error", [None, ProcessLookupError(), PermissionError(), OSError()])
def test_kill_permission_error_requires_group_absence_after_reaping(monkeypatch, probe_error):
    """Darwin may reject KILL of a zombie-only group; an exited leader alone is insufficient."""
    process = Mock(pid=12345)
    denied = PermissionError("synthetic cleanup denial")
    events = []

    def killpg(pid, sig):
        assert pid == process.pid
        events.append(sig)
        if sig == signal.SIGKILL:
            raise denied
        if sig == 0 and probe_error is not None:
            raise probe_error

    def wait(*, timeout):
        assert timeout == notify.TERMINATE_GRACE
        events.append("reap")
        return -signal.SIGTERM

    process.wait.side_effect = wait
    monkeypatch.setattr(notify.os, "killpg", killpg)
    monkeypatch.setattr(notify.time, "sleep", Mock())
    if isinstance(probe_error, ProcessLookupError):
        notify._stop_send(process)
    else:
        with pytest.raises(PermissionError) as exc:
            notify._stop_send(process)
        assert exc.value is denied
    # No destructive signals after reaping releases the leader's PID reservation.
    assert events == [signal.SIGTERM, signal.SIGKILL, "reap", 0]
    process.wait.assert_called_once_with(timeout=notify.TERMINATE_GRACE)


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")
def test_kill_permission_error_does_not_skip_bounded_reap(monkeypatch):
    process = Mock(pid=12345)
    process.wait.side_effect = subprocess.TimeoutExpired("synthetic", notify.TERMINATE_GRACE)
    killpg = Mock(side_effect=[None, PermissionError()])
    monkeypatch.setattr(notify.os, "killpg", killpg)
    monkeypatch.setattr(notify.time, "sleep", Mock())
    with pytest.raises(subprocess.TimeoutExpired):
        notify._stop_send(process)
    process.wait.assert_called_once_with(timeout=notify.TERMINATE_GRACE)
    assert [call.args[1] for call in killpg.call_args_list] == [signal.SIGTERM, signal.SIGKILL]


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")
def test_term_permission_error_is_not_suppressed(monkeypatch):
    process = Mock(pid=12345)
    killpg = Mock(side_effect=PermissionError())
    monkeypatch.setattr(notify.os, "killpg", killpg)
    with pytest.raises(PermissionError):
        notify._stop_send(process)
    killpg.assert_called_once_with(process.pid, signal.SIGTERM)
    process.wait.assert_not_called()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")
@pytest.mark.parametrize("probe_error", [None, PermissionError(), OSError()])
def test_denied_group_cleanup_preserves_quarantine(fake_cli, monkeypatch, tmp_path, probe_error):
    fake_cli("raise AssertionError('must not run')")
    process = Mock(pid=12345)
    process.wait.side_effect = [subprocess.TimeoutExpired("synthetic", 60), -signal.SIGTERM]
    launch = Mock(return_value=process)
    denied = PermissionError("synthetic cleanup denial")
    monkeypatch.setattr(notify.subprocess, "Popen", launch)
    monkeypatch.setattr(notify.os, "killpg", Mock(side_effect=[None, denied, probe_error]))
    monkeypatch.setattr(notify.time, "sleep", Mock())
    with pytest.raises(PermissionError) as exc:
        notify.main()
    assert exc.value is denied
    assert not (tmp_path / "notified-2026-09-17").exists()
    assert (tmp_path / "notify-attempt-2026-09-17").read_text() == "delivery_unverified\n"
    assert notify.main() == 1
    launch.assert_called_once()
