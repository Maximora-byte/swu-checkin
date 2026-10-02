"""The portable delivery wraps the frozen app without changing its contents."""

import hashlib
import importlib.util
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("portable", Path(__file__).with_name("portable.py"))
assert spec is not None and spec.loader is not None
portable = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portable)


@pytest.fixture
def bundle(tmp_path):
    app = tmp_path / "app"
    (app / "_internal/build-info").mkdir(parents=True)
    for name, data in {
        "SWUCheckin.exe": b"frozen application",
        "_internal/build-info/BUILD-INFO.json": b'{"source_commit":"example"}',
        "_internal/build-info/TOOLCHAIN.txt": b"toolchain",
        "_internal/中文 space.dat": b"resource",
        "SHA256SUMS.txt": b"old manifest is replaced",
    }.items():
        (app / name).write_bytes(data)
    return app, tmp_path / "SWUCheckin-2.0.0-win-x64-Portable.zip", Path(__file__).parent


def test_portable_structure_manifest_and_unchanged_installer_input(bundle):
    app, output, resources = bundle
    before = {p.relative_to(app).as_posix(): p.read_bytes() for p in app.rglob("*") if p.is_file()}
    portable.create_portable(app, output, resources)
    assert before == {p.relative_to(app).as_posix(): p.read_bytes() for p in app.rglob("*") if p.is_file()}
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert all(name.startswith("SWUCheckin/") for name in names)
        manifest = archive.read("SWUCheckin/SHA256SUMS.txt").decode().splitlines()
        assert [line.split("  ", 1)[1] for line in manifest] == sorted(
            name.removeprefix("SWUCheckin/") for name in names if name != "SWUCheckin/SHA256SUMS.txt"
        )
        for line in manifest:
            digest, name = line.split("  ", 1)
            assert hashlib.sha256(archive.read("SWUCheckin/" + name)).hexdigest() == digest
        for name, data in before.items():
            if name != "SHA256SUMS.txt":
                assert archive.read("SWUCheckin/" + name) == data
        assert "无需" in archive.read("SWUCheckin/README-PORTABLE.txt").decode()
        assert archive.read("SWUCheckin/BUILD-INFO.json") == before["_internal/build-info/BUILD-INFO.json"]


def test_portable_is_stable_for_same_input_and_epoch(bundle, monkeypatch):
    app, output, resources = bundle
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    portable.create_portable(app, output, resources)
    first = output.read_bytes()
    portable.create_portable(app, output, resources)
    assert output.read_bytes() == first
    assert not output.with_suffix(".zip.tmp").exists()


@pytest.mark.parametrize("name", ["SWUCheckin.exe", "_internal/build-info/BUILD-INFO.json"])
def test_missing_app_or_provenance_fails(bundle, name):
    app, output, resources = bundle
    (app / name).unlink()
    with pytest.raises(ValueError, match="complete frozen"):
        portable.create_portable(app, output, resources)
    assert not output.exists()


def test_output_inside_app_fails(bundle):
    app, _, resources = bundle
    with pytest.raises(ValueError, match="outside"):
        portable.create_portable(app, app / "portable.zip", resources)


def test_portable_refuses_missing_instructions_or_licenses(bundle, tmp_path):
    app, output, _ = bundle
    with pytest.raises(ValueError, match="instructions, license"):
        portable.create_portable(app, output, tmp_path / "missing")
    assert not output.exists()


def test_bundled_tcl_license_matches_upstream_release():
    license_path = Path(__file__).parent / "licenses/Tcl-8.6.15-LICENSE.txt"
    assert hashlib.sha256(license_path.read_bytes()).hexdigest() == (
        "c0a69a2bfd757361ec7e6143973b103c90409316b49e9c88db26ad6388e79f16"
    )


def test_symbolic_link_fails(bundle):
    app, output, resources = bundle
    try:
        (app / "linked.dat").symlink_to(app / "SWUCheckin.exe")
    except OSError:
        pytest.skip("Creating symlinks is not available")
    with pytest.raises(ValueError, match="symbolic"):
        portable.create_portable(app, output, resources)


def test_build_produces_portable_and_ci_verifies_before_installation():
    root = Path(__file__).resolve().parents[2]
    build = (root / "scripts/windows/build.ps1").read_text()
    workflow = (root / ".github/workflows/windows-desktop.yml").read_text()
    assert "packaging/windows/portable.py" in build
    assert "win-x64-Portable.zip" in build
    assert workflow.index("./scripts/windows/verify-portable.ps1") < workflow.index(
        "./scripts/windows/verify-install.ps1"
    )
    assert "scripts/windows/verify-portable.ps1" in workflow.split("workflow_dispatch:")[0]
