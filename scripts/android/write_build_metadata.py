"""Record the reviewed clean source in the signed preview, without key material."""

import argparse
import hashlib
import json
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def metadata() -> dict:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()

    if git("status", "--porcelain"):
        raise ValueError("signed distribution preview requires a clean reviewed source checkout")
    return {
        "schema_version": 1,
        "source_commit": git("rev-parse", "HEAD"),
        "source_tree": git("rev-parse", "HEAD^{tree}"),
        "source_dirty": False,
        "project_version": tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"],
        "uv_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        "android_version": "0.1.2-preview",
        "android_version_code": 4,
        "preview": True,
        "signature": "persistent local protected RSA-4096 preview key",
        "verification_scope": "synthetic acceptance; no school-account authentication or submission",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = metadata()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Clean source recorded for signed preview")
