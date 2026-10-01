"""Windows desktop operations; no network, credential reads or tasks at import time."""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath
from uuid import uuid4
from xml.etree import ElementTree as ET

from . import formal_execution
from .desktop_errors import DesktopError, DesktopErrorCode
from .models import CheckinResult
from .runtime_lock import RuntimeLock
from .service import CheckinService, run_checkin, run_probe
from .status import SUCCESSFUL_CHECKIN_STATUSES, SUCCESSFUL_PROBE_STATUSES, CheckinStatus
from .storage import load_run_status, record_run_status
from .token_store import TokenStore, WindowsDpapiProtector

TASK_NAME = "SWUCheckin-Desktop"
LEGACY_TASK_NAME = "SWUCheckin-Daily"
TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def app_root() -> Path:
    value = os.getenv("LOCALAPPDATA", "").strip()
    if sys.platform != "win32" or not value or not Path(value).is_absolute():
        raise DesktopError(DesktopErrorCode.WINDOWS_REQUIRED)
    return Path(value) / "SWUCheckin"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".desktop-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def task_xml(executable: str, sid: str, now: datetime | None = None) -> bytes:
    """A per-user non-elevated task; paths are XML escaped, never shell interpolated."""
    if not executable or not sid:
        raise DesktopError(DesktopErrorCode.TASK_IDENTITY_MISSING)
    ET.register_namespace("", TASK_NS)

    def element(parent: ET.Element, name: str, text: str | None = None) -> ET.Element:
        child = ET.SubElement(parent, f"{{{TASK_NS}}}{name}")
        child.text = text
        return child

    root = ET.Element(f"{{{TASK_NS}}}Task", {"version": "1.4"})
    registration = element(root, "RegistrationInfo")
    element(registration, "Description", "SWU Check-in desktop: user-selected scheduled mode")
    triggers = element(root, "Triggers")
    current = (now or datetime.now(UTC)).astimezone(timezone(timedelta(hours=8)))
    for minute in (15, 45):
        boundary = current.replace(hour=21, minute=minute, second=0, microsecond=0)
        if boundary <= current:
            boundary += timedelta(days=1)
        trigger = element(triggers, "CalendarTrigger")
        element(trigger, "StartBoundary", boundary.isoformat())
        element(trigger, "Enabled", "true")
        element(element(trigger, "ScheduleByDay"), "DaysInterval", "1")
    principal = element(element(root, "Principals"), "Principal")
    principal.set("id", "Author")
    element(principal, "UserId", sid)
    element(principal, "LogonType", "InteractiveToken")
    element(principal, "RunLevel", "LeastPrivilege")
    settings = element(root, "Settings")
    for name, value in (
        ("MultipleInstancesPolicy", "IgnoreNew"),
        ("DisallowStartIfOnBatteries", "false"),
        ("StopIfGoingOnBatteries", "false"),
        ("StartWhenAvailable", "false"),
        ("RunOnlyIfNetworkAvailable", "true"),
        ("ExecutionTimeLimit", "PT15M"),
        ("Enabled", "true"),
    ):
        element(settings, name, value)
    actions = element(root, "Actions")
    actions.set("Context", "Author")
    execution = element(actions, "Exec")
    element(execution, "Command", executable)
    element(execution, "Arguments", "--scheduled")
    element(execution, "WorkingDirectory", str(PureWindowsPath(executable).parent))
    return ET.tostring(root, encoding="utf-16", xml_declaration=True)


class DesktopBackend:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else app_root()
        self.last_warning = ""

    @property
    def credential_path(self) -> Path:
        return self.root / "desktop-credentials.dpapi"

    @property
    def config_path(self) -> Path:
        return self.root / "desktop-config.json"

    def save_credentials(self, username: str, password: str) -> None:
        if not username.strip() or not password:
            raise DesktopError(DesktopErrorCode.CREDENTIALS_EMPTY)
        if self._read_config().get("enabled") is True:
            raise DesktopError(DesktopErrorCode.SCHEDULE_ACTIVE)
        data = json.dumps({"schema_version": 1, "username": username.strip(), "password": password}).encode("utf-8")
        try:
            _atomic_write(self.credential_path, WindowsDpapiProtector().protect(data))
        except Exception:
            raise DesktopError(DesktopErrorCode.CREDENTIAL_SAVE_FAILED) from None

    def load_credentials(self) -> tuple[str, str] | None:
        try:
            data = self.credential_path.read_bytes()
        except FileNotFoundError:
            return None
        try:
            payload = json.loads(WindowsDpapiProtector().unprotect(data))
            if not isinstance(payload, dict) or (
                type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1
            ):
                raise ValueError
            username, password = payload.get("username"), payload.get("password")
            if not isinstance(username, str) or not username or not isinstance(password, str) or not password:
                raise ValueError
            return username, password
        except Exception:
            raise DesktopError(DesktopErrorCode.CREDENTIAL_LOAD_FAILED) from None

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

    def _system_command(self, executable: str, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        if sys.platform != "win32":
            raise DesktopError(DesktopErrorCode.TASK_WINDOWS_REQUIRED)
        root = os.environ.get("SystemRoot", r"C:\Windows")
        return subprocess.run(
            [str(Path(root) / "System32" / executable), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _task_exists(self, name: str) -> bool:
        # schtasks exit 1 conflates missing tasks, access denial and service
        # failures. Query the exact root task via COM instead; only GetTask's
        # explicit ERROR_FILE_NOT_FOUND is absence. .NET may map that HRESULT
        # to FileNotFoundException rather than COMException. Never parse text.
        literal = name.replace("'", "''")
        script = (
            "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; "
            "try { $s=New-Object -ComObject Schedule.Service; $s.Connect(); "
            "$f=$s.GetFolder('\\') } catch { exit 3 }; "
            "try { $null=$f.GetTask('" + literal + "') } catch { "
            "$e=$_.Exception; while ($null -ne $e) { "
            "if ($e.HResult -eq -2147024894) { "
            "[Console]::Out.Write('SWU_TASK_ABSENT'); exit 0 }; $e=$e.InnerException }; exit 3 }; "
            "[Console]::Out.Write('SWU_TASK_EXISTS'); exit 0"
        )
        try:
            result = self._system_command(
                r"WindowsPowerShell\v1.0\powershell.exe",
                [
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-EncodedCommand",
                    base64.b64encode(script.encode("utf-16-le")).decode("ascii"),
                ],
            )
            if result.returncode == 0 and not result.stderr.strip():
                if result.stdout.strip() == "SWU_TASK_EXISTS":
                    return True
                if result.stdout.strip() == "SWU_TASK_ABSENT":
                    return False
        except Exception:
            pass
        raise DesktopError(DesktopErrorCode.TASK_QUERY_FAILED) from None

    def _read_config(self) -> dict:
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except Exception:
            raise DesktopError(DesktopErrorCode.CONFIG_DAMAGED) from None
        if not isinstance(payload, dict) or (
            type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1
        ):
            raise DesktopError(DesktopErrorCode.CONFIG_INVALID)
        return payload

    def schedule_mode(self) -> str | None:
        if not self._task_exists(TASK_NAME):
            return None
        config = self._read_config()
        mode = config.get("mode")
        if config.get("enabled") is not True:
            return None
        if not isinstance(mode, str) or mode not in {"probe", "checkin"}:
            raise DesktopError(DesktopErrorCode.SCHEDULE_MODE_INVALID)
        return mode

    def schedule_enabled(self) -> bool:
        return self.schedule_mode() is not None

    def set_schedule(self, enabled: bool, mode: str = "probe") -> None:
        if not enabled:
            if self._task_exists(TASK_NAME):
                result = self._system_command("schtasks.exe", ["/Delete", "/TN", TASK_NAME, "/F"])
                if result.returncode != 0:
                    raise DesktopError(DesktopErrorCode.TASK_DISABLE_FAILED)
            _atomic_write(self.config_path, b'{"schema_version":1,"enabled":false}')
            return
        if not isinstance(mode, str) or mode not in {"probe", "checkin"}:
            raise DesktopError(DesktopErrorCode.MODE_REQUIRED)
        if not getattr(sys, "frozen", False):
            raise DesktopError(DesktopErrorCode.FROZEN_REQUIRED)
        credentials = self.load_credentials()
        if credentials is None:
            raise DesktopError(DesktopErrorCode.SAVED_CREDENTIALS_REQUIRED)
        self._task_exists(TASK_NAME)  # Unknown current state must not permit overwrite.
        if self._task_exists(LEGACY_TASK_NAME):
            raise DesktopError(DesktopErrorCode.LEGACY_TASK_EXISTS)
        if not self.diagnose(*credentials):
            raise DesktopError(DesktopErrorCode.DIAGNOSIS_FAILED)
        identity = self._system_command("whoami.exe", ["/user", "/fo", "csv", "/nh"])
        try:
            sid = next(csv.reader(io.StringIO(identity.stdout)))[1]
            if identity.returncode or not sid.startswith("S-1-"):
                raise ValueError
        except (IndexError, StopIteration, ValueError):
            raise DesktopError(DesktopErrorCode.USER_IDENTITY_FAILED) from None
        previous = self.config_path.read_bytes() if self.config_path.exists() else None
        payload = json.dumps({"schema_version": 1, "enabled": True, "mode": mode}).encode("utf-8")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, filename = tempfile.mkstemp(suffix=".xml", prefix=".task-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(task_xml(sys.executable, sid))
            _atomic_write(self.config_path, payload)
            result = self._system_command("schtasks.exe", ["/Create", "/TN", TASK_NAME, "/XML", filename, "/F"])
            if result.returncode != 0 or not self._task_exists(TASK_NAME):
                raise DesktopError(DesktopErrorCode.TASK_CREATE_FAILED)
        except Exception:
            if previous is not None:
                _atomic_write(self.config_path, previous)
            elif self.config_path.exists():
                self.config_path.unlink()
            raise
        finally:
            if os.path.exists(filename):
                os.unlink(filename)

    def run_scheduled(self) -> int:
        try:
            config = self._read_config()
            if (
                config.get("enabled") is not True
                or not isinstance(config.get("mode"), str)
                or config.get("mode") not in {"probe", "checkin"}
            ):
                return 1
            credentials = self.load_credentials()
            if credentials is None:
                return 1
            mode = config["mode"]
            result = self.probe(*credentials) if mode == "probe" else self.check_in(*credentials)
            record = {"at": datetime.now(UTC).isoformat(), "result": json.loads(result.to_json())}
            try:
                _atomic_write(self.root / "desktop-last-run.json", json.dumps(record).encode("utf-8"))
            except OSError:
                self.last_warning = "定时结果未能保存，请检查本地磁盘。"
            allowed = SUCCESSFUL_PROBE_STATUSES if mode == "probe" else SUCCESSFUL_CHECKIN_STATUSES
            return 0 if CheckinStatus(result.code) in allowed else 1
        except Exception:
            # Never place decrypted credentials, API bodies or arbitrary errors in logs.
            return 1

    def self_test(self) -> int:
        """Exercise runtime assets with synthetic inputs only; no saved credentials/network."""
        import ssl
        import tkinter

        import certifi
        import ddddocr
        from PIL import Image

        from .time_utils import today_shanghai

        ssl.create_default_context(cafile=certifi.where())
        tkinter.Tcl().eval("info patchlevel")
        if sys.platform == "win32":
            window = tkinter.Tk()
            window.withdraw()
            window.update_idletasks()
            window.destroy()
        today_shanghai()
        image = Image.new("RGB", (100, 40), "white")
        ddddocr.DdddOcr(show_ad=False, use_gpu=False).classification(image)
        if sys.platform == "win32":
            protector = WindowsDpapiProtector()
            if protector.unprotect(protector.protect(b"synthetic-self-test")) != b"synthetic-self-test":
                return 1
            # Read-only integration check: a fresh random task name must be
            # positively absent, not an access/service/query failure. No task
            # is registered, modified, executed or removed by this check.
            if self._task_exists("SWUCheckin-SelfTest-" + uuid4().hex):
                return 1
        with tempfile.TemporaryDirectory(prefix="swu-offline-test-") as directory:
            with RuntimeLock(Path(directory) / "test.lock"):
                pass
        return 0
