"""Credential-free packaging gate. Never contacts SWU or invokes check-in."""

from __future__ import annotations

import importlib
import json
import os
import ssl
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def run(private_directory: str, with_https: bool = False) -> str:
    """Return fixed, non-sensitive checks; paths and exception text never escape."""
    checks: dict[str, bool | str] = {"python_313": sys.version_info[:2] == (3, 13)}
    try:
        importlib.import_module("swu_checkin.service")
        importlib.import_module("swu_checkin.formal_execution")
        checks["core_import"] = True
        checks["ocr_not_loaded"] = not any(
            name in sys.modules for name in ("ddddocr", "PIL", "onnxruntime", "tkinter", "swu_checkin.desktop_backend")
        )
        shanghai = ZoneInfo("Asia/Shanghai")
        checks["timezone"] = datetime(2026, 1, 1, tzinfo=shanghai).utcoffset().total_seconds() == 28800
        root = Path(private_directory)
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise ValueError("invalid private directory")
        probe = root / "feasibility"
        probe.mkdir(mode=0o700, exist_ok=True)
        if probe.is_symlink():
            raise ValueError("invalid probe directory")
        descriptor, temporary_name = tempfile.mkstemp(prefix="write-test-", dir=probe)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w") as handle:
                handle.write("synthetic test only")
            checks["private_storage"] = temporary.read_text() == "synthetic test only"
        finally:
            temporary.unlink(missing_ok=True)
        from swu_checkin.formal_execution import execute_formal_checkin_with_lock
        from swu_checkin.runtime_lock import RuntimeLock

        previous_lock = os.environ.get("SWUDK_LOCK_FILE")
        lock_path = probe / "formal.lock"
        os.environ["SWUDK_LOCK_FILE"] = str(lock_path)
        try:

            def contend() -> bool:
                contender = RuntimeLock()
                acquired = contender.acquire()
                contender.release()
                return not acquired

            checks["formal_lock_contention"] = execute_formal_checkin_with_lock(contend)
            with RuntimeLock():
                checks["formal_lock_released"] = True
        finally:
            if previous_lock is None:
                os.environ.pop("SWUDK_LOCK_FILE", None)
            else:
                os.environ["SWUDK_LOCK_FILE"] = previous_lock
        checks["tls_verification"] = ssl.create_default_context().verify_mode == ssl.CERT_REQUIRED
        checks["https"] = "not_run"
        if with_https:
            import requests

            # Public, non-account endpoint. No redirects, cookies or user data.
            with requests.Session() as session:
                session.trust_env = False
                with session.get(
                    "https://www.python.org/robots.txt", timeout=15, allow_redirects=False, stream=True
                ) as response:
                    checks["https"] = response.status_code == 200
    except Exception:
        checks["unexpected_failure"] = True
    checks["passed"] = (
        not checks.get("unexpected_failure", False)
        and all(value is True for key, value in checks.items() if key != "https")
        and (not with_https or checks.get("https") is True)
    )
    return json.dumps(checks, ensure_ascii=False, sort_keys=True)
