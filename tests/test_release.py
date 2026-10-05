from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tarfile
import textwrap
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

    assert swu_checkin.__version__ == version


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


@pytest.mark.parametrize("version", ["2.1.0rc1", "2.1", "v2.1.0", ""])
def test_release_preflight_rejects_non_numeric_installer_versions(tmp_path: Path, version: str):
    completed = subprocess.run(
        [sys.executable, str(VERIFY_TAG), "--pyproject", str(_pyproject(tmp_path, version))],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "project.version is invalid" in completed.stderr


def test_release_workflow_enforces_tag_commit_on_main():
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "git fetch --no-tags origin +refs/heads/main:refs/remotes/origin/main" in workflow
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" origin/main' in workflow
    assert "Tagged commit is not contained in origin/main; refusing release." in workflow


@pytest.mark.parametrize("channel", ["stable", "prerelease", "invalid"])
def test_release_channel_is_explicit_and_validated(tmp_path: Path, channel: str):
    path = _pyproject(tmp_path)
    with path.open("a", encoding="utf-8") as output:
        output.write(f'\n[tool.swu-checkin.release]\nchannel = "{channel}"\n')
    completed = subprocess.run(
        [sys.executable, str(VERIFY_TAG), "--pyproject", str(path), "--channel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if channel == "invalid":
        assert completed.returncode != 0
        assert "release channel" in completed.stderr
    else:
        assert completed.returncode == 0
        assert completed.stdout.strip() == channel


def test_stable_release_stays_draft_until_persistent_android_package_is_reviewed():
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    publish = _workflow_job(workflow, "publish")
    assert 'if [[ "$RELEASE_CHANNEL" == stable ]]' in publish
    stable = publish.split('if [[ "$RELEASE_CHANNEL" == stable ]]', 1)[1].split("else", 1)[0]
    assert "--verify-tag --draft --latest=false" in stable
    assert "--prerelease" not in stable


def test_release_workflow_separates_build_and_publish_permissions():
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    build = _workflow_job(workflow, "build-verify", "windows")
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
    assert "Expected six user packages and eleven reviewed supporting files." in workflow
    assert "--verify-tag" in workflow
    assert "--prerelease --latest=false" in workflow
    assert "--notes-file RELEASE-NOTES.md" in workflow
    assert "--generate-notes" not in workflow
    assert "refusing to overwrite immutable artifacts" in workflow
    assert "sha256sum -c SHA256SUMS.txt" in workflow


def test_release_workflow_preflights_pr_and_manual_runs_but_only_publishes_tags():
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    publish = _workflow_job(workflow, "publish")

    assert "  pull_request:" in workflow
    assert "  workflow_dispatch:" in workflow
    assert "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')" in publish
    assert "needs: [build-verify, stage-assets]" in publish
    assert "secrets:" not in workflow
    assert workflow.count("GH_TOKEN:") == 1
    assert "GH_TOKEN:" in publish


def test_release_workflow_requires_same_source_and_all_native_gates_before_staging():
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    stage = _workflow_job(workflow, "stage-assets", "publish")

    assert "needs: [build-verify, windows, macos, android-verify]" in stage
    for name in ("windows-desktop.yml", "macos-desktop.yml", "android-feasibility.yml"):
        assert f"uses: ./.github/workflows/{name}" in workflow
    assert workflow.count("ref: ${{ github.sha }}") == 5
    assert '--version "$PROJECT_VERSION" --commit "$GITHUB_SHA"' in stage
    assert 'test -s "docs/releases/v${project_version}.md"' in workflow


def test_required_quality_context_still_aggregates_all_jobs():
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "  quality:\n    name: quality" in workflow
    quality = _workflow_job(workflow, "quality")
    assert "if: ${{ always() }}" in quality
    assert "needs: [changes, preview-quality, linux-quality, windows-quality, package-quality]" in quality


@pytest.mark.parametrize(
    ("preview", "scope", "image", "linux", "windows", "package", "success"),
    [
        ("false", "success", "skipped", "success", "success", "success", True),
        ("true", "success", "success", "skipped", "skipped", "skipped", True),
        ("true", "failure", "success", "skipped", "skipped", "skipped", False),
        ("true", "success", "failure", "skipped", "skipped", "skipped", False),
        ("true", "success", "skipped", "skipped", "skipped", "skipped", False),
        ("true", "success", "cancelled", "skipped", "skipped", "skipped", False),
        ("true", "success", "success", "failure", "skipped", "skipped", False),
        ("false", "success", "skipped", "failure", "success", "success", False),
        ("false", "success", "skipped", "success", "failure", "success", False),
        ("false", "success", "skipped", "success", "success", "failure", False),
        ("false", "success", "skipped", "skipped", "success", "success", False),
    ],
)
def test_quality_gate_executes_real_shell_and_rejects_incomplete_checks(
    preview, scope, image, linux, windows, package, success
):
    quality = _workflow_job(CI_WORKFLOW.read_text(encoding="utf-8"), "quality")
    script = textwrap.dedent(quality.split("        run: |\n", 1)[1])
    bash = shutil.which("bash")
    if os.name == "nt":
        git = shutil.which("git")
        bash = str(Path(git).resolve().parent.parent / "bin/bash.exe") if git else None
    assert bash
    env = {
        **os.environ,
        "PREVIEW_ONLY": preview,
        "SCOPE_RESULT": scope,
        "PREVIEW_RESULT": image,
        "LINUX_RESULT": linux,
        "WINDOWS_RESULT": windows,
        "PACKAGE_RESULT": package,
    }
    result = subprocess.run([bash, "-e", "-o", "pipefail", "-c", script], env=env, capture_output=True, check=False)
    assert (result.returncode == 0) == success


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
        "C:/absolute/path",
        "c:drive-relative/path",
        "\\rooted\\path",
        "\\\\server\\share\\path",
        "//server/share/path",
        "\\\\?\\C:\\absolute\\path",
        "package\\..\\escape",
        "package/..\\escape",
        "package/relative\\path",
        "package/file:stream",
        "package/.git /config",
        "package/.env.",
        "package/\x00hidden",
        "package/\nhidden",
        "",
        ".",
        "package/../escape",
        "package/.git/config",
        "package/.GIT/config",
        "package/.venv/bin/python",
        "package/.pytest_cache/state",
        "package/__pycache__/module.pyc",
        "package/.env",
        "package/.ENV",
        "package/credentials.env",
        "package/notify.env",
        "package/auth-token-cache",
        "package/status.json",
        "package/secrets/token",
        "package/private.key",
        "package/private.pem",
        "package/private.PEM",
    ],
)
def test_archive_verifier_rejects_private_or_unsafe_paths(tmp_path: Path, member: str):
    verifier = _load_artifact_verifier()

    with pytest.raises(RuntimeError):
        verifier._verify_archive_members(tmp_path / "artifact.tar.gz", [member])


def test_archive_verifier_accepts_normal_wheel_and_sdist_members(tmp_path: Path):
    verifier = _load_artifact_verifier()

    verifier._verify_archive_members(
        tmp_path / "artifact.whl",
        [
            "swu_checkin/__init__.py",
            "swu_checkin-2.1.0.dist-info/METADATA",
            "swu_checkin-2.1.0.dist-info/licenses/LICENSE",
        ],
    )
    verifier._verify_archive_members(
        tmp_path / "artifact.tar.gz", ["swu_checkin-2.1.0/", "./swu_checkin-2.1.0/src/swu_checkin/cli.py"]
    )


@pytest.mark.parametrize("members", [["package/file", "package/file"], ["package/file", "package/FILE"]])
def test_archive_verifier_rejects_duplicate_portable_paths(tmp_path: Path, members: list[str]):
    verifier = _load_artifact_verifier()

    with pytest.raises(RuntimeError, match="duplicate portable archive path"):
        verifier._verify_archive_members(tmp_path / "artifact.whl", members)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_archive_verifier_rejects_tar_links_and_special_files(tmp_path: Path, kind: str):
    verifier = _load_artifact_verifier()
    wheel, sdist = tmp_path / "empty.whl", tmp_path / "unsafe.tar.gz"
    with zipfile.ZipFile(wheel, "w"):
        pass
    with tarfile.open(sdist, "w:gz") as archive:
        entry = tarfile.TarInfo("package/link")
        entry.type = {"symlink": tarfile.SYMTYPE, "hardlink": tarfile.LNKTYPE, "fifo": tarfile.FIFOTYPE}[kind]
        entry.linkname = "../../escape"
        archive.addfile(entry)

    with pytest.raises(RuntimeError, match="links or special files"):
        verifier._verify_archives(wheel, sdist)


def test_archive_verifier_rejects_zip_symlinks(tmp_path: Path):
    verifier = _load_artifact_verifier()
    wheel, sdist = tmp_path / "unsafe.whl", tmp_path / "empty.tar.gz"
    with tarfile.open(sdist, "w:gz"):
        pass
    with zipfile.ZipFile(wheel, "w") as archive:
        entry = zipfile.ZipInfo("package/link")
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        archive.writestr(entry, "../../escape")

    with pytest.raises(RuntimeError, match="symbolic links"):
        verifier._verify_archives(wheel, sdist)
