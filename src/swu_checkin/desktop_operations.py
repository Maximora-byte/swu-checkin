"""Shared desktop service adapter; no platform-specific storage or scheduling."""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import formal_execution
from .desktop_errors import DesktopError, DesktopErrorCode
from .models import CheckinResult
from .service import CheckinService, run_checkin, run_probe
from .storage import load_run_status, record_run_status
from .token_store import TokenStore


class DesktopOperations:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.last_warning = ""

    def _options(self) -> dict:
        return {"token_store": TokenStore(self.root / "auth-token-cache")}

    def diagnose(self, username: str, password: str) -> bool:
        report = CheckinService(timeout=10, **self._options()).diagnose(
            username, password, read_token_cache=False, write_token_cache=False
        )
        return all(
            (
                report.authentication,
                report.leave_policy,
                report.student_profile,
                report.dormitory_schema,
                report.checkin_api,
            )
        )

    def probe(self, username: str, password: str) -> CheckinResult:
        return run_probe(username, password, 10, **self._options())

    def check_in(self, username: str, password: str) -> CheckinResult:
        if os.getenv("SWUDK_PROBE_ONLY") == "1":
            raise DesktopError(DesktopErrorCode.READONLY_ENABLED)

        # The same OS lock and default path as cli.main; direct GUI calls cannot bypass it.
        def execute() -> CheckinResult:
            result = run_checkin(username, password, 10, **self._options())
            self.last_warning = ""
            try:
                record_run_status(str(self.root / "status.json"), result.code)
            except Exception:
                # The remote outcome is preserved even when local disk/state is damaged.
                self.last_warning = "签到结果已返回，但本地状态未能保存。请查看本次结果，勿盲目重复提交。"
            return result

        return formal_execution.execute_formal_checkin_with_lock(execute)

    def status_text(self) -> str:
        lines = []
        try:
            status = load_run_status(str(self.root / "status.json"))
            if status and status.attempts:
                last = status.attempts[-1]
                lines.append(f"最近正式执行：{last.at}　{last.message}")
            else:
                lines.append("尚无本地正式签到记录")
        except Exception:
            lines.append("本地签到状态损坏或不可读取；这不代表学校签到失败")
        try:
            recent = json.loads((self.root / "desktop-last-run.json").read_text(encoding="utf-8"))
            if isinstance(recent, dict) and isinstance(recent.get("at"), str):
                result = CheckinResult.from_dict(recent.get("result"))
                label = "只读检测" if result.mode == "probe" else "正式签到"
                lines.append(f"最近定时{label}：{recent['at']}　{result.message}")
        except FileNotFoundError:
            pass
        except Exception:
            lines.append("最近定时结果不可读取")
        return "\n".join(lines)
