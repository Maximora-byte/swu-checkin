"""Test a signed release on a fresh disposable installation; refuse existing app data."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

if __package__:
    from .verify_device import check_device, read_page_size
    from .verify_instrumentation import RELEASE_EXPECTED_TESTS
    from .verify_instrumentation import verify as verify_tests
    from .verify_signed_apk import APP_ID, certificate_digest
    from .verify_signed_apk import verify as verify_apk
    from .verify_ui import verify as verify_ui
else:
    from verify_device import check_device, read_page_size
    from verify_instrumentation import RELEASE_EXPECTED_TESTS
    from verify_instrumentation import verify as verify_tests
    from verify_signed_apk import APP_ID, certificate_digest
    from verify_signed_apk import verify as verify_apk
    from verify_ui import verify as verify_ui


def require_absent(text: str, returncode: int) -> None:
    if text.strip() or returncode not in (0, 1):
        raise ValueError("release acceptance requires an absent package; existing app data will not be touched")


def accept(args: argparse.Namespace) -> None:
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    base = [str(args.adb), "-s", args.serial]

    def adb(*command: str, timeout: int = 90, check: bool = True):
        return subprocess.run(
            [*base, *command], capture_output=True, encoding="utf-8", errors="replace", timeout=timeout, check=check
        )

    page = adb("shell", "getconf", "PAGE_SIZE", check=False)
    metadata = {
        "api": int(adb("shell", "getprop", "ro.build.version.sdk").stdout.strip()),
        "abi": adb("shell", "getprop", "ro.product.cpu.abi").stdout.strip(),
        "page_size": read_page_size(
            page.stdout if page.returncode == 0 else "",
            adb("shell", "cat", "/proc/self/smaps").stdout if page.returncode else "",
        ),
        "emulator": adb("shell", "getprop", "ro.kernel.qemu").stdout.strip() == "1",
    }
    check_device(metadata, api=args.api, abi=args.abi, page_size=args.page_size)
    if not metadata["emulator"]:
        raise ValueError("this release acceptance is restricted to disposable emulators")
    for package in (APP_ID, f"{APP_ID}.test"):
        installed = adb("shell", "pm", "path", package, check=False)
        require_absent(installed.stdout + installed.stderr, installed.returncode)
        retained = adb("shell", "pm", "list", "packages", "-u", package)
        if f"package:{package}" in retained.stdout.splitlines():
            raise ValueError("release acceptance refuses existing or retained package data")
    # Check both files before making the first installation or clearing any data.
    inventory = verify_apk(args)
    signature = subprocess.run(
        [
            str(args.java),
            "-jar",
            str(args.sdk / "build-tools/35.0.0/lib/apksigner.jar"),
            "verify",
            "--print-certs",
            str(args.test_apk),
        ],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    if certificate_digest(signature.stdout) != inventory["certificate_sha256"]:
        raise ValueError("test APK signing certificate differs from the production APK")
    (evidence / "device.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (evidence / "apk-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    checksums = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (args.apk, args.test_apk)}
    (evidence / "apk-checksums.json").write_text(json.dumps(checksums, indent=2) + "\n", encoding="utf-8")
    results = {}

    def instrument(label: str, expected: set[tuple[str, str]]) -> None:
        classes = ",".join(sorted({klass for klass, _ in expected}))
        if len(expected) == 1:
            klass, method = next(iter(expected))
            classes = f"{klass}#{method}"
        adb("shell", "am", "start", "-W", "-n", f"{APP_ID}/io.github.maximorabyte.swucheckin.MainActivity")
        result = adb(
            "shell",
            "am",
            "instrument",
            "-w",
            "-r",
            "-e",
            "class",
            classes,
            f"{APP_ID}.test/androidx.test.runner.AndroidJUnitRunner",
            timeout=600,
            check=False,
        )
        report = result.stdout + result.stderr
        (evidence / f"instrumentation-{label}.txt").write_text(report, encoding="utf-8")
        result.check_returncode()
        results[label] = verify_tests(report, expected_tests=expected)
        print(f"{label}: {results[label]} tests passed", flush=True)

    try:
        adb("install", str(args.apk.resolve()), timeout=180)
        adb("install", str(args.test_apk.resolve()), timeout=180)
        instrument("fresh-install", RELEASE_EXPECTED_TESTS)
        upgrade_class = "io.github.maximorabyte.swucheckin.ReleaseUpgradeTest"
        instrument("upgrade-account-seed", {(upgrade_class, "storeSyntheticUpgradeAccount")})
        adb("install", "-r", str(args.apk.resolve()), timeout=180)
        instrument("upgrade-account-retained", {(upgrade_class, "verifySyntheticUpgradeAccount")})
        instrument("replacement-install", RELEASE_EXPECTED_TESTS)
        # Only the synthetic app created by this invocation is cleared.
        if adb("shell", "pm", "clear", APP_ID).stdout.strip() != "Success":
            raise ValueError("synthetic app data could not be cleared")
        instrument("cleared-data", RELEASE_EXPECTED_TESTS)
        adb("shell", "am", "start", "-W", "-n", f"{APP_ID}/io.github.maximorabyte.swucheckin.MainActivity")
        for attempt in range(30):
            dump = adb("shell", "uiautomator", "dump", "/data/local/tmp/swu-release-ui.xml", check=False)
            if dump.returncode == 0:
                xml = adb("shell", "cat", "/data/local/tmp/swu-release-ui.xml").stdout
                (evidence / "release-ui.xml").write_text(xml, encoding="utf-8")
                try:
                    verify_ui(xml, app_id=APP_ID)
                    break
                except ValueError:
                    pass
            if attempt == 29:
                raise RuntimeError("release diagnostic UI readiness timed out")
            time.sleep(1)
        screenshot = subprocess.run([*base, "exec-out", "screencap", "-p"], capture_output=True, timeout=30, check=True)
        (evidence / "release-screen.png").write_bytes(screenshot.stdout)
        (evidence / "result.json").write_text(
            json.dumps(
                {"passed": True, "tests": results, "scope": "synthetic production APK; same-version reinstall"},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    finally:
        logs = adb("logcat", "-d", "-b", "all", "-v", "threadtime", timeout=30, check=False)
        (evidence / "system-logcat.txt").write_text(logs.stdout + logs.stderr, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for option in ("adb", "apk", "test-apk", "sdk", "java", "certificate", "evidence-dir"):
        parser.add_argument(f"--{option}", type=Path, required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--api", type=int, required=True)
    parser.add_argument("--abi", choices=("x86_64", "arm64-v8a"), required=True)
    parser.add_argument("--page-size", type=int, choices=(4096, 16384), required=True)
    accept(parser.parse_args())
    print("Signed Android release acceptance passed")
