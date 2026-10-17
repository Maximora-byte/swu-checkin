"""Document the unresolved group boundary, NOT a whole-tree cleanup acceptance test."""

import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from swu_checkin import notify


@pytest.mark.skipif(sys.platform != "linux", reason="Linux subreaper and exact owned pidfds")
@pytest.mark.parametrize("leader_exits_on_term", [False, True])
def test_process_group_scope_excludes_detached_grandchildren(tmp_path, monkeypatch, leader_exits_on_term):
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0
    assert libc.prctl(36, 1, 0, 0, 0) == 0
    script = tmp_path / "fake_tree.py"
    script.write_text(
        "import os, signal, subprocess, sys, time\nfrom pathlib import Path\n"
        f"root = Path({str(tmp_path)!r})\n"
        "role = int(sys.argv[1])\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"if role == 0 and {leader_exits_on_term!r}: signal.signal(signal.SIGTERM, signal.SIG_DFL)\n"
        "(root / ('pid-' + str(role))).write_text(str(os.getpid()))\n"
        "if role < 2: subprocess.Popen([sys.executable, __file__, str(role + 1)], start_new_session=(role == 1))\n"
        "while True: time.sleep(0.01)\n"
    )
    monkeypatch.setattr(notify, "TERMINATE_GRACE", 0.05)
    process = None
    owned = {}
    try:
        process = subprocess.Popen(
            [sys.executable, str(script), "0"],
            env={"HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path), "PATH": os.defpath},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + 5
        while len(list(tmp_path.glob("pid-*"))) != 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        pids = [int((tmp_path / f"pid-{role}").read_text()) for role in range(3)]
        for pid in pids:
            owned[pid] = os.pidfd_open(pid)
        assert os.getpgid(pids[2]) != process.pid
        assert os.getsid(pids[2]) != process.pid
        notify._stop_send(process)
        # This demonstrates the open containment gap. Do not change this into an
        # assertion that standalone killpg provides bounded whole-tree cleanup.
        assert Path(f"/proc/{pids[2]}/stat").read_text().split()[2] != "Z"
    finally:
        # Only signal identities belonging to these synthetic children. Adopt and
        # reap the escaped grandchild; never scan/kill unrelated process trees.
        for pidfile in tmp_path.glob("pid-*"):
            pid = int(pidfile.read_text())
            if pid not in owned:
                try:
                    owned[pid] = os.pidfd_open(pid)
                except ProcessLookupError:
                    pass
        for fd in owned.values():
            try:
                signal.pidfd_send_signal(fd, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process is not None:
            process.wait(timeout=5)
        for pid, fd in owned.items():
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
            os.close(fd)
        assert libc.prctl(36, previous.value, 0, 0, 0) == 0
        assert all(not Path(f"/proc/{pid}").exists() for pid in owned)
