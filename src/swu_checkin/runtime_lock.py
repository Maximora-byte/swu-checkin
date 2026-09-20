"""Cross-process, non-blocking lock for formal CLI check-in runs."""

from __future__ import annotations

import errno
import importlib
import os
import stat
import tempfile
from pathlib import Path
from types import ModuleType


class RuntimeLockError(RuntimeError):
    """The runtime lock could not be managed safely."""


class RuntimeLockBusy(RuntimeLockError):
    """Another formal check-in process currently owns the lock."""


def default_lock_path() -> Path:
    """Return the shared lock path for the current platform."""
    override = os.getenv("SWUDK_LOCK_FILE", "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise RuntimeLockError("SWUDK_LOCK_FILE must be an absolute path")
        return path

    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA", "").strip()
        root = Path(base) if base else Path(tempfile.gettempdir())
        return root / "SWUCheckin" / "checkin.lock"

    deployed_state = Path("/var/lib/swu-checkin")
    if deployed_state.is_dir():
        return deployed_state / "checkin.lock"

    runtime_dir = os.getenv("XDG_RUNTIME_DIR", "").strip()
    if runtime_dir:
        return Path(runtime_dir) / "swu-checkin.lock"
    return Path(tempfile.gettempdir()) / f"swu-checkin-{os.getuid()}.lock"


class RuntimeLock:
    """Own an OS-managed advisory lock without waiting for another process."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_lock_path()
        self._fd: int | None = None
        self._platform_module: ModuleType | None = None

    @property
    def acquired(self) -> bool:
        return self._fd is not None

    def acquire(self) -> bool:
        """Acquire immediately, returning false when another process owns it."""
        if self.acquired:
            raise RuntimeLockError("runtime lock is already acquired")
        if not self.path.is_absolute():
            raise RuntimeLockError("runtime lock path must be absolute")

        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = self._open_lock_file()
        except OSError as error:
            raise RuntimeLockError("unable to open runtime lock safely") from error

        try:
            self._validate_open_file(fd)
            acquired = self._acquire_os_lock(fd)
        except Exception:
            os.close(fd)
            raise
        if not acquired:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        """Release and close the lock file descriptor."""
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        try:
            self._release_os_lock(fd)
        finally:
            os.close(fd)

    def __enter__(self) -> RuntimeLock:
        if not self.acquire():
            raise RuntimeLockBusy("another check-in process owns the runtime lock")
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.release()

    def _open_lock_file(self) -> int:
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        flags |= getattr(os, "O_BINARY", 0)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if nofollow:
            flags |= nofollow
        elif self.path.is_symlink():
            raise RuntimeLockError("refusing a symbolic-link runtime lock")
        return os.open(self.path, flags, 0o660)

    def _validate_open_file(self, fd: int) -> None:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise RuntimeLockError("runtime lock is not a regular file")
        try:
            target = self.path.lstat()
        except OSError as error:
            raise RuntimeLockError("runtime lock path changed during open") from error
        if stat.S_ISLNK(target.st_mode):
            raise RuntimeLockError("refusing a symbolic-link runtime lock")
        if (opened.st_dev, opened.st_ino) != (target.st_dev, target.st_ino):
            raise RuntimeLockError("runtime lock path changed during open")

    def _acquire_os_lock(self, fd: int) -> bool:
        if os.name == "nt":
            module = importlib.import_module("msvcrt")
            self._platform_module = module
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                module.locking(fd, module.LK_NBLCK, 1)
            except OSError as error:
                if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or getattr(error, "winerror", None) in {
                    33,
                    36,
                    158,
                }:
                    return False
                raise RuntimeLockError("unable to acquire runtime lock") from error
            return True

        module = importlib.import_module("fcntl")
        self._platform_module = module
        try:
            module.flock(fd, module.LOCK_EX | module.LOCK_NB)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN}:
                return False
            raise RuntimeLockError("unable to acquire runtime lock") from error
        return True

    def _release_os_lock(self, fd: int) -> None:
        module = self._platform_module
        if module is None:
            return
        if os.name == "nt":
            os.lseek(fd, 0, os.SEEK_SET)
            module.locking(fd, module.LK_UNLCK, 1)
        else:
            module.flock(fd, module.LOCK_UN)
