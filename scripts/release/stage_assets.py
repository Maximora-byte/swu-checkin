"""Stage verified user packages; never create tags, releases, or execute binaries.

Inputs are the successful build jobs of the same workflow run. The Android CI
debug APK deliberately stays outside this release set: a persistent signing key
and its separately reviewed candidate are managed outside untrusted PR jobs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

from verify_artifacts import _verify_archives, safe_archive_path


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid object: {path.name}")
    return value


def _single(root: Path, pattern: str) -> Path:
    files = sorted(root.glob(pattern))
    if len(files) != 1 or not files[0].is_file() or files[0].is_symlink():
        raise ValueError(f"expected exactly one regular {pattern}")
    return files[0]


def _verify_checksums(root: Path) -> set[str]:
    """Validate every producer manifest entry without resolving outside its root."""
    seen: set[str] = set()
    for line in (root / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None:
            raise ValueError("invalid producer checksum manifest")
        digest, name = match.groups()
        relative = safe_archive_path(root, name)
        path = root / relative
        if name in seen or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("duplicate, missing, or unsafe producer checksum entry")
        if sha256(path) != digest:
            raise ValueError(f"producer checksum mismatch: {name}")
        seen.add(name)
    if not seen:
        raise ValueError("empty producer checksum manifest")
    return seen


def _provenance(root: Path, version: str, commit: str, architecture: str, platform: str) -> dict:
    info = _json(root / "BUILD-INFO.json")
    if (
        info.get("application_version") != version
        or info.get("source_commit") != commit
        or info.get("source_dirty") is not False
        or info.get("architecture") != architecture
        or info.get("preview") is not True
    ):
        raise ValueError(f"{platform} package version, source, architecture or preview provenance mismatch")
    if platform == "windows":
        if info.get("signature") != "unsigned":
            raise ValueError("Windows preview must explicitly disclose its unsigned state")
    elif info.get("signature") != "ad-hoc; no Developer ID" or info.get("notarized") is not False:
        raise ValueError("macOS preview must explicitly disclose ad-hoc signing and no notarization")
    return info


def _verify_zip_licenses(archive_path: Path, root: Path, prefix: str, repository_license: bytes) -> None:
    inventory_data = (root / "LICENSE-INVENTORY.json").read_bytes()
    inventory = json.loads(inventory_data)
    if (
        not isinstance(inventory, dict)
        or inventory.get("schema_version") != 1
        or inventory.get("missing") != []
        or not isinstance(inventory.get("components"), list)
        or not inventory["components"]
    ):
        raise ValueError("native license inventory is missing or incomplete")
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        for name in names:
            safe_archive_path(archive_path, name)
        if len(names) != len(set(names)) or archive.testzip() is not None:
            raise ValueError("native ZIP contains duplicate entries or a CRC failure")
        if archive.read(prefix + "LICENSE-INVENTORY.json") != inventory_data:
            raise ValueError("native package and external license inventories differ")
        if archive.read(prefix + "BUILD-INFO.json") != (root / "BUILD-INFO.json").read_bytes():
            raise ValueError("native package and external source provenance differ")
        license_name = (
            "SWUCheckin/_internal/LICENSE"
            if prefix.startswith("SWUCheckin/")
            else "SWUCheckin.app/Contents/Resources/LICENSE"
        )
        if archive.read(license_name) != repository_license:
            raise ValueError("native package does not contain the repository's exact MIT license")
        for component in inventory["components"]:
            if not isinstance(component, dict) or not component.get("name") or not component.get("files"):
                raise ValueError("native license component has no preserved license files")
            for entry in component["files"]:
                if not isinstance(entry, dict):
                    raise ValueError("invalid native license entry")
                name, digest = entry.get("path"), entry.get("sha256")
                if (
                    not isinstance(name, str)
                    or not isinstance(digest, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", digest)
                ):
                    raise ValueError("invalid native license path or digest")
                safe_archive_path(archive_path, name)
                if hashlib.sha256(archive.read(prefix + name)).hexdigest() != digest:
                    raise ValueError("native bundled license digest mismatch")


def _verify_python_metadata(wheel: Path, sdist: Path, version: str, repository_license: bytes) -> None:
    _verify_archives(wheel, sdist)
    with zipfile.ZipFile(wheel) as archive:
        metadata = BytesParser().parsebytes(archive.read(f"swu_checkin-{version}.dist-info/METADATA"))
        license_data = archive.read(f"swu_checkin-{version}.dist-info/licenses/LICENSE")
        if (
            metadata.get("Version") != version
            or metadata.get("Name") != "swu-checkin"
            or license_data != repository_license
        ):
            raise ValueError("wheel metadata version or repository license mismatch")
    with tarfile.open(sdist, "r:gz") as archive:
        source = archive.extractfile(f"swu_checkin-{version}/PKG-INFO")
        license_source = archive.extractfile(f"swu_checkin-{version}/LICENSE")
        if source is None or license_source is None:
            raise ValueError("sdist metadata or repository license missing")
        with source, license_source:
            metadata = BytesParser().parsebytes(source.read())
            if (
                metadata.get("Version") != version
                or metadata.get("Name") != "swu-checkin"
                or license_source.read() != repository_license
            ):
                raise ValueError("sdist metadata version or repository license mismatch")


def stage_assets(
    python_dist: Path,
    windows: Path,
    macos_arm64: Path,
    macos_x86_64: Path,
    version: str,
    commit: str,
    notes: Path,
    repository_license: Path,
    output: Path,
) -> dict:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("an exact numeric release version and source commit are required")
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to overwrite an existing staged release")
    if notes.name != f"v{version}.md" or not notes.read_text(encoding="utf-8").strip():
        raise ValueError("the version's explicit release notes are required")
    python_info = _json(python_dist / "SOURCE-INFO.json")
    if python_info.get("version") != version or python_info.get("source_commit") != commit:
        raise ValueError("Python package source or version mismatch")
    selected: list[tuple[Path, str, str, dict | None]] = [
        (_single(python_dist, f"swu_checkin-{version}-py3-none-any.whl"), "python", "wheel", None),
        (_single(python_dist, f"swu_checkin-{version}.tar.gz"), "python", "sdist", None),
    ]
    _verify_python_metadata(selected[0][0], selected[1][0], version, repository_license.read_bytes())
    windows_checksums = _verify_checksums(windows)
    windows_info = _provenance(windows, version, commit, "AMD64", "windows")
    portable = _single(windows, f"SWUCheckin-{version}-win-x64-Portable.zip")
    _verify_zip_licenses(portable, windows, "SWUCheckin/_internal/build-info/", repository_license.read_bytes())
    installer = _single(windows, f"SWUCheckin-{version}-win-x64-Setup.exe")
    if not {portable.name, installer.name, "BUILD-INFO.json", "LICENSE-INVENTORY.json"} <= windows_checksums:
        raise ValueError("producer manifest does not cover all Windows release inputs")
    with installer.open("rb") as source:
        header = source.read(2)
    if header != b"MZ":
        raise ValueError("Windows installer is not a PE executable")
    selected.extend(
        [(portable, "windows-x64", "portable", windows_info), (installer, "windows-x64", "installer", windows_info)]
    )
    for arch, root in (("arm64", macos_arm64), ("x86_64", macos_x86_64)):
        checksums = _verify_checksums(root)
        info = _provenance(root, version, commit, arch, "macos")
        archive = _single(root, f"SWUCheckin-{version}-macos15-{arch}-preview.zip")
        if not {archive.name, "BUILD-INFO.json", "LICENSE-INVENTORY.json"} <= checksums:
            raise ValueError("producer manifest does not cover all macOS release inputs")
        _verify_zip_licenses(
            archive, root, "SWUCheckin.app/Contents/Resources/build-info/", repository_license.read_bytes()
        )
        selected.append((archive, f"macos-{arch}", "preview-app", info))
    # Validate all inputs before copying anything, keeping a failed preflight
    # distinct from a completed reviewable release directory.
    output.mkdir(parents=True, exist_ok=True)
    assets = []
    for source, platform, kind, provenance in selected:
        target = output / source.name
        shutil.copyfile(source, target)
        assets.append(
            {
                "name": target.name,
                "sha256": sha256(target),
                "size": target.stat().st_size,
                "platform": platform,
                "kind": kind,
                "version": version,
                "source_commit": commit,
                "provenance": provenance,
            }
        )
    for platform, root in (("windows-x64", windows), ("macos-arm64", macos_arm64), ("macos-x86_64", macos_x86_64)):
        for name in ("BUILD-INFO.json", "LICENSE-INVENTORY.json"):
            shutil.copyfile(root / name, output / f"{platform}-{name}")
    shutil.copyfile(python_dist / "SOURCE-INFO.json", output / "python-SOURCE-INFO.json")
    shutil.copyfile(repository_license, output / "LICENSE")
    shutil.copyfile(notes, output / "RELEASE-NOTES.md")
    result = {
        "schema_version": 1,
        "version": version,
        "source_commit": commit,
        "prerelease": True,
        "assets": assets,
        "omitted": {"android": "CI APK uses a temporary debug key; separately reviewed persistent-signature candidate"},
        "limitations": [
            "Windows is unsigned; macOS is ad-hoc signed and unnotarized",
            "native clean-user acceptance and real school-account validation remain incomplete",
        ],
    }
    (output / "ASSET-MANIFEST.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    lines = [f"{sha256(path)}  {path.name}" for path in sorted(output.iterdir()) if path.is_file()]
    (output / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-dist", type=Path, required=True)
    parser.add_argument("--windows-dir", type=Path, required=True)
    parser.add_argument("--macos-arm64-dir", type=Path, required=True)
    parser.add_argument("--macos-x86-64-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--notes", type=Path, required=True)
    parser.add_argument("--repository-license", type=Path, default=Path("LICENSE"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = stage_assets(
        args.python_dist,
        args.windows_dir,
        args.macos_arm64_dir,
        args.macos_x86_64_dir,
        args.version,
        args.commit,
        args.notes,
        args.repository_license,
        args.output,
    )
    print(
        json.dumps(
            {"version": result["version"], "source_commit": result["source_commit"], "assets": len(result["assets"])}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
