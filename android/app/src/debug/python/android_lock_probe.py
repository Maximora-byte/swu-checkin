"""Debug-only synthetic cross-process lock helpers, never authentication."""

from swu_checkin.runtime_lock import RuntimeLock

_held: RuntimeLock | None = None


def try_once(path: str) -> bool:
    lock = RuntimeLock(path)
    acquired = lock.acquire()
    lock.release()
    return acquired


def hold(path: str) -> bool:
    global _held
    if _held is not None:
        return False
    lock = RuntimeLock(path)
    if not lock.acquire():
        return False
    _held = lock
    return True


def release() -> None:
    global _held
    if _held is not None:
        _held.release()
    _held = None
