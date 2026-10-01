"""Single ownership boundary for formal CLI and desktop execution."""

from collections.abc import Callable

from .runtime_lock import RuntimeLock


def execute_formal_checkin_with_lock[T](operation: Callable[[], T]) -> T:
    """Keep credential acquisition, execution and status recording in one lock."""
    with RuntimeLock():
        return operation()
