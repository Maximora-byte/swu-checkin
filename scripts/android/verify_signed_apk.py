"""Verify the exact production preview: persistent cert, manifest, licenses and ELF alignment."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

if __package__:
    from .verify_apk import inspect_apk
else:
    from verify_apk import inspect_apk

APP_ID = "io.github.maximorabyte.swucheckin"
ROOT = Path(__file__).resolve().parents[2]
VERSION_NAME = "0.1.1-preview"
VERSION_CODE = 3


def verify_elf(data: bytes) -> None:
    if data[:6] != b"\x7fELF\x02\x01":
        raise ValueError("expected little-endian 64-bit ELF")
    offset = struct.unpack_from("<Q", data, 32)[0]
    size, count = struct.unpack_from("<HH", data, 54)
    if size != 56 or not count or offset + size * count > len(data):
        raise ValueError("invalid ELF program headers")
    loads = 0
    for index in range(count):
        kind, _, file_offset, address, _, _, _, alignment = struct.unpack_from("<IIQQQQQQ", data, offset + index * size)
        if kind == 1:
            loads += 1
            if alignment < 16384 or file_offset % 16384 != address % 16384:
                raise ValueError("ELF load segment is not 16 KB aligned")
    if not loads:
        raise ValueError("ELF has no load segments")


def verify_manifest(text: str) -> None:
    if not re.search(
        rf"^package: name='{re.escape(APP_ID)}' versionCode='{VERSION_CODE}' versionName='{re.escape(VERSION_NAME)}'",
        text,
        re.MULTILINE,
    ):
        raise ValueError("unexpected release package or version")
    if "application-debuggable" in text:
        raise ValueError("production preview must not be debuggable")
    if "sdkVersion:'24'" not in text or "targetSdkVersion:'36'" not in text:
        raise ValueError("unexpected supported Android SDK range")


def certificate_digest(text: str) -> str:
    matches = re.findall(r"^Signer #1 certificate SHA-256 digest: ([a-fA-F0-9]{64})$", text, re.MULTILINE)
    if len(matches) != 1 or re.search(r"^Signer #[2-9]", text, re.MULTILINE):
        raise ValueError("expected exactly one APK signing certificate")
    return matches[0].lower()


def verify(args: argparse.Namespace) -> dict:
    inventory = inspect_apk(args.apk)
    tools = args.sdk / "build-tools" / "35.0.0"

    def run(*command: object) -> str:
        return subprocess.run([str(part) for part in command], check=True, capture_output=True, encoding="utf-8").stdout

    badging = run(tools / "aapt2.exe", "dump", "badging", args.apk)
    verify_manifest(badging)
    manifest = run(tools / "aapt2.exe", "dump", "xmltree", args.apk, "--file", "AndroidManifest.xml")
    if "LockProbeService" in manifest:
        raise ValueError("debug lock probe service in production APK")
    signature = run(
        args.java, "-jar", tools / "lib" / "apksigner.jar", "verify", "--verbose", "--print-certs", args.apk
    )
    digest = certificate_digest(signature)
    expected = hashlib.sha256(args.certificate.read_bytes()).hexdigest()
    if digest != expected:
        raise ValueError("APK does not use the expected persistent certificate")
    run(tools / "zipalign.exe", "-c", "-P", "16", "4", args.apk)
    native = {}

    def inspect(name: str, data: bytes) -> None:
        if "android_lock_probe" in name:
            raise ValueError("debug Python lock probe in production APK")
        if data.startswith(b"\x7fELF"):
            verify_elf(data)
            native[name] = hashlib.sha256(data).hexdigest()

    with ZipFile(args.apk) as apk:
        try:
            provenance = json.loads(apk.read("assets/BUILD-INFO.json"))
        except (KeyError, ValueError) as exc:
            raise ValueError("signed preview requires embedded source provenance") from exc
        commit = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
        tree = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD^{tree}"], text=True).strip()
        if subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True).strip():
            raise ValueError("signed preview verification requires a clean source checkout")
        if (
            provenance.get("source_commit") != commit
            or provenance.get("source_tree") != tree
            or provenance.get("source_dirty") is not False
            or provenance.get("project_version") != "2.1.0"
            or provenance.get("android_version") != VERSION_NAME
            or provenance.get("android_version_code") != VERSION_CODE
            or provenance.get("uv_lock_sha256") != hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest()
        ):
            raise ValueError("signed preview source or version does not match reviewed checkout")
        for name in apk.namelist():
            data = apk.read(name)
            inspect(name, data)
            if name.startswith("assets/chaquopy/") and name.endswith((".imy", ".zip")):
                with ZipFile(BytesIO(data)) as inner:
                    for entry in inner.namelist():
                        inspect(f"{name}!{entry}", inner.read(entry))
    if not native:
        raise ValueError("missing packaged native libraries")
    return {
        "passed": True,
        "application_id": APP_ID,
        "version_name": VERSION_NAME,
        "version_code": VERSION_CODE,
        "debuggable": False,
        "certificate_sha256": digest,
        "apk_sha256": hashlib.sha256(args.apk.read_bytes()).hexdigest(),
        "inventory": inventory,
        "native_16kb_alignment": native,
        "provenance": provenance,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Signed production preview verification passed")
