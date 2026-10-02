"""Fail closed if the feasibility APK packages desktop OCR/native dependencies."""

import argparse
import json
from pathlib import Path
from zipfile import ZipFile


def inspect_apk(path: Path) -> dict[str, object]:
    with ZipFile(path) as archive:
        names = archive.namelist()
    abis = sorted({name.split("/")[1] for name in names if name.startswith("lib/")})
    if abis != ["arm64-v8a", "x86_64"]:
        raise ValueError("expected exactly two 64-bit ABIs")
    for abi in abis:
        if f"lib/{abi}/libpython3.13.so" not in names:
            raise ValueError("missing Python 3.13 runtime")
    forbidden = ("ddddocr", "onnxruntime", "libopencv", "Pillow", "/PIL/")
    if any(part in name for name in names for part in forbidden):
        raise ValueError("unexpected desktop OCR dependency")
    return {"abis": abis, "python": "3.13", "desktop_ocr_excluded": True, "size_bytes": path.stat().st_size}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect_apk(args.apk), sort_keys=True))
