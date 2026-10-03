"""Collect native macOS preview provenance before signing application resources."""

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from license_inventory import collect, verify  # noqa: E402


def metadata(root: Path, output: Path) -> None:
    # Do not carry removed dependencies' notices into a rebuilt preview.
    if output.resolve() != root / "build/macos/metadata":
        raise RuntimeError("Native metadata output must remain inside this checkout's build/macos/metadata")
    if output.exists():
        shutil.rmtree(output)
    collect(root, output)
    verify(output)

    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()

    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if importlib.metadata.version("swu-checkin") != version:
        raise RuntimeError("Installed application metadata does not match source version")
    commit = git("rev-parse", "HEAD")
    info = {
        "application_version": version,
        "developer": "MatchAll",
        "source_commit": commit,
        "commit": commit,
        "source_dirty": bool(git("status", "--porcelain")),
        "source_tree": git("rev-parse", "HEAD^{tree}"),
        "uv_lock_sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
        "macos": platform.mac_ver()[0],
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "dependencies": {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()},
        "minimum_declared_macos": "15.0",
        "preview": True,
        "signature": "ad-hoc; no Developer ID",
        "notarized": False,
        "keychain_ci_smoke_passed": os.getenv("SWU_KEYCHAIN_SMOKE_PASSED") == "true",
        # The build may only be uploaded after every required check succeeds.
        "checks": [
            "frozen Tk GUI with busy/idle native Quit guard",
            "frozen OCR inference",
            "TLS trust assets",
            "runtime lock",
            "scheduled mode rejected",
            "bundled original license hashes",
        ],
        "not_verified": [
            "physical Mac clean-user acceptance",
            "Gatekeeper distribution approval",
            "school authentication or submission",
            "macOS versions other than build runner",
        ],
    }
    (output / "BUILD-INFO.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if sys.platform != "darwin":
        raise SystemExit("Native macOS provenance requires macOS")
    metadata(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
