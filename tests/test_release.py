from __future__ import annotations

import importlib.util
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

import swu_checkin

ROOT = Path(__file__).resolve().parents[1]
VERIFY_TAG = ROOT / "scripts" / "release" / "verify_release_tag.py"
VERIFY_ARTIFACTS = ROOT / "scripts" / "release" / "verify_artifacts.py"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _load_artifact_verifier():
    spec = importlib.util.spec_from_file_location("verify_artifacts", VERIFY_ARTIFACTS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workflow_job(source: str, name: str, next_name: str | None = None) -> str:
    start = source.index(f"  {name}:\n")
    end = source.index(f"  {next_name}:\n", start) if next_name else len(source)
    return source[start:end]


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


def test_release_workflow_enforces_tag_commit_on_main():
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "git fetch --no-tags origin +refs/heads/main:refs/remotes/origin/main" in workflow
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" origin/main' in workflow
    assert "Tagged commit is not contained in origin/main; refusing release." in workflow


def test_release_workflow_separates_build_and_publish_permissions():
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    build = _workflow_job(workflow, "build-verify", "publish")
    publish = _workflow_job(workflow, "publish")

    assert "permissions:\n      contents: read" in build
    assert "contents: write" not in build
    assert "persist-credentials: false" in build
    assert "permissions:\n      contents: write" in publish
    assert "contents: read" not in publish
    assert "GH_REPO: ${{ github.repository }}" in publish
    assert "--repo" not in publish
    assert "actions/checkout@" not in publish
    assert "setup-uv@" not in publish
    assert "uv sync" not in publish
    assert "pytest" not in publish
    assert "uv build" not in publish
    assert "scripts/release/" not in publish


def test_release_workflow_transfers_only_pinned_verified_artifacts():
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in workflow
    assert "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093" in workflow
    assert "Expected exactly one verified wheel and one verified sdist." in workflow
    assert "--verify-tag" in workflow
    assert "--generate-notes" in workflow


def test_required_quality_context_still_aggregates_all_jobs():
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "  quality:\n    name: quality" in workflow
    assert "needs: [linux-quality, windows-quality, package-quality]" in workflow


def test_artifact_verifier_smokes_wheel_and_sdist_separately(monkeypatch, tmp_path: Path):
    verifier = _load_artifact_verifier()
    wheel = tmp_path / "swu_checkin-1.1.0-py3-none-any.whl"
    sdist = tmp_path / "swu_checkin-1.1.0.tar.gz"
    with zipfile.ZipFile(wheel, mode="w"):
        pass
    with tarfile.open(sdist, mode="w:gz"):
        pass
    calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        verifier,
        "_smoke_install",
        lambda artifact, _version, _uv, label: calls.append((artifact, label)),
    )

    verifier.verify_artifacts(tmp_path, "1.1.0", "uv")

    assert calls == [(wheel.resolve(), "wheel"), (sdist.resolve(), "sdist")]


@pytest.mark.parametrize(
    "member",
    [
        "/absolute/path",
        "package/../escape",
        "package/.git/config",
        "package/.venv/bin/python",
        "package/.pytest_cache/state",
        "package/__pycache__/module.pyc",
        "package/.env",
        "package/credentials.env",
        "package/notify.env",
        "package/auth-token-cache",
        "package/status.json",
        "package/secrets/token",
        "package/private.key",
        "package/private.pem",
    ],
)
def test_archive_verifier_rejects_private_or_unsafe_paths(tmp_path: Path, member: str):
    verifier = _load_artifact_verifier()

    with pytest.raises(RuntimeError):
        verifier._verify_archive_members(tmp_path / "artifact.tar.gz", [member])
