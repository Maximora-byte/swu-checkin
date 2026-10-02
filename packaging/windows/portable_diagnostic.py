"""Synthetic, source-only stage diagnostics after a failed frozen CI self-test.

Never a replacement for the portable executable acceptance gate. No school
requests, saved account reads, real task registration or exception text output.
"""

import base64
import ctypes
import json
import os
import re
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


STAGE_DETAILS: dict[str, object] = {}


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


def classify_command(result) -> dict[str, object]:
    marker = result.stdout.strip()
    known = {"SWU_TASK_EXISTS", "SWU_TASK_ABSENT", "SWU_RESTRICTED_PS_OK"}
    phases = [
        line
        for line in result.stdout.splitlines()
        if re.fullmatch(r"(?:IDENTITY|COM|CONNECT|ROOT|TASK)_(?:OK|ABSENT|FAIL)(?::-?\d+)?", line)
    ]
    return {
        "returncode": int(result.returncode),
        "stdout_category": marker if marker in known else "OTHER" if marker else "EMPTY",
        "stderr_present": bool(result.stderr.strip()),
        "progress_xml": result.stderr.startswith("#< CLIXML"),
        "phases": phases[:12],
    }


def absent_task() -> None:
    from swu_checkin.desktop_backend import DesktopBackend

    details = {}
    STAGE_DETAILS["absent-task"] = details
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    advapi.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    token = ctypes.c_void_p()
    opened = bool(advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)))
    details["own_token_read"] = {"success": opened, "winerror": 0 if opened else ctypes.get_last_error()}
    if opened:
        kernel.CloseHandle(token)
    backend = DesktopBackend()
    original = backend._system_command

    def invoke(script: str):
        return original(
            r"WindowsPowerShell\v1.0\powershell.exe",
            [
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                base64.b64encode(script.encode("utf-16-le")).decode("ascii"),
            ],
        )

    def record_probe(name: str, script: str) -> None:
        try:
            details[name] = classify_command(invoke(script))
        except Exception as error:
            kind = type(error).__name__
            details[name] = {"exception_type": kind if kind in SAFE_ERROR_TYPES else "OTHER"}
            if isinstance(error, OSError):
                details[name]["winerror"] = getattr(error, "winerror", None)

    record_probe("powershell", "[Console]::Out.Write('SWU_RESTRICTED_PS_OK'); exit 0")
    # Fixed strings and HRESULTs only. No identity value, username, task output,
    # arbitrary exception text, or school endpoint is ever written to the report.
    script = r"""
$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
try { $null=[Security.Principal.WindowsIdentity]::GetCurrent(); 'IDENTITY_OK' }
catch { 'IDENTITY_FAIL:' + $_.Exception.HResult }
try { $s=New-Object -ComObject Schedule.Service; 'COM_OK' }
catch { 'COM_FAIL:' + $_.Exception.HResult; exit 3 }
try { $s.Connect(); 'CONNECT_OK' }
catch { 'CONNECT_FAIL:' + $_.Exception.HResult; exit 3 }
try { $f=$s.GetFolder('\'); 'ROOT_OK' }
catch { 'ROOT_FAIL:' + $_.Exception.HResult; exit 3 }
try { $null=$f.GetTask('SWUCheckin-SelfTest-Diagnostic-' + [Guid]::NewGuid().ToString('N')); 'TASK_OK' }
catch {
    $e=$_.Exception
    while ($null -ne $e) {
        if ($e.HResult -eq -2147024894) { 'TASK_ABSENT'; exit 0 }
        $last=$e.HResult; $e=$e.InnerException
    }
    'TASK_FAIL:' + $last; exit 3
}
"""
    record_probe("scheduler_phases", script)

    def checked(executable, arguments):
        try:
            result = original(executable, arguments)
        except Exception as error:
            kind = type(error).__name__
            details["production_query"] = {"exception_type": kind if kind in SAFE_ERROR_TYPES else "OTHER"}
            if isinstance(error, OSError):
                details["production_query"]["winerror"] = getattr(error, "winerror", None)
            raise
        details["production_query"] = classify_command(result)
        return result

    backend._system_command = checked
    assert backend._task_exists("SWUCheckin-SelfTest-" + uuid4().hex) is False


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
    STAGE_DETAILS.clear()
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
        if name in STAGE_DETAILS:
            results[-1]["details"] = STAGE_DETAILS[name]
        # Flush after every stage so a timeout still leaves safe partial evidence.
        report.write_text(json.dumps(results, ensure_ascii=True) + "\n", encoding="ascii")
    return int(any(item["result"] != "PASS" for item in results))


if __name__ == "__main__":
    raise SystemExit(run(Path(sys.argv[1])))
