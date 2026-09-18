"""Stable, non-sensitive result models for CLI and automation consumers."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .status import CheckinStatus, status_message

SCHEMA_VERSION = 1

RESULT_FIELDS = frozenset({"schema_version", "mode", "status", "code", "message", "attempts", "duration_ms"})

ALLOWED_CODES_BY_MODE = {
    "checkin": frozenset(
        {
            int(CheckinStatus.NO_TASK),
            int(CheckinStatus.SUCCESS),
            int(CheckinStatus.ALREADY_CHECKED_IN),
            int(CheckinStatus.LOGIN_FAILED),
            int(CheckinStatus.DATA_ERROR),
            int(CheckinStatus.ON_LEAVE),
        }
    ),
    "probe": frozenset(
        {
            int(CheckinStatus.NO_TASK),
            int(CheckinStatus.ALREADY_CHECKED_IN),
            int(CheckinStatus.LOGIN_FAILED),
            int(CheckinStatus.DATA_ERROR),
            int(CheckinStatus.ON_LEAVE),
            int(CheckinStatus.PROBE_PENDING),
        }
    ),
}

STATUS_NAMES = {
    CheckinStatus.NO_TASK: "no_task",
    CheckinStatus.SUCCESS: "success",
    CheckinStatus.ALREADY_CHECKED_IN: "already_checked_in",
    CheckinStatus.LOGIN_FAILED: "login_failed",
    CheckinStatus.DATA_ERROR: "data_error",
    CheckinStatus.ON_LEAVE: "on_leave",
    CheckinStatus.PROBE_PENDING: "probe_pending",
}


@dataclass(frozen=True)
class CheckinResult:
    """One top-level check-in or probe execution result."""

    status: str
    code: int
    message: str
    attempts: int
    duration_ms: int
    mode: str

    def __post_init__(self) -> None:
        if not isinstance(self.mode, str) or self.mode not in ALLOWED_CODES_BY_MODE:
            raise ValueError("mode must be checkin or probe")
        if isinstance(self.code, bool) or not isinstance(self.code, int):
            raise ValueError("status code must be an integer")
        if self.code not in ALLOWED_CODES_BY_MODE[self.mode]:
            raise ValueError("status code is not valid for mode")
        try:
            normalized = CheckinStatus(self.code)
        except (TypeError, ValueError) as error:
            raise ValueError("unsupported check-in status code") from error
        if self.status != STATUS_NAMES[normalized]:
            raise ValueError("status name does not match status code")
        if self.message != status_message(normalized):
            raise ValueError("message does not match status code")
        if isinstance(self.attempts, bool) or not isinstance(self.attempts, int) or self.attempts < 1:
            raise ValueError("attempts must be a positive integer")
        if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int) or self.duration_ms < 0:
            raise ValueError("duration_ms must be a non-negative integer")

    @classmethod
    def from_status(
        cls,
        status: CheckinStatus | int,
        *,
        attempts: int,
        duration_ms: int,
        mode: str,
    ) -> CheckinResult:
        normalized = CheckinStatus(status)
        return cls(
            status=STATUS_NAMES[normalized],
            code=int(normalized),
            message=status_message(normalized),
            attempts=attempts,
            duration_ms=duration_ms,
            mode=mode,
        )

    @classmethod
    def from_dict(cls, payload: object) -> CheckinResult:
        """Validate and load exactly one schema-version-1 result document."""

        if not isinstance(payload, dict) or set(payload) != RESULT_FIELDS:
            raise ValueError("result fields do not match schema")
        schema_version = payload["schema_version"]
        if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported schema version")
        return cls(
            status=payload["status"],
            code=payload["code"],
            message=payload["message"],
            attempts=payload["attempts"],
            duration_ms=payload["duration_ms"],
            mode=payload["mode"],
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": self.mode,
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "attempts": self.attempts,
            "duration_ms": self.duration_ms,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))
