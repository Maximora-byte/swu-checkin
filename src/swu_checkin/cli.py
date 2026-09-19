"""Command-line parsing, presentation, exit codes, and status recording."""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import time
from getpass import getpass
from pathlib import Path
from typing import TextIO

from .models import CheckinResult
from .service import DEFAULT_MAX_ATTEMPTS, DEFAULT_RETRY_DELAY, CheckinService, DoctorReport, run_checkin, run_probe
from .status import SUCCESSFUL_CHECKIN_STATUSES, SUCCESSFUL_PROBE_STATUSES, CheckinStatus
from .storage import StatusStorageError, load_run_status, record_run_status

DEFAULT_STATUS_FILE = "/var/lib/swu-checkin/status.json"


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
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("setup", help="交互验证账号和接口（不保存密码）")
    commands.add_parser("doctor", help="运行只读环境与接口诊断")
    status_parser = commands.add_parser(
        "status",
        help="读取已有的本地运行状态（不发网络请求）",
        description=(
            "读取已有的非敏感 status 文件。systemd 默认路径为 /var/lib/swu-checkin/status.json；"
            "普通本地 run 仅在设置 SWUDK_STATUS_FILE 时记录。"
        ),
    )
    status_parser.add_argument("--file", dest="status_file", help="状态文件路径")
    run_parser = commands.add_parser("run", help="立即执行正式签到")
    run_parser.add_argument("--json", action="store_true", dest="command_json", help="输出 schema v1 JSON")
    probe_parser = commands.add_parser("probe", help="只读检测，不提交签到")
    probe_parser.add_argument("--json", action="store_true", dest="command_json", help="输出 schema v1 JSON")
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


def _interactive_credentials() -> tuple[str, str]:
    return input("校园网账号：").strip(), getpass("校园网密码：")


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


def _execute(*, probe_only: bool, json_output: bool) -> int:
    username, password = _credentials(json_output=json_output)
    started = time.perf_counter()
    redirected = contextlib.redirect_stdout(sys.stderr) if json_output else contextlib.nullcontext()
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

    _print_result(result, json_output=json_output)
    return 0 if _successful(result) else 1


def _setup() -> int:
    username, password = _interactive_credentials()
    if not username or not password:
        print("配置验证失败：账号和密码不能为空")
        return 1
    try:
        report = CheckinService(timeout=10).diagnose(
            username,
            password,
            read_token_cache=False,
            write_token_cache=False,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        print(f"配置验证失败：{type(error).__name__}", file=sys.stderr)
        return 1
    if not _doctor_report_passed(report):
        print("配置验证失败；未保存任何凭据。")
        return 1
    print("配置验证成功；本版本不会保存密码或创建明文凭据文件。")
    print("自动化运行请使用受限权限的环境文件或 Secret，本地运行可继续交互输入。")
    return 0


def _doctor_lines(*, runtime: bool, credentials: bool, report: DoctorReport | None) -> list[tuple[str, bool]]:
    return [
        ("Runtime", runtime),
        ("Credentials", credentials),
        ("SWU Authentication", bool(report and report.authentication)),
        ("Leave API", bool(report and report.leave_policy)),
        ("Student Profile", bool(report and report.student_profile)),
        ("Dormitory Schema", bool(report and report.dormitory_schema)),
        ("Check-in API", bool(report and report.checkin_api)),
    ]


def _doctor_report_passed(report: DoctorReport) -> bool:
    return all(
        (
            report.authentication,
            report.leave_policy,
            report.student_profile,
            report.dormitory_schema,
            report.checkin_api,
        )
    )


def _doctor() -> int:
    username, password = _credentials(json_output=False)
    credentials = bool(username and password)
    runtime = sys.version_info >= (3, 13)
    try:
        report = (
            CheckinService(timeout=10).diagnose(
                username,
                password,
                read_token_cache=False,
                write_token_cache=False,
            )
            if credentials
            else None
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        print(f"诊断失败：{type(error).__name__}", file=sys.stderr)
        report = None
    lines = _doctor_lines(runtime=runtime, credentials=credentials, report=report)
    for label, passed in lines:
        print(f"{label:<20} {'✓' if passed else '✗'}")
    return 0 if all(passed for _label, passed in lines) else 1


def _status(status_file: str | None) -> int:
    path = status_file or os.getenv("SWUDK_STATUS_FILE") or DEFAULT_STATUS_FILE
    try:
        status = load_run_status(path)
    except StatusStorageError as error:
        print(str(error), file=sys.stderr)
        return 1
    if status is None:
        print(f"尚无本地运行状态：{Path(path)}")
        return 0
    print(f"日期：{status.date}")
    print(f"结果：{'成功' if status.successful else '未成功'}")
    if status.attempts:
        latest = status.attempts[-1]
        print(f"最近一次：[{latest.code}] {latest.message}（{latest.at}）")
    else:
        print("最近一次：无运行记录")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command in {"setup", "doctor", "status"} and (args.json_output or args.probe):
        parser.error("setup、doctor 和 status 不支持旧式 --json/--probe 选项")
    if args.command == "setup":
        return _setup()
    if args.command == "doctor":
        return _doctor()
    if args.command == "status":
        return _status(args.status_file)

    if args.command == "run" and args.probe:
        parser.error("run 不能与旧式 --probe 同时使用")

    probe_environment = os.getenv("SWUDK_PROBE_ONLY") == "1"
    if args.command == "run" and probe_environment:
        print("安全开关 SWUDK_PROBE_ONLY=1 已启用，拒绝执行正式签到。", file=sys.stderr)
        return 2

    command_json = getattr(args, "command_json", False)
    json_output = args.json_output or command_json
    probe_only = args.command == "probe" or (args.command is None and (args.probe or probe_environment))
    return _execute(probe_only=probe_only, json_output=json_output)


if __name__ == "__main__":
    raise SystemExit(main())
