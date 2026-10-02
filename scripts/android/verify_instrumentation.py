"""Android's am instrument may exit zero on test failure: validate its output."""

import argparse
import re
from pathlib import Path

EXPECTED_TESTS = {
    ("io.github.maximorabyte.swucheckin.RuntimeFeasibilityTest", "embeddedPythonCoreStorageTimezoneAndLock"),
    ("io.github.maximorabyte.swucheckin.RuntimeFeasibilityTest", "verifiedPublicHttpsFromEmbeddedPython"),
    ("io.github.maximorabyte.swucheckin.CrossProcessLockTest", "lockIsSharedAndProcessDeathReleasesIt"),
    ("io.github.maximorabyte.swucheckin.DiagnosticsUiTest", "diagnosticButtonsAndRecreation"),
    ("io.github.maximorabyte.swucheckin.AccountSecurityTest", "encryptionTamperingAndMissingKeyFailClosed"),
    ("io.github.maximorabyte.swucheckin.AccountSecurityTest", "captchaCancellationTimeoutAndStaleAnswer"),
    ("io.github.maximorabyte.swucheckin.CheckinUiTest", "manualLoginQueryConfirmationAndCancellation"),
}

# Release APKs deliberately omit the debug-only private lock-probe process.
# Its seven-test debug gate remains mandatory in CI; the exact production APK
# gets its own six-test gate, including synthetic auth/UI and secure storage.
RELEASE_EXPECTED_TESTS = EXPECTED_TESTS - {
    ("io.github.maximorabyte.swucheckin.CrossProcessLockTest", "lockIsSharedAndProcessDeathReleasesIt"),
}


def verify(text: str, *, expected_tests: set[tuple[str, str]] = EXPECTED_TESTS) -> int:
    match = re.findall(r"^OK \((\d+) tests?\)\s*$", text, re.MULTILINE)
    if match != [str(len(expected_tests))]:
        raise ValueError("expected all feasibility instrumentation tests to pass")
    if re.findall(r"^INSTRUMENTATION_CODE: (-?\d+)\s*$", text, re.MULTILINE) != ["-1"]:
        raise ValueError("missing or unsuccessful instrumentation termination")
    if any(
        marker in text
        for marker in (
            "FAILURES!!!",
            "INSTRUMENTATION_FAILED",
            "INSTRUMENTATION_ABORTED",
            "Process crashed",
            "shortMsg=",
        )
    ):
        raise ValueError("instrumentation reported a failure")
    completed = set()
    current: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("INSTRUMENTATION_STATUS: "):
            field, _, value = line.removeprefix("INSTRUMENTATION_STATUS: ").partition("=")
            current[field] = value
        elif line.startswith("INSTRUMENTATION_STATUS_CODE: "):
            code = line.removeprefix("INSTRUMENTATION_STATUS_CODE: ").strip()
            if code == "0":
                completed.add((current.get("class"), current.get("test")))
            elif code != "1":
                raise ValueError("test failed or was skipped")
            current = {}
    if completed != expected_tests:
        raise ValueError("expected test identities were not all successful")
    return len(completed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    print(f"Passed instrumentation tests: {verify(args.report.read_text())}")
