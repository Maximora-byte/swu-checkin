"""Check APK ABIs, excluded OCR packages and actual distribution notices."""

import argparse
import hashlib
import json
from contextlib import ExitStack
from email import message_from_bytes
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, is_zipfile

ROOT = Path(__file__).resolve().parents[2]
LICENSE_ASSETS = ROOT / "android/app/src/main/assets/licenses"
INVENTORY_PATH = "assets/licenses/inventory.json"


def verify_licenses(archive: ZipFile, nested: dict[str, ZipFile]) -> dict[str, int]:
    """Trust reviewed repository inputs, never checksums supplied only by an APK."""
    expected_bytes = (LICENSE_ASSETS / "inventory.json").read_bytes()
    if INVENTORY_PATH not in archive.namelist() or archive.read(INVENTORY_PATH) != expected_bytes:
        raise ValueError("missing or changed license inventory")
    inventory = json.loads(expected_bytes)

    def read(path: str) -> bytes:
        container, separator, member = path.partition("!/")
        try:
            return nested[container].read(member) if separator else archive.read(container)
        except KeyError as exc:
            raise ValueError(f"missing distribution notice/runtime file: {path}") from exc

    for record in (
        inventory["license_files"]
        + inventory["nested_notices"]
        + inventory["native_files"]
        + inventory["runtime_archives"]
    ):
        data = read(record["path"])
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError(f"changed distribution notice/runtime file: {record['path']}")

    expected_assets = {record["path"] for record in inventory["license_files"]} | {INVENTORY_PATH}
    actual_assets = {
        name for name in archive.namelist() if name.startswith("assets/licenses/") and not name.endswith("/")
    }
    if actual_assets != expected_assets:
        raise ValueError("unreviewed license asset set")

    # Dependency upgrades must renew the inventory, even when the old notices
    # remain in an APK alongside the new code. Match all distribution identities.
    expected_metadata = {item["metadata_path"] for item in inventory["python_distributions"]}
    actual_metadata = {
        f"{container}!/{name}"
        for container, packages in nested.items()
        for name in packages.namelist()
        if name.endswith(".dist-info/METADATA")
    }
    if actual_metadata != expected_metadata:
        raise ValueError("unreviewed Python distribution set")
    for item in inventory["python_distributions"]:
        data = read(item["metadata_path"])
        metadata = message_from_bytes(data)
        if (
            metadata["Name"] != item["name"]
            or metadata["Version"] != item["version"]
            or hashlib.sha256(data).hexdigest() != item["metadata_sha256"]
        ):
            raise ValueError("unreviewed Python distribution version")

    expected_native = {item["path"] for item in inventory["native_files"]}
    actual_native = {name for name in archive.namelist() if name.endswith(".so")} | {
        f"{container}!/{name}"
        for container, packages in nested.items()
        for name in packages.namelist()
        if name.endswith(".so")
    }
    if actual_native != expected_native:
        raise ValueError("unreviewed native distribution set")
    return {
        "license_assets": len(inventory["license_files"]),
        "nested_notices": len(inventory["nested_notices"]),
        "python_distributions": len(inventory["python_distributions"]),
        "native_files": len(inventory["native_files"]),
        "maven_components": len(inventory["maven_components"]),
        "runtime_archives": len(inventory["runtime_archives"]),
    }


def inspect_apk(path: Path) -> dict[str, object]:
    with ExitStack() as stack:
        archive = stack.enter_context(ZipFile(path))
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate APK entries")
        packaged_names = list(names)
        nested = {}
        # Chaquopy requirements and source archives use .imy, not .zip. Inspect
        # their actual contents: checking only APK top-level names is insufficient.
        for name in names:
            if name.startswith("assets/chaquopy/") and name.endswith((".imy", ".zip")):
                data = BytesIO(archive.read(name))
                if not is_zipfile(data):
                    raise ValueError("unrecognized Python package archive")
                packages = stack.enter_context(ZipFile(data))
                if len(packages.namelist()) != len(set(packages.namelist())):
                    raise ValueError("duplicate Python archive entries")
                nested[name] = packages
                packaged_names.extend(packages.namelist())
        abis = sorted({name.split("/")[1] for name in names if name.startswith("lib/")})
        if abis != ["arm64-v8a", "x86_64"]:
            raise ValueError("expected exactly two 64-bit ABIs")
        for abi in abis:
            if f"lib/{abi}/libpython3.13.so" not in names:
                raise ValueError("missing Python 3.13 runtime")
        forbidden = ("ddddocr", "onnxruntime", "opencv", "pillow", "pil/")
        if any(part in name.lower() for name in packaged_names for part in forbidden):
            raise ValueError("unexpected desktop OCR dependency")
        licenses = verify_licenses(archive, nested)
    return {
        "abis": abis,
        "python": "3.13",
        "desktop_ocr_excluded": True,
        "size_bytes": path.stat().st_size,
        "distribution_notices": licenses,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect_apk(args.apk), sort_keys=True))
