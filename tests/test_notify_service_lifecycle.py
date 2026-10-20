"""Opt-in real systemd acceptance; never runs OpenClaw or reads application state."""

import configparser
import os
import select
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

UNIT = Path(__file__).resolve().parents[1] / "deploy/systemd/swu-checkin-notify.service"


def test_notify_unit_has_bounded_cgroup_stop():
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.read(UNIT)
    service = config["Service"]
    assert service.get("KillMode") == "control-group"
    assert service.get("TimeoutStopSec") == "3"
    assert service.get("SendSIGKILL") == "yes"
    assert service.get("RemainAfterExit", "no") == "no"
    assert service["TimeoutStartSec"] == "90"
    assert service["ProtectControlGroups"] == "true"
    assert service["CapabilityBoundingSet"] == ""


@pytest.mark.skipif(
    sys.platform != "linux" or os.getenv("SWU_TEST_SYSTEMD") != "1",
    reason="explicit opt-in for privileged, isolated swu-fixture-* units only",
)
@pytest.mark.parametrize("mode", ["nested_timeout", "leader_exit", "term_leader", "marker_error", "dryrun"])
def test_service_completion_cleans_detached_term_resistant_tree(tmp_path, mode):
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.read(UNIT)
    service = config["Service"]
    name = "swu-fixture-" + uuid.uuid4().hex
    script = tmp_path / "synthetic.py"
    script.write_text(
        "import os, signal, subprocess, sys, time\n"
        "from pathlib import Path\n"
        f"root = Path({str(tmp_path)!r})\n"
        "role = int(sys.argv[1])\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "(root / ('pid-' + str(role))).write_text(str(os.getpid()))\n"
        "if role < 2: subprocess.Popen([sys.executable, __file__, str(role + 1)], start_new_session=True)\n"
        "if role == 0:\n"
        " (root / 'synthetic-send').write_text('once')\n"
        " while not (root / 'pid-2').exists(): time.sleep(.01)\n"
        f" if {mode!r} in ('leader_exit', 'marker_error', 'dryrun'): sys.exit(0)\n"
        f" if {mode!r} == 'term_leader': signal.signal(signal.SIGTERM, signal.SIG_DFL)\n"
        "while True: time.sleep(.01)\n"
    )
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import ctypes, os, subprocess, sys\nfrom pathlib import Path\n"
        "assert ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) == 0\n"
        f"sys.path.insert(0, {str(UNIT.parents[2] / 'src')!r})\n"
        "from swu_checkin import notify\n"
        f"root = Path({str(tmp_path)!r})\n"
        "os.environ['SWUDK_NOTIFY_TARGET'] = 'synthetic-never-routed'\n"
        f"os.environ['SWUDK_NOTIFY_DRY_RUN'] = {'1' if mode == 'dryrun' else '0'!r}\n"
        "notify.SEND_TIMEOUT = .5\nnotify.TERMINATE_GRACE = .05\n"
        "spawn = subprocess.Popen\nlaunches = []\n"
        "def fake(command, **kwargs):\n"
        f" assert ('--dry-run' in command) == {mode == 'dryrun'!r}\n"
        " launches.append(1)\n"
        f" return spawn([sys.executable, {str(script)!r}, '0'], **kwargs)\n"
        "notify.subprocess.Popen = fake\n"
        "write = Path.write_text\n"
        "def safe_write(path, *args, **kwargs):\n"
        f" if {mode!r} == 'marker_error' and path.name.startswith('notified-'): raise OSError('synthetic')\n"
        " return write(path, *args, **kwargs)\n"
        "Path.write_text = safe_write\n"
        "first = notify.main()\nsecond = notify.main()\n"
        "assert launches == [1], 'uncertain send must not replay'\n"
        f"expected = {1 if mode in ('nested_timeout', 'term_leader', 'marker_error') else 0}\n"
        "assert first == second == expected\n"
        "assert len(list(root.glob('notify-attempt-*'))) == 1\n"
        "assert bool(list(root.glob('notified-*'))) == (expected == 0)\n"
        "(root / 'application-returned').write_text(str(first))\n"
    )
    properties = {
        # Copy only lifecycle/sandbox settings, NEVER production paths, env or ExecStart.
        key: service[key]
        for key in (
            "Type",
            "TimeoutStartSec",
            "NoNewPrivileges",
            "PrivateTmp",
            "PrivateDevices",
            "ProtectSystem",
            "ProtectHome",
            "ProtectKernelTunables",
            "ProtectKernelModules",
            "ProtectKernelLogs",
            "ProtectControlGroups",
            "RestrictSUIDSGID",
            "LockPersonality",
            "CapabilityBoundingSet",
            "RestrictAddressFamilies",
        )
    }
    for key in ("KillMode", "TimeoutStopSec", "SendSIGKILL"):
        if key in service:
            properties[key] = service[key]
    properties.update(
        {
            "PrivateNetwork": "yes",
            "ReadWritePaths": str(tmp_path),
            "Environment": f"HOME={tmp_path} XDG_CONFIG_HOME={tmp_path} SWUDK_STATE_DIR={tmp_path}",
        }
    )
    command = ["systemd-run", "--quiet", "--wait", f"--unit={name}"]
    for key, value in properties.items():
        command += ["--property", f"{key}={value}"]
    command += [sys.executable, str(driver)]
    runner = None
    owned = {}
    cgroup = None
    try:
        runner = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 5
        while not (tmp_path / "application-returned").exists() and time.monotonic() < deadline:
            if runner.poll() is not None:
                pytest.fail(f"synthetic unit did not start: {runner.communicate()}")
            time.sleep(0.01)
        assert (tmp_path / "application-returned").exists()
        for role in (1, 2):
            pid = int((tmp_path / f"pid-{role}").read_text())
            owned[pid] = os.pidfd_open(pid)
        cgroup = subprocess.check_output(
            ["systemctl", "show", name, "--property=ControlGroup", "--value"], text=True
        ).strip()
        assert cgroup.startswith("/system.slice/swu-fixture-")
        started = time.monotonic()
        while runner.poll() is None and time.monotonic() - started < 5:
            time.sleep(0.01)
        assert runner.poll() is not None, "unit completion exceeded short cgroup stop budget"
        runner.communicate(timeout=1)
        state = subprocess.check_output(
            ["systemctl", "show", name, "--property=ActiveState", "--value"], text=True
        ).strip()
        assert state in {"inactive", "failed"}
        events = select.poll()
        for fd in owned.values():
            events.register(fd, select.POLLIN)
        assert len(events.poll(1000)) == len(owned)
        for pid in owned:
            assert not Path(f"/proc/{pid}").exists()
        for pidfile in tmp_path.glob("pid-*"):
            assert not Path(f"/proc/{int(pidfile.read_text())}").exists()
        directory = Path("/sys/fs/cgroup") / cgroup.lstrip("/")
        assert not directory.exists() or not (directory / "cgroup.procs").read_text().strip()
        print(
            f"fixture={name} mode={mode} unit_state={state} stop_elapsed={time.monotonic() - started:.3f} cgroup_empty=true owned_pids_absent=true"
        )
    finally:
        # Exact private fixture unit and pidfd identities only; no production unit calls.
        subprocess.run(["systemctl", "kill", "--signal=KILL", name], capture_output=True)
        subprocess.run(["systemctl", "stop", name], capture_output=True, timeout=10)
        if runner is not None:
            runner.communicate(timeout=5)
        for fd in owned.values():
            try:
                signal.pidfd_send_signal(fd, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.close(fd)
        subprocess.run(["systemctl", "reset-failed", name], capture_output=True)
