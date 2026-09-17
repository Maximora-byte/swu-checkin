"""Send one non-sensitive Telegram summary for the day's SWU check-in runs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .status import CheckinStatus
from .time_utils import today_shanghai

SUCCESS_CODES = {int(CheckinStatus.SUCCESS), int(CheckinStatus.ALREADY_CHECKED_IN)}
LEAVE_CODE = int(CheckinStatus.ON_LEAVE)


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
        print(f"{today} 已发送过通知，跳过")
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

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    except subprocess.TimeoutExpired:
        print("Telegram 通知发送超时", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print(f"Telegram 通知发送失败（退出码 {result.returncode}）", file=sys.stderr)
        return 1

    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    marker.write_text("sent\n", encoding="utf-8")
    os.chmod(marker, 0o600)
    print(f"{today} Telegram 通知发送成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
