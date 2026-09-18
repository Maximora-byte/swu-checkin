"""Strict GitHub Actions adapter for the stable CLI JSON document."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .models import SCHEMA_VERSION, STATUS_NAMES
from .status import CheckinStatus, status_message

_REQUIRED_FIELDS = frozenset({"schema_version", "mode", "status", "code", "message", "attempts", "duration_ms"})


def parse_checkin_result(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or not _REQUIRED_FIELDS.issubset(payload):
        raise ValueError("missing required result fields")
    if isinstance(payload["schema_version"], bool) or payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported schema version")
    if payload["mode"] != "checkin":
        raise ValueError("Actions requires checkin mode")
    code = payload["code"]
    if isinstance(code, bool) or not isinstance(code, int):
        raise ValueError("status code must be an integer")
    try:
        status = CheckinStatus(code)
    except ValueError as error:
        raise ValueError("unknown status code") from error
    if not isinstance(payload["status"], str) or not isinstance(payload["message"], str):
        raise ValueError("status fields must be strings")
    if payload["status"] != STATUS_NAMES[status] or payload["message"] != status_message(status):
        raise ValueError("status fields are inconsistent")
    attempts = payload["attempts"]
    duration_ms = payload["duration_ms"]
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise ValueError("invalid attempts")
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms < 0:
        raise ValueError("invalid duration")
    return payload


def load_checkin_result(path: Path) -> dict[str, object]:
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("invalid check-in JSON document") from error
    return parse_checkin_result(payload)


def write_github_outputs(payload: dict[str, object], output_path: Path) -> None:
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(f"status_code={payload['code']}\n")
        handle.write(f"status_msg={payload['message']}\n")
        handle.write(f"status_name={payload['status']}\n")
        handle.write(f"full_result={compact}\n")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 2:
        print("用法：python -m swu_checkin.actions_result RESULT_JSON GITHUB_OUTPUT", file=sys.stderr)
        return 2
    try:
        payload = load_checkin_result(Path(arguments[0]))
        write_github_outputs(payload, Path(arguments[1]))
    except (OSError, ValueError) as error:
        print(f"结构化签到结果无效：{type(error).__name__}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
