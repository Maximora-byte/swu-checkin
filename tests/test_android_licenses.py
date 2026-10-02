"""Distribution gates exercise omission, forgery and unreviewed dependency changes."""

import hashlib
import importlib.util
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "android/app/src/main/assets/licenses"


def load_script(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(data):
    return hashlib.sha256(data).hexdigest()


def license_fixture(tmp_path, monkeypatch):
    verifier = load_script("android_license_verifier", "scripts/android/verify_apk.py")
    notice = b"Copyright fixture author\nPermission granted for redistribution\n"
    metadata = b"Metadata-Version: 2.1\nName: fixture\nVersion: 1.0\nLicense-File: LICENSE\n"
    native = b"\x7fELF fixture native library"
    container = "assets/chaquopy/requirements-common.imy"
    metadata_path = "fixture-1.0.dist-info/METADATA"
    license_path = "fixture-1.0.dist-info/licenses/LICENSE"
    manifest = {
        "license_files": [{"path": "assets/licenses/fixture.txt", "sha256": digest(notice)}],
        "nested_notices": [{"path": f"{container}!/{license_path}", "sha256": digest(notice)}],
        "python_distributions": [
            {
                "name": "fixture",
                "version": "1.0",
                "metadata_path": f"{container}!/{metadata_path}",
                "metadata_sha256": digest(metadata),
            }
        ],
        "native_files": [{"path": "lib/arm64-v8a/fixture.so", "sha256": digest(native)}],
        "maven_components": [],
        "runtime_archives": [],
    }
    expected = json.dumps(manifest).encode()
    assets = tmp_path / "reviewed"
    assets.mkdir()
    (assets / "inventory.json").write_bytes(expected)
    monkeypatch.setattr(verifier, "LICENSE_ASSETS", assets)
    outer = {
        "assets/licenses/inventory.json": expected,
        "assets/licenses/fixture.txt": notice,
        "lib/arm64-v8a/fixture.so": native,
    }
    inner = {metadata_path: metadata, license_path: notice}
    return verifier, container, outer, inner


def zipped(files):
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        for path, payload in files.items():
            archive.writestr(path, payload)
    return data


def verify_fixture(verifier, container, outer, inner):
    with ZipFile(zipped(outer)) as archive, ZipFile(zipped(inner)) as packages:
        return verifier.verify_licenses(archive, {container: packages})


def test_licenses_are_checked_in_actual_outer_and_nested_archives(tmp_path, monkeypatch):
    verifier, container, outer, inner = license_fixture(tmp_path, monkeypatch)
    assert verify_fixture(verifier, container, outer, inner)["python_distributions"] == 1
    del inner["fixture-1.0.dist-info/licenses/LICENSE"]
    with pytest.raises(ValueError, match="missing distribution notice"):
        verify_fixture(verifier, container, outer, inner)


def test_notice_tampering_cannot_be_hidden_by_rewriting_apk_inventory(tmp_path, monkeypatch):
    verifier, container, outer, inner = license_fixture(tmp_path, monkeypatch)
    outer["assets/licenses/fixture.txt"] = b"replaced notice"
    with pytest.raises(ValueError, match="changed distribution notice"):
        verify_fixture(verifier, container, outer, inner)
    forged = json.loads(outer["assets/licenses/inventory.json"])
    forged["license_files"][0]["sha256"] = digest(outer["assets/licenses/fixture.txt"])
    outer["assets/licenses/inventory.json"] = json.dumps(forged).encode()
    with pytest.raises(ValueError, match="changed license inventory"):
        verify_fixture(verifier, container, outer, inner)


def test_dependency_versions_and_additional_distributions_fail_closed(tmp_path, monkeypatch):
    verifier, container, outer, inner = license_fixture(tmp_path, monkeypatch)
    key = "fixture-1.0.dist-info/METADATA"
    inner[key] = inner[key].replace(b"Version: 1.0", b"Version: 2.0")
    with pytest.raises(ValueError, match="distribution version"):
        verify_fixture(verifier, container, outer, inner)
    inner[key] = inner[key].replace(b"Version: 2.0", b"Version: 1.0")
    inner["added-1.0.dist-info/METADATA"] = b"Name: added\nVersion: 1.0\n"
    with pytest.raises(ValueError, match="distribution set"):
        verify_fixture(verifier, container, outer, inner)


def test_runtime_bytes_and_unreviewed_native_files_fail_closed(tmp_path, monkeypatch):
    verifier, container, outer, inner = license_fixture(tmp_path, monkeypatch)
    old = outer["lib/arm64-v8a/fixture.so"]
    outer["lib/arm64-v8a/fixture.so"] = b"\x7fELF upgraded runtime"
    with pytest.raises(ValueError, match="changed distribution notice/runtime file"):
        verify_fixture(verifier, container, outer, inner)
    outer["lib/arm64-v8a/fixture.so"] = old
    inner["added.so"] = b"\x7fELF additional dependency"
    with pytest.raises(ValueError, match="native distribution set"):
        verify_fixture(verifier, container, outer, inner)


def test_missing_inventory_and_unreviewed_license_assets_fail_closed(tmp_path, monkeypatch):
    verifier, container, outer, inner = license_fixture(tmp_path, monkeypatch)
    outer["assets/licenses/extra.txt"] = b"unreviewed notice"
    with pytest.raises(ValueError, match="license asset set"):
        verify_fixture(verifier, container, outer, inner)
    del outer["assets/licenses/inventory.json"]
    with pytest.raises(ValueError, match="missing or changed license inventory"):
        verify_fixture(verifier, container, outer, inner)


def test_reviewed_assets_keep_original_project_and_runtime_license_text():
    manifest = json.loads((ASSETS / "inventory.json").read_text(encoding="utf-8"))
    paths = [item["path"] for item in manifest["license_files"]]
    assert paths == sorted(set(paths))
    actual = {"assets/licenses/" + path.relative_to(ASSETS).as_posix() for path in ASSETS.rglob("*") if path.is_file()}
    assert actual == set(paths) | {"assets/licenses/inventory.json"}
    for item in manifest["license_files"]:
        data = (ROOT / "android/app/src/main" / item["path"]).read_bytes()
        assert digest(data) == item["sha256"]
        assert item["source"].startswith(("https://", "repository:"))
    assert (ASSETS / "SWUCheckin-LICENSE.txt").read_bytes() == (ROOT / "LICENSE").read_bytes()
    assert "Copyright (c) 2017-2025 Chaquo Ltd and contributors" in (ASSETS / "Chaquopy-17.0.0-LICENSE.txt").read_text()
    assert "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2" in (ASSETS / "CPython-3.13.9-LICENSE.txt").read_text()
    assert "CNRI LICENSE AGREEMENT" in (ASSETS / "CPython-3.13.9-LICENSE.txt").read_text()
    expected = {
        tuple(line.split("=="))
        for line in (ROOT / "android/requirements-android.txt").read_text().splitlines()
        if line and not line.startswith("#")
    }
    actual_python = {
        (item["name"].lower().replace("_", "-"), item["version"]) for item in manifest["python_distributions"]
    }
    assert actual_python == expected | {("setuptools", "68.2.2"), ("pyelftools", "0.26")}


def test_gradle_inventory_checks_resolved_versions_and_excludes_constraints(tmp_path, monkeypatch):
    verifier = load_script("maven_inventory", "packaging/android/verify_maven_inventory.py")
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"maven_components": [{"coordinate": "example:runtime:2.0"}]}))
    monkeypatch.setattr(verifier, "INVENTORY", inventory)
    report = "releaseRuntimeClasspath\n+--- example:runtime:1.0 -> 2.0\n+--- example:unused:3.0 (c)\nBUILD SUCCESSFUL\n"
    assert verifier.verify(report) == 1
    with pytest.raises(ValueError, match="unreviewed Maven"):
        verifier.verify(report.replace("-> 2.0", "-> 2.1"))
    with pytest.raises(ValueError, match="incomplete"):
        verifier.verify(report.replace("BUILD SUCCESSFUL", "BUILD FAILED"))
