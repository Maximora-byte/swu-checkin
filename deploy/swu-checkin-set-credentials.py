#!/usr/bin/env python3
"""Securely store SWU credentials, probe login, then enable the timer."""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CREDENTIAL_DIR = Path("/etc/swu-checkin")
CREDENTIAL_FILE = CREDENTIAL_DIR / "credentials.env"
NOTIFY_FILE = CREDENTIAL_DIR / "notify.env"


def _quote_environment_value(value: str) -> str:
    if "\0" in value or "\n" in value or "\r" in value:
        raise ValueError("凭据不能包含 NUL 或换行符")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _write_credentials(username: str, password: str) -> None:
    CREDENTIAL_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(CREDENTIAL_DIR, 0o700)
    content = (
        f"SWUDK_USERNAME={_quote_environment_value(username)}\nSWUDK_PASSWORD={_quote_environment_value(password)}\n"
    )

    descriptor, temporary_name = tempfile.mkstemp(prefix=".credentials.", dir=CREDENTIAL_DIR, text=True)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, CREDENTIAL_FILE)
        os.chmod(CREDENTIAL_FILE, 0o600)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    if os.geteuid() != 0:
        print("请使用 sudo 运行此命令。", file=sys.stderr)
        return 2

    username = input("西南大学统一身份认证账号：").strip()
    password = getpass.getpass("西南大学统一身份认证密码（输入不显示）：")
    confirmation = getpass.getpass("再次输入密码：")
    if not username or not password:
        print("账号和密码不能为空。", file=sys.stderr)
        return 2
    if password != confirmation:
        print("两次密码不一致，未保存。", file=sys.stderr)
        return 2

    _write_credentials(username, password)
    print("凭据已安全保存，正在执行只读登录探测（不会提交签到）……")
    probe = subprocess.run(["systemctl", "start", "swu-checkin-probe.service"], check=False)
    if probe.returncode != 0:
        print("只读探测失败，定时器未启用。请查看：", file=sys.stderr)
        print("  journalctl -u swu-checkin-probe.service -n 30 --no-pager", file=sys.stderr)
        return 1

    subprocess.run(["systemctl", "enable", "--now", "swu-checkin.timer"], check=True)
    print("只读探测通过，swu-checkin.timer 已启用。")
    if NOTIFY_FILE.exists():
        subprocess.run(["systemctl", "enable", "--now", "swu-checkin-notify.timer"], check=True)
        print("检测到 Telegram 通知配置，swu-checkin-notify.timer 已启用。")
    else:
        print("未检测到 /etc/swu-checkin/notify.env；Telegram 通知 timer 保持未启用。")
    subprocess.run(["systemctl", "list-timers", "swu-checkin.timer", "--no-pager"], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
