"""Fail closed if the feasibility APK packages desktop OCR/native dependencies."""

import argparse
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, is_zipfile


def inspect_apk(path: Path) -> dict[str, object]:
    with ZipFile(path) as archive:
        names = archive.namelist()
        packaged_names = list(names)
        # Chaquopy requirements and source archives use .imy, not .zip. Inspect
        # their actual contents: checking only APK top-level names is insufficient.
        for name in names:
            if name.startswith("assets/chaquopy/") and name.endswith((".imy", ".zip")):
                data = BytesIO(archive.read(name))
                if not is_zipfile(data):
                    raise ValueError("unrecognized Python package archive")
                with ZipFile(data) as packages:
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
    return {"abis": abis, "python": "3.13", "desktop_ocr_excluded": True, "size_bytes": path.stat().st_size}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect_apk(args.apk), sort_keys=True))
