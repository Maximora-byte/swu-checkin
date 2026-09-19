from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import swu_checkin

ROOT = Path(__file__).resolve().parents[1]
VERIFY_TAG = ROOT / "scripts" / "release" / "verify_release_tag.py"


def _pyproject(tmp_path: Path, version: str = "1.1.0") -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(f'[project]\nname = "swu-checkin"\nversion = "{version}"\n', encoding="utf-8")
    return path


def test_package_version_matches_project_metadata():
    with (ROOT / "pyproject.toml").open("rb") as source:
        version = tomllib.load(source)["project"]["version"]

    assert swu_checkin.__version__ == version == "1.1.0"


def test_release_tag_matches_project_version(tmp_path: Path):
    completed = subprocess.run(
        [sys.executable, str(VERIFY_TAG), "--pyproject", str(_pyproject(tmp_path)), "--tag", "v1.1.0"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "1.1.0"


@pytest.mark.parametrize("tag", ["v1.0.0", "v1.1.1", "1.1.0"])
def test_release_tag_mismatch_fails(tmp_path: Path, tag: str):
    completed = subprocess.run(
        [sys.executable, str(VERIFY_TAG), "--pyproject", str(_pyproject(tmp_path)), "--tag", tag],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "does not match project version" in completed.stderr
