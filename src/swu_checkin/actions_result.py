"""Strict GitHub Actions adapter for the stable CLI JSON document."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .models import CheckinResult


def parse_checkin_result(payload: object) -> dict[str, object]:
    result = CheckinResult.from_dict(payload)
    if result.mode != "checkin":
        raise ValueError("Actions requires checkin mode")
    return result.to_dict()


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
