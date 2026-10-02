"""Synthetic, source-only stage diagnostics after a failed frozen CI self-test.

Never a replacement for the portable executable acceptance gate. No school
requests, saved account reads, real task registration or exception text output.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

SAFE_ERROR_TYPES = {
    "AssertionError",
    "DesktopError",
    "FileNotFoundError",
    "ImportError",
    "ModuleNotFoundError",
    "OSError",
    "PermissionError",
    "RuntimeError",
    "TclError",
    "TokenStoreError",
    "ValueError",
}


def tls() -> None:
    import ssl

    import certifi

    ssl.create_default_context(cafile=certifi.where())


def tcl() -> None:
    import tkinter

    tkinter.Tcl().eval("info patchlevel")


def tk_window() -> None:
    import tkinter

    window = tkinter.Tk()
    try:
        window.withdraw()
        window.update_idletasks()
    finally:
        window.destroy()


def timezone() -> None:
    from swu_checkin.time_utils import today_shanghai

    today_shanghai()


def ocr() -> None:
    import ddddocr
    from PIL import Image

    ddddocr.DdddOcr(show_ad=False, use_gpu=False).classification(Image.new("RGB", (100, 40), "white"))


def dpapi() -> None:
    from swu_checkin.token_store import WindowsDpapiProtector

    protector = WindowsDpapiProtector()
    value = b"synthetic-self-test"
    assert protector.unprotect(protector.protect(value)) == value


def absent_task() -> None:
    from swu_checkin.desktop_backend import DesktopBackend

    assert DesktopBackend()._task_exists("SWUCheckin-SelfTest-" + uuid4().hex) is False


def temporary_lock() -> None:
    from swu_checkin.runtime_lock import RuntimeLock

    with tempfile.TemporaryDirectory(prefix="swu-offline-diagnostic-") as directory:
        with RuntimeLock(Path(directory) / "test.lock"):
            pass


def run(report: Path) -> int:
    if not (
        sys.platform == "win32"
        and os.getenv("GITHUB_ACTIONS") == "true"
        and os.getenv("RUNNER_ENVIRONMENT") == "github-hosted"
        and os.getenv("ImageOS") == "win22"
    ):
        raise RuntimeError("Diagnostic requires disposable GitHub-hosted windows-2022")
    results = []
    for name, operation in (
        ("tls", tls),
        ("tcl", tcl),
        ("tk-window", tk_window),
        ("timezone", timezone),
        ("ocr", ocr),
        ("dpapi", dpapi),
        ("absent-task", absent_task),
        ("temporary-lock", temporary_lock),
    ):
        try:
            operation()
        except Exception as error:
            kind = type(error).__name__
            results.append({"stage": name, "result": "FAIL", "type": kind if kind in SAFE_ERROR_TYPES else "OTHER"})
        else:
            results.append({"stage": name, "result": "PASS"})
        # Flush after every stage so a timeout still leaves safe partial evidence.
        report.write_text(json.dumps(results, ensure_ascii=True) + "\n", encoding="ascii")
    return int(any(item["result"] != "PASS" for item in results))


if __name__ == "__main__":
    raise SystemExit(run(Path(sys.argv[1])))
