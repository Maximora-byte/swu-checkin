import os
import subprocess
import sys
import textwrap

import pytest

from swu_checkin.runtime_lock import RuntimeLock, RuntimeLockError, default_lock_path

SUBPROCESS_PROGRAM = textwrap.dedent(
    """
    import os
    import sys

    from swu_checkin.runtime_lock import RuntimeLock

    lock = RuntimeLock(sys.argv[2])
    if not lock.acquire():
        print("busy", flush=True)
        raise SystemExit(3)
    print("acquired", flush=True)
    if sys.argv[1] == "hold":
        sys.stdin.readline()
        lock.release()
    elif sys.argv[1] == "exit-without-release":
        os._exit(0)
    else:
        lock.release()
    """
)


def _run_once(lock_path):
    return subprocess.run(
        [sys.executable, "-u", "-c", SUBPROCESS_PROGRAM, "once", str(lock_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_lock_is_reusable_after_release(tmp_path):
    lock = RuntimeLock(tmp_path / "checkin.lock")

    assert lock.acquire() is True
    assert lock.acquired is True
    lock.release()
    assert lock.acquired is False
    assert lock.acquire() is True
    lock.release()


def test_context_manager_releases_after_exception(tmp_path):
    path = tmp_path / "checkin.lock"

    with pytest.raises(RuntimeError, match="expected"):
        with RuntimeLock(path):
            raise RuntimeError("expected")

    contender = RuntimeLock(path)
    assert contender.acquire() is True
    contender.release()


def test_lock_file_contains_no_sensitive_runtime_data(tmp_path):
    path = tmp_path / "checkin.lock"

    with RuntimeLock(path):
        content = path.read_bytes()

    assert content in {b"", b"\0"}


@pytest.mark.skipif(os.name != "nt", reason="Windows default lock domain")
def test_windows_default_lock_path_is_shared_under_local_appdata(monkeypatch, tmp_path):
    monkeypatch.delenv("SWUDK_LOCK_FILE", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert default_lock_path() == tmp_path / "SWUCheckin" / "checkin.lock"


def test_real_subprocess_contention_is_non_blocking_and_release_is_reusable(tmp_path):
    path = tmp_path / "checkin.lock"
    holder = subprocess.Popen(
        [sys.executable, "-u", "-c", SUBPROCESS_PROGRAM, "hold", str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "acquired"

        contender = _run_once(path)
        assert contender.returncode == 3
        assert contender.stdout.strip() == "busy"

        assert holder.stdin is not None
        holder.stdin.write("release\n")
        holder.stdin.flush()
        assert holder.wait(timeout=10) == 0

        after_release = _run_once(path)
        assert after_release.returncode == 0
        assert after_release.stdout.strip() == "acquired"
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=10)


def test_process_exit_releases_os_lock_without_stale_pid_logic(tmp_path):
    path = tmp_path / "checkin.lock"
    completed = subprocess.run(
        [sys.executable, "-u", "-c", SUBPROCESS_PROGRAM, "exit-without-release", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0
    after_exit = _run_once(path)
    assert after_exit.returncode == 0
    assert after_exit.stdout.strip() == "acquired"


@pytest.mark.skipif(os.name == "nt", reason="POSIX symbolic-link safety check")
def test_posix_rejects_symbolic_link_lock_target(tmp_path):
    real_file = tmp_path / "real.lock"
    real_file.touch()
    symlink = tmp_path / "checkin.lock"
    symlink.symlink_to(real_file)

    with pytest.raises(RuntimeLockError):
        RuntimeLock(symlink).acquire()
