"""Atomic non-sensitive run-status storage shared with the notifier."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .status import CheckinStatus, is_successful_checkin_status, status_message
from .time_utils import now_shanghai


def record_run_status(status_path: str, result: CheckinStatus | int) -> None:
    """Record a result without changing the notifier's established JSON format."""

    path = Path(status_path)
    now = now_shanghai()
    today = now.date().isoformat()
    current: dict = {}
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        pass

    attempts = current.get("attempts", []) if current.get("date") == today else []
    if not isinstance(attempts, list):
        attempts = []
    attempts.append(
        {
            "at": now.isoformat(timespec="seconds"),
            "code": int(result),
            "message": status_message(result),
        }
    )
    attempts = attempts[-10:]
    payload = {
        "date": today,
        "attempts": attempts,
        "successful": any(
            is_successful_checkin_status(attempt.get("code")) for attempt in attempts if isinstance(attempt, dict)
        ),
    }

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".status.", dir=path.parent, text=True)
    try:
        os.fchmod(descriptor, 0o640)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
