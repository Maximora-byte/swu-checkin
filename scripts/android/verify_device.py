"""Run synthetic acceptance on one explicitly selected Android device."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

if __package__:
    from .verify_apk import inspect_apk
    from .verify_instrumentation import verify as verify_tests
    from .verify_ui import APP_ID
    from .verify_ui import verify as verify_ui
else:
    from verify_apk import inspect_apk
    from verify_instrumentation import verify as verify_tests
    from verify_ui import APP_ID
    from verify_ui import verify as verify_ui


def check_device(metadata: dict, *, api: int, abi: str, page_size: int) -> None:
    """Refuse a different device instead of silently testing the wrong matrix row."""
    expected = {"api": api, "abi": abi, "page_size": page_size}
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise ValueError(f"device {key}: expected {value}, got {metadata.get(key)}")


def read_page_size(getconf: str, smaps: str = "") -> int:
    """Android 7 lacks getconf: read the shell process's actual kernel page size."""
    if getconf.strip().isdecimal() and int(getconf.strip()) > 0:
        return int(getconf.strip())
    page = re.search(r"^KernelPageSize:\s+(\d+)\s+kB\s*$", smaps, re.MULTILINE)
    if page and int(page[1]) > 0:
        return int(page[1]) * 1024
    raise ValueError("device did not report a valid kernel page size")


def check_disposable_account(marker: str) -> None:
    """Never uninstall or clear an existing account-bearing application."""
    if marker.strip() != "NO_SAVED_ACCOUNT":
        raise ValueError("acceptance refuses to clear saved accounts; use a disposable installation")


def accept(args: argparse.Namespace) -> None:
    evidence = args.evidence_dir.resolve()
    # A previous successful result must never survive a failed re-run.
    evidence.mkdir(parents=True, exist_ok=False)
    base = [str(args.adb), "-s", args.serial]

    def adb(*command: str, timeout: int = 90, check: bool = True):
        return subprocess.run(
            [*base, *command], capture_output=True, encoding="utf-8", errors="replace", timeout=timeout, check=check
        )

    page = adb("shell", "getconf", "PAGE_SIZE", check=False)
    smaps = adb("shell", "cat", "/proc/self/smaps").stdout if page.returncode else ""
    metadata = {
        "api": int(adb("shell", "getprop", "ro.build.version.sdk").stdout.strip()),
        "abi": adb("shell", "getprop", "ro.product.cpu.abi").stdout.strip(),
        "page_size": read_page_size(page.stdout if page.returncode == 0 else "", smaps),
        "emulator": adb("shell", "getprop", "ro.kernel.qemu").stdout.strip() == "1",
    }
    check_device(metadata, api=args.api, abi=args.abi, page_size=args.page_size)
    if args.system_logs and not metadata["emulator"]:
        raise ValueError("full system logs are limited to disposable emulators")
    (evidence / "device.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    inventory = inspect_apk(args.apk)
    (evidence / "apk-inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    checksums = {}
    for path in (args.apk, args.test_apk):
        with path.open("rb") as handle:
            checksums[path.name] = hashlib.file_digest(handle, "sha256").hexdigest()
    (evidence / "apk-checksums.json").write_text(json.dumps(checksums, indent=2), encoding="utf-8")
    results = {}
    try:
        for package_id in (APP_ID, f"{APP_ID}.test"):
            # Android's pm path exits 1 when the package is absent on a fresh AVD.
            package = adb("shell", "pm", "path", package_id, check=False)
            if package.returncode not in (0, 1):
                package.check_returncode()
            installed = package.stdout.strip()
            if package.returncode == 1 and (installed or package.stderr.strip()):
                package.check_returncode()
            if installed:
                if package_id == APP_ID:
                    marker = adb(
                        "shell",
                        f"run-as {APP_ID} sh -c 'if [ -e no_backup/account.enc ] || "
                        "[ -e no_backup/account.enc.bak ]; then echo SAVED_ACCOUNT; "
                        "else echo NO_SAVED_ACCOUNT; fi'",
                    )
                    check_disposable_account(marker.stdout)
                adb("uninstall", package_id)
        adb("install", str(args.apk.resolve()), timeout=180)
        adb("install", str(args.test_apk.resolve()), timeout=180)
        # Clear only this synthetic application, never device-wide data.
        adb("shell", "pm", "clear", APP_ID)
        for stage in ("fresh-install", "replacement-install", "cleared-data"):
            if stage == "replacement-install":
                adb("install", "-r", str(args.apk.resolve()), timeout=180)
            elif stage == "cleared-data":
                adb("shell", "pm", "clear", APP_ID)
            # Real devices may restrict ActivityScenario launches from a
            # background task. Bring this credential-free app to the foreground
            # before instrumentation; the user still needs to keep it unlocked.
            adb("shell", "am", "start", "-W", "-n", f"{APP_ID}/io.github.maximorabyte.swucheckin.MainActivity")
            run = adb(
                "shell",
                "am",
                "instrument",
                "-w",
                "-r",
                f"{APP_ID}.test/androidx.test.runner.AndroidJUnitRunner",
                timeout=600,
                check=False,
            )
            report = run.stdout + run.stderr
            (evidence / f"instrumentation-{stage}.txt").write_text(report, encoding="utf-8")
            results[stage] = verify_tests(report)
        adb("shell", "am", "start", "-W", "-n", f"{APP_ID}/io.github.maximorabyte.swucheckin.MainActivity")
        for attempt in range(30):
            dump = adb("shell", "uiautomator", "dump", "/data/local/tmp/swu-feasibility-ui.xml", check=False)
            if dump.returncode == 0:
                xml = adb("shell", "cat", "/data/local/tmp/swu-feasibility-ui.xml").stdout
                (evidence / "feasibility-ui.xml").write_text(xml, encoding="utf-8")
                try:
                    verify_ui(xml)
                    break
                except ValueError:
                    pass
            if attempt == 29:
                raise RuntimeError("feasibility UI readiness timed out")
            time.sleep(1)
        screenshot = subprocess.run([*base, "exec-out", "screencap", "-p"], capture_output=True, timeout=30, check=True)
        (evidence / "feasibility-screen.png").write_bytes(screenshot.stdout)
        (evidence / "result.json").write_text(
            json.dumps({"passed": True, "tests": results}, indent=2), encoding="utf-8"
        )
    finally:
        if args.system_logs:
            run = adb("logcat", "-d", "-b", "all", "-v", "threadtime", timeout=30, check=False)
            (evidence / "system-logcat.txt").write_text(run.stdout + run.stderr, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--adb", type=Path, required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--test-apk", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--api", type=int, required=True)
    parser.add_argument("--abi", choices=("x86_64", "arm64-v8a"), required=True)
    parser.add_argument("--page-size", type=int, choices=(4096, 16384), required=True)
    parser.add_argument("--system-logs", action="store_true")
    accept(parser.parse_args())
    print("Android device acceptance passed")
