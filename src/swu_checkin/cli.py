"""Command-line parsing, presentation, exit codes, and status recording."""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import time
from getpass import getpass
from typing import TextIO

from .models import CheckinResult
from .service import DEFAULT_MAX_ATTEMPTS, DEFAULT_RETRY_DELAY, run_checkin, run_probe
from .status import SUCCESSFUL_CHECKIN_STATUSES, SUCCESSFUL_PROBE_STATUSES, CheckinStatus
from .storage import record_run_status


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="西南大学宿舍签到")
    parser.add_argument("--json", action="store_true", dest="json_output", help="仅在 stdout 输出结构化 JSON")
    parser.add_argument("--probe", action="store_true", help="只登录并读取任务，绝不提交签到")
    return parser


def _credentials(*, json_output: bool) -> tuple[str, str]:
    username = os.getenv("SWUDK_USERNAME", "")
    if not username:
        if json_output:
            print("校园网账号：", end="", file=sys.stderr, flush=True)
            username = input().strip()
        else:
            username = input("校园网账号：").strip()
    password = os.getenv("SWUDK_PASSWORD", "") or getpass("校园网密码：")
    return username, password


def _successful(result: CheckinResult) -> bool:
    status = CheckinStatus(result.code)
    allowed = SUCCESSFUL_PROBE_STATUSES if result.mode == "probe" else SUCCESSFUL_CHECKIN_STATUSES
    return status in allowed


def _print_result(result: CheckinResult, *, json_output: bool, stream: TextIO | None = None) -> None:
    stream = stream or sys.stdout
    if json_output:
        print(result.to_json(), file=stream)
    else:
        print(f"[{result.code}] {result.message}", file=stream)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    probe_only = args.probe or os.getenv("SWUDK_PROBE_ONLY") == "1"
    username, password = _credentials(json_output=args.json_output)
    started = time.perf_counter()
    redirected = contextlib.redirect_stdout(sys.stderr) if args.json_output else contextlib.nullcontext()
    try:
        with redirected:
            if probe_only:
                result = run_probe(username, password, 10)
            else:
                result = run_checkin(
                    username,
                    password,
                    10,
                    max_attempts=_env_int("SWUDK_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS),
                    retry_delay=_env_int("SWUDK_RETRY_DELAY", DEFAULT_RETRY_DELAY),
                )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        result = CheckinResult.from_status(
            CheckinStatus.DATA_ERROR,
            attempts=1,
            duration_ms=duration_ms,
            mode="probe" if probe_only else "checkin",
        )
        print(f"未预期错误：{type(error).__name__}", file=sys.stderr)

    status_file = os.getenv("SWUDK_STATUS_FILE")
    if status_file and not probe_only:
        try:
            record_run_status(status_file, result.code)
        except OSError as error:
            print(f"状态记录失败：{type(error).__name__}", file=sys.stderr)

    _print_result(result, json_output=args.json_output)
    return 0 if _successful(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
