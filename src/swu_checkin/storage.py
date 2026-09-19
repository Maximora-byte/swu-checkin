"""Atomic non-sensitive run-status storage shared with the notifier."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .status import CheckinStatus, is_successful_checkin_status, status_message
from .time_utils import now_shanghai


class StatusStorageError(ValueError):
    """The local non-sensitive status file is missing required structure."""


@dataclass(frozen=True)
class StoredAttempt:
    at: str
    code: int
    message: str


@dataclass(frozen=True)
class StoredRunStatus:
    date: str
    attempts: tuple[StoredAttempt, ...]
    successful: bool


def load_run_status(status_path: str) -> StoredRunStatus | None:
    """Load only the established non-sensitive status fields without network access."""

    path = Path(status_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as error:
        raise StatusStorageError("无法读取本地状态文件") from error
    if not isinstance(payload, dict) or set(payload) != {"date", "attempts", "successful"}:
        raise StatusStorageError("本地状态文件结构无效")
    if not isinstance(payload["date"], str) or not isinstance(payload["successful"], bool):
        raise StatusStorageError("本地状态文件字段无效")
    try:
        date.fromisoformat(payload["date"])
    except ValueError as error:
        raise StatusStorageError("本地状态日期无效") from error
    raw_attempts = payload["attempts"]
    if not isinstance(raw_attempts, list) or len(raw_attempts) > 10:
        raise StatusStorageError("本地状态记录无效")
    attempts: list[StoredAttempt] = []
    for raw in raw_attempts:
        if not isinstance(raw, dict) or set(raw) != {"at", "code", "message"}:
            raise StatusStorageError("本地状态记录无效")
        code = raw["code"]
        if isinstance(code, bool) or not isinstance(code, int):
            raise StatusStorageError("本地状态码无效")
        try:
            normalized = CheckinStatus(code)
        except ValueError as error:
            raise StatusStorageError("本地状态码无效") from error
        if normalized is CheckinStatus.PROBE_PENDING:
            raise StatusStorageError("本地状态码无效")
        if not isinstance(raw["at"], str) or raw["message"] != status_message(normalized):
            raise StatusStorageError("本地状态记录无效")
        try:
            datetime.fromisoformat(raw["at"])
        except ValueError as error:
            raise StatusStorageError("本地状态时间无效") from error
        attempts.append(StoredAttempt(at=raw["at"], code=code, message=raw["message"]))
    expected_success = any(is_successful_checkin_status(attempt.code) for attempt in attempts)
    if payload["successful"] is not expected_success:
        raise StatusStorageError("本地状态成功标记不一致")
    return StoredRunStatus(date=payload["date"], attempts=tuple(attempts), successful=payload["successful"])


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
