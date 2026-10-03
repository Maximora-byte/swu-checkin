from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2.1.0"
COMMIT = "a" * 40


@pytest.fixture
def stager(monkeypatch):
    source = ROOT / "scripts/release/stage_assets.py"
    monkeypatch.syspath_prepend(str(source.parent))
    spec = importlib.util.spec_from_file_location("stage_assets", source)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, data: dict) -> bytes:
    content = (json.dumps(data, indent=2) + "\n").encode()
    path.write_bytes(content)
    return content


def _checksum(root: Path) -> None:
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
        for path in sorted(root.iterdir())
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    (root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def inputs(tmp_path: Path) -> dict:
    # These fixtures exercise the packaging boundary without pretending to
    # execute a real native installer or school-account request.
    python_dist, windows, arm, intel = (tmp_path / name for name in ("python", "windows", "arm", "intel"))
    for root in (python_dist, windows, arm, intel):
        root.mkdir()
    _write_json(python_dist / "SOURCE-INFO.json", {"version": VERSION, "source_commit": COMMIT})
    license_file = tmp_path / "LICENSE"
    license_file.write_bytes(b"fixture MIT license\n")
    metadata = f"Name: swu-checkin\nVersion: {VERSION}\n\n".encode()
    with zipfile.ZipFile(python_dist / f"swu_checkin-{VERSION}-py3-none-any.whl", "w") as archive:
        archive.writestr(f"swu_checkin-{VERSION}.dist-info/METADATA", metadata)
        archive.writestr(f"swu_checkin-{VERSION}.dist-info/licenses/LICENSE", license_file.read_bytes())
    with tarfile.open(python_dist / f"swu_checkin-{VERSION}.tar.gz", "w:gz") as archive:
        for name, data in (("PKG-INFO", metadata), ("LICENSE", license_file.read_bytes())):
            entry = tarfile.TarInfo(f"swu_checkin-{VERSION}/{name}")
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
    license_data = b"fixture dependency license\n"
    inventory = {
        "schema_version": 1,
        "missing": [],
        "components": [
            {
                "name": "Python",
                "version": "3.13.15",
                "files": [
                    {
                        "path": "PYTHON-LICENSE.txt",
                        "sha256": hashlib.sha256(license_data).hexdigest(),
                        "source": "fixture",
                    }
                ],
            }
        ],
    }
    for root, architecture, platform in (
        (windows, "AMD64", "windows"),
        (arm, "arm64", "macos"),
        (intel, "x86_64", "macos"),
    ):
        info = {
            "application_version": VERSION,
            "source_commit": COMMIT,
            "source_dirty": False,
            "architecture": architecture,
            "preview": True,
            "signature": "unsigned" if platform == "windows" else "ad-hoc; no Developer ID",
            "notarized": False,
        }
        provenance_bytes = _write_json(root / "BUILD-INFO.json", info)
        inventory_bytes = _write_json(root / "LICENSE-INVENTORY.json", inventory)
        if platform == "windows":
            zip_path = root / f"SWUCheckin-{VERSION}-win-x64-Portable.zip"
            prefix, license_name = "SWUCheckin/_internal/build-info/", "SWUCheckin/_internal/LICENSE"
            (root / f"SWUCheckin-{VERSION}-win-x64-Setup.exe").write_bytes(b"MZfixture installer")
        else:
            zip_path = root / f"SWUCheckin-{VERSION}-macos15-{architecture}-preview.zip"
            prefix, license_name = (
                "SWUCheckin.app/Contents/Resources/build-info/",
                "SWUCheckin.app/Contents/Resources/LICENSE",
            )
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr(prefix + "LICENSE-INVENTORY.json", inventory_bytes)
            archive.writestr(prefix + "BUILD-INFO.json", provenance_bytes)
            archive.writestr(prefix + "PYTHON-LICENSE.txt", license_data)
            archive.writestr(license_name, license_file.read_bytes())
        _checksum(root)
    notes = tmp_path / f"v{VERSION}.md"
    notes.write_text("# Fixture pre-release notes\n", encoding="utf-8")
    return {
        "python_dist": python_dist,
        "windows": windows,
        "macos_arm64": arm,
        "macos_x86_64": intel,
        "version": VERSION,
        "commit": COMMIT,
        "notes": notes,
        "repository_license": license_file,
        "output": tmp_path / "staged",
    }


def test_preflight_stages_user_packages_and_full_provenance_without_debug_apk(stager, inputs: dict):
    result = stager.stage_assets(**inputs)

    assert len(result["assets"]) == 6
    assert result["prerelease"] is True
    assert result["source_commit"] == COMMIT
    assert "temporary debug key" in result["omitted"]["android"]
    output = inputs["output"]
    assert len(list(output.iterdir())) == 17
    assert not list(output.glob("*.apk"))
    stager._verify_checksums(output)
    for asset in result["assets"]:
        assert asset["sha256"] == stager.sha256(output / asset["name"])


def _stable_native_inputs(inputs: dict) -> None:
    for key in ("windows", "macos_arm64", "macos_x86_64"):
        root = inputs[key]
        info = json.loads((root / "BUILD-INFO.json").read_bytes())
        info.update(developer="MatchAll", preview=key != "windows")
        provenance = _write_json(root / "BUILD-INFO.json", info)
        archive_path = next(root.glob("*.zip"))
        with zipfile.ZipFile(archive_path) as archive:
            content = {entry.filename: archive.read(entry) for entry in archive.infolist()}
        name = next(name for name in content if name.endswith("BUILD-INFO.json"))
        content[name] = provenance
        with zipfile.ZipFile(archive_path, "w") as archive:
            for name, data in content.items():
                archive.writestr(name, data)
        _checksum(root)


def test_stable_staging_preserves_macos_preview_restrictions(stager, inputs: dict):
    _stable_native_inputs(inputs)
    result = stager.stage_assets(**inputs, prerelease=False)
    assert result["prerelease"] is False
    assert result["developer"] == "MatchAll"
    assert all(
        asset["provenance"]["preview"] is False for asset in result["assets"] if asset["platform"] == "windows-x64"
    )
    assert all(
        asset["provenance"]["preview"] is True for asset in result["assets"] if asset["platform"].startswith("macos")
    )
    stager._verify_checksums(inputs["output"])


@pytest.mark.parametrize("field,value", [("preview", True), ("developer", "Other")])
def test_stable_staging_rejects_preview_or_incorrect_developer(stager, inputs: dict, field: str, value):
    _stable_native_inputs(inputs)
    root = inputs["windows"]
    info = json.loads((root / "BUILD-INFO.json").read_bytes())
    info[field] = value
    _write_json(root / "BUILD-INFO.json", info)
    _checksum(root)
    with pytest.raises(ValueError, match="provenance mismatch"):
        stager.stage_assets(**inputs, prerelease=False)
    assert not inputs["output"].exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [("source_commit", "b" * 40), ("application_version", "2.0.0"), ("source_dirty", True), ("signature", "unknown")],
)
def test_preflight_rejects_native_source_version_dirty_or_signing_mismatch(stager, inputs: dict, field: str, value):
    root = inputs["windows"]
    info = json.loads((root / "BUILD-INFO.json").read_bytes())
    info[field] = value
    _write_json(root / "BUILD-INFO.json", info)
    _checksum(root)

    with pytest.raises(ValueError, match="provenance mismatch|unsigned state"):
        stager.stage_assets(**inputs)
    assert not inputs["output"].exists()


def test_preflight_rejects_changed_user_package_even_with_same_metadata(stager, inputs: dict):
    portable = next(inputs["windows"].glob("*-Portable.zip"))
    with portable.open("ab") as source:
        source.write(b"changed after producer audit")

    with pytest.raises(ValueError, match="producer checksum mismatch"):
        stager.stage_assets(**inputs)
    assert not inputs["output"].exists()


def test_preflight_rejects_archive_traversal(stager, inputs: dict):
    portable = next(inputs["windows"].glob("*-Portable.zip"))
    with zipfile.ZipFile(portable, "a") as archive:
        archive.writestr("../escape", "fixture")
    _checksum(inputs["windows"])

    with pytest.raises(RuntimeError, match="unsafe archive path"):
        stager.stage_assets(**inputs)


def test_preflight_rejects_renamed_old_package_with_new_external_provenance(stager, inputs: dict):
    portable = next(inputs["windows"].glob("*-Portable.zip"))
    with zipfile.ZipFile(portable) as archive:
        content = {entry.filename: archive.read(entry) for entry in archive.infolist()}
    inner = json.loads(content["SWUCheckin/_internal/build-info/BUILD-INFO.json"])
    inner["application_version"] = "2.0.0"
    content["SWUCheckin/_internal/build-info/BUILD-INFO.json"] = json.dumps(inner).encode()
    with zipfile.ZipFile(portable, "w") as archive:
        for name, data in content.items():
            archive.writestr(name, data)
    _checksum(inputs["windows"])

    with pytest.raises(ValueError, match="external source provenance differ"):
        stager.stage_assets(**inputs)


def test_preflight_rejects_renamed_python_wheel_with_old_metadata(stager, inputs: dict):
    wheel = next(inputs["python_dist"].glob("*.whl"))
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"swu_checkin-{VERSION}.dist-info/METADATA", "Name: swu-checkin\nVersion: 2.0.0\n\n")
        archive.writestr(f"swu_checkin-{VERSION}.dist-info/licenses/LICENSE", inputs["repository_license"].read_bytes())

    with pytest.raises(ValueError, match="wheel metadata version"):
        stager.stage_assets(**inputs)


def test_preflight_rejects_python_provenance_version_mismatch(stager, inputs: dict):
    _write_json(inputs["python_dist"] / "SOURCE-INFO.json", {"version": "2.0.0", "source_commit": COMMIT})

    with pytest.raises(ValueError, match="Python package source or version"):
        stager.stage_assets(**inputs)


def test_preflight_rejects_license_bytes_not_matching_audited_inventory(stager, inputs: dict):
    portable = next(inputs["windows"].glob("*-Portable.zip"))
    with zipfile.ZipFile(portable) as archive:
        content = {entry.filename: archive.read(entry) for entry in archive.infolist()}
    content["SWUCheckin/_internal/build-info/PYTHON-LICENSE.txt"] = b"replaced license"
    with zipfile.ZipFile(portable, "w") as archive:
        for name, data in content.items():
            archive.writestr(name, data)
    _checksum(inputs["windows"])

    with pytest.raises(ValueError, match="bundled license digest mismatch"):
        stager.stage_assets(**inputs)


def test_preflight_rejects_macos_notarization_claim(stager, inputs: dict):
    root = inputs["macos_arm64"]
    info = json.loads((root / "BUILD-INFO.json").read_bytes())
    info["notarized"] = True
    _write_json(root / "BUILD-INFO.json", info)
    _checksum(root)

    with pytest.raises(ValueError, match="no notarization"):
        stager.stage_assets(**inputs)


def test_preflight_rejects_missing_manifest_asset_entry(stager, inputs: dict):
    path = inputs["windows"] / "SHA256SUMS.txt"
    path.write_text(
        "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if "-Setup.exe" not in line) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cover all Windows release inputs"):
        stager.stage_assets(**inputs)


def test_preflight_refuses_overwriting_prior_staged_assets(stager, inputs: dict):
    stager.stage_assets(**inputs)

    with pytest.raises(ValueError, match="refusing to overwrite"):
        stager.stage_assets(**inputs)
