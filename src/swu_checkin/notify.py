"""Send one non-sensitive Telegram summary for the day's SWU check-in runs."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .status import CheckinStatus
from .time_utils import today_shanghai

SUCCESS_CODES = {int(CheckinStatus.SUCCESS), int(CheckinStatus.ALREADY_CHECKED_IN)}
LEAVE_CODE = int(CheckinStatus.ON_LEAVE)
SEND_TIMEOUT = 60
TERMINATE_GRACE = 2


def _stop_send(process: subprocess.Popen) -> None:
    """Stop the original POSIX group only; detached descendants need external containment."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        # Do not reap the leader before KILL: keep its PID reserved as the PGID.
        time.sleep(TERMINATE_GRACE)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Darwin can report EPERM for a group containing only an unreaped
            # zombie. Reap the leader, then require proof the entire group is
            # gone; leader exit alone does not prove descendants have stopped.
            process.wait(timeout=TERMINATE_GRACE)
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return
            except OSError:
                pass
            # Never send another destructive signal after releasing the PID.
            # A surviving/reused group or inconclusive probe remains a failure.
            raise
    else:
        # The notifier is deployed on Linux; other platforms only kill the child.
        process.kill()
    process.wait(timeout=TERMINATE_GRACE)


def _load_status(path: Path, today: str) -> tuple[list[dict], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        return [], "没有读取到今天的任务结果"
    if payload.get("date") != today or not isinstance(payload.get("attempts"), list):
        return [], "今天没有产生有效的任务结果"
    attempts = [attempt for attempt in payload["attempts"] if isinstance(attempt, dict)]
    if not attempts:
        return [], "今天没有产生有效的任务结果"
    return attempts, ""


def _build_message(attempts: list[dict], today: str, error: str) -> str:
    if error:
        return f"❌ SWU 宿舍签到未完成\n日期：{today}\n原因：{error}\n请尽快手动检查。"

    successful = [attempt for attempt in attempts if attempt.get("code") in SUCCESS_CODES]
    leave = [attempt for attempt in attempts if attempt.get("code") == LEAVE_CODE]
    last = attempts[-1] if attempts else {}
    if successful:
        result = successful[-1].get("message", "已签到")
        return f"✅ SWU 宿舍签到成功\n日期：{today}\n结果：{result}\n今日执行：{len(attempts)} 次"
    if leave:
        return f"ℹ️ SWU 宿舍签到：今日无需签到\n日期：{today}\n原因：请假期间\n今日执行：{len(attempts)} 次"

    result = last.get("message", "未知错误")
    return f"❌ SWU 宿舍签到未完成\n日期：{today}\n最后结果：{result}\n今日执行：{len(attempts)} 次\n请尽快手动检查。"


def main() -> int:
    state_dir = Path(os.getenv("SWUDK_STATE_DIR", "/var/lib/swu-checkin"))
    today = today_shanghai()
    marker = state_dir / f"notified-{today}"
    if marker.exists():
        print(f"{today} CLI 完成标记已存在，跳过；平台送达未核验")
        return 0

    attempts, error = _load_status(state_dir / "status.json", today)
    message = _build_message(attempts, today, error)
    target = os.getenv("SWUDK_NOTIFY_TARGET", "").strip()
    if not target:
        print("Telegram 通知未配置：缺少 SWUDK_NOTIFY_TARGET", file=sys.stderr)
        return 2

    command = [
        "/usr/bin/openclaw",
        "message",
        "send",
        "--channel",
        os.getenv("SWUDK_NOTIFY_CHANNEL", "telegram"),
        "--account",
        os.getenv("SWUDK_NOTIFY_ACCOUNT", "default"),
        "--target",
        target,
        "--message",
        message,
        "--json",
    ]
    if os.getenv("SWUDK_NOTIFY_DRY_RUN") == "1":
        command.append("--dry-run")

    # Claim before spawning: an interrupted or failed CLI may already have sent.
    # This is a conservative replay quarantine, never a platform delivery receipt.
    attempt = state_dir / f"notify-attempt-{today}"
    try:
        state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(attempt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("delivery_unverified\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        print("notify stage=guard reason=attempt_exists outcome=delivery_unverified", file=sys.stderr)
        return 1
    except OSError:
        print("notify stage=guard reason=state_error outcome=not_sent", file=sys.stderr)
        return 1

    started = time.monotonic()
    try:
        # Never retain untrusted CLI output (secrets, unbounded data or held pipes).
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name == "posix",
        )
    except OSError:
        elapsed_ms = min(999999, max(0, int((time.monotonic() - started) * 1000)))
        print(f"notify stage=spawn reason=spawn_error outcome=not_sent elapsed_ms={elapsed_ms}", file=sys.stderr)
        return 1
    try:
        returncode = process.wait(timeout=SEND_TIMEOUT)
    except subprocess.TimeoutExpired:
        reason = "timeout"
        try:
            _stop_send(process)
        except subprocess.TimeoutExpired:
            reason = "cleanup_timeout"
        except OSError:
            # Never render cleanup exceptions: their chained timeout contains
            # the private command. Preserve quarantine and report failure only.
            reason = "cleanup_error"
        elapsed_ms = min(999999, max(0, int((time.monotonic() - started) * 1000)))
        print(
            f"notify stage=send reason={reason} outcome=unknown_after_send elapsed_ms={elapsed_ms}",
            file=sys.stderr,
        )
        return 1
    if returncode != 0:
        elapsed_ms = min(999999, max(0, int((time.monotonic() - started) * 1000)))
        reason = "signal_exit" if returncode < 0 else "nonzero_exit"
        exit_detail = f"signal={-returncode}" if returncode < 0 else f"exit={returncode}"
        print(
            f"notify stage=send reason={reason} outcome=unknown_after_send {exit_detail} elapsed_ms={elapsed_ms}",
            file=sys.stderr,
        )
        return 1

    try:
        marker.write_text("sent\n", encoding="utf-8")
        os.chmod(marker, 0o600)
    except OSError:
        print("notify stage=state reason=marker_error outcome=delivery_unverified", file=sys.stderr)
        return 1
    print(f"{today} CLI 已退出 0；平台送达未核验")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
