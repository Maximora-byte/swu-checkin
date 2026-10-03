"""Production Android gates must reject unsafe data handling and unsigned/debug builds."""

import struct
import sys
from importlib import import_module
from pathlib import Path

import pytest

# The pytest console entry point does not add the checkout root to sys.path.
# Load only these repository scripts, then restore the global search path so
# both console pytest and python -m pytest exercise the same module objects.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    device_verifier = import_module("scripts.android.verify_release_device")
    apk_verifier = import_module("scripts.android.verify_signed_apk")
finally:
    sys.path.pop(0)

require_absent = device_verifier.require_absent
certificate_digest = apk_verifier.certificate_digest
verify_elf = apk_verifier.verify_elf
verify_manifest = apk_verifier.verify_manifest


@pytest.mark.parametrize("text,code", [("package:/data/app/user/base.apk", 0), ("permission denied", 1), ("", 2)])
def test_release_acceptance_preserves_existing_data(text, code):
    with pytest.raises(ValueError, match="existing app data"):
        require_absent(text, code)


def test_release_manifest_rejects_debug_and_old_versions():
    manifest = (
        "package: name='io.github.maximorabyte.swucheckin' versionCode='4' versionName='0.1.2-preview'\n"
        "sdkVersion:'24'\ntargetSdkVersion:'36'\n"
    )
    verify_manifest(manifest)
    verify_manifest(manifest.replace("sdkVersion:", "minSdkVersion:"))
    with pytest.raises(ValueError):
        verify_manifest(manifest + "minSdkVersion:'23'\n")
    for bad in (manifest + "application-debuggable", manifest.replace("versionCode='4'", "versionCode='3'")):
        with pytest.raises(ValueError):
            verify_manifest(bad)


def test_release_certificate_requires_one_signer():
    cert = "Signer #1 certificate SHA-256 digest: " + "ab" * 32 + "\n"
    assert certificate_digest(cert) == "ab" * 32
    with pytest.raises(ValueError):
        certificate_digest(cert + "Signer #2 certificate SHA-256 digest: " + "cd" * 32)


def test_elf_rejects_small_or_incongruent_load_alignment():
    data = bytearray(120)
    data[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HH", data, 54, 56, 1)
    struct.pack_into("<IIQQQQQQ", data, 64, 1, 5, 0, 0, 0, 1, 1, 16384)
    verify_elf(data)
    struct.pack_into("<Q", data, 112, 4096)
    with pytest.raises(ValueError, match="16 KB"):
        verify_elf(data)
    struct.pack_into("<Q", data, 112, 16384)
    struct.pack_into("<Q", data, 80, 4096)
    with pytest.raises(ValueError, match="16 KB"):
        verify_elf(data)


def test_release_device_stops_on_adb_failure_even_with_complete_test_output(tmp_path, monkeypatch):
    """A failed runner transport cannot be laundered through an earlier OK line."""
    import argparse
    import subprocess

    verifier = device_verifier

    certificate = "ab" * 32
    apk = tmp_path / "app.apk"
    tests = tmp_path / "app-test.apk"
    apk.write_bytes(b"fixture production APK")
    tests.write_bytes(b"fixture test APK")
    calls = []

    def report(expected):
        records = []
        for klass, method in sorted(expected):
            records += [
                f"INSTRUMENTATION_STATUS: class={klass}",
                f"INSTRUMENTATION_STATUS: test={method}",
                "INSTRUMENTATION_STATUS_CODE: 0",
            ]
        return "\n".join(records) + f"\nOK ({len(expected)} tests)\nINSTRUMENTATION_CODE: -1\n"

    def run(command, **kwargs):
        calls.append(command)
        output = ""
        code = 0
        if "getconf" in command:
            output = "4096\n"
        elif "getprop" in command:
            output = {"ro.build.version.sdk": "35", "ro.product.cpu.abi": "x86_64", "ro.kernel.qemu": "1"}[command[-1]]
        elif "--print-certs" in command:
            output = f"Signer #1 certificate SHA-256 digest: {certificate}\n"
        elif "instrument" in command:
            output = report(verifier.RELEASE_EXPECTED_TESTS)
            code = 17
        elif "install" in command or "clear" in command:
            output = "Success\n"
        return subprocess.CompletedProcess(command, code, stdout=output, stderr="")

    monkeypatch.setattr(verifier.subprocess, "run", run)
    monkeypatch.setattr(verifier, "verify_apk", lambda _: {"certificate_sha256": certificate})
    arguments = argparse.Namespace(
        adb=tmp_path / "adb",
        serial="disposable-fixture",
        apk=apk,
        test_apk=tests,
        sdk=tmp_path,
        java=tmp_path / "java",
        certificate=tmp_path / "certificate",
        evidence_dir=tmp_path / "evidence",
        api=35,
        abi="x86_64",
        page_size=4096,
    )
    with pytest.raises(
        (ValueError, RuntimeError, subprocess.CalledProcessError), match="instrumentation|instrument|runner|adb"
    ):
        verifier.accept(arguments)
    assert not any("clear" in command for command in calls)
    assert sum("instrument" in command for command in calls) == 1
    assert (arguments.evidence_dir / "instrumentation-fresh-install.txt").exists()


def test_signed_preview_rejects_source_changes_after_metadata_generation(tmp_path, monkeypatch):
    """A matching HEAD alone does not prove the files built stayed unchanged."""
    import argparse
    import hashlib
    import json
    import subprocess
    from zipfile import ZipFile

    verifier = apk_verifier

    commit, tree = "a" * 40, "b" * 40
    lock = tmp_path / "uv.lock"
    lock.write_bytes(b"reviewed dependency lock")
    certificate = tmp_path / "certificate.cer"
    certificate.write_bytes(b"fixture DER certificate")
    cert_digest = hashlib.sha256(certificate.read_bytes()).hexdigest()
    manifest = (
        "package: name='io.github.maximorabyte.swucheckin' versionCode='4' versionName='0.1.2-preview'\n"
        "sdkVersion:'24'\ntargetSdkVersion:'36'\n"
    )
    native = bytearray(120)
    native[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<Q", native, 32, 64)
    struct.pack_into("<HH", native, 54, 56, 1)
    struct.pack_into("<IIQQQQQQ", native, 64, 1, 5, 0, 0, 0, 1, 1, 16384)
    provenance = {
        "source_commit": commit,
        "source_tree": tree,
        "source_dirty": False,
        "project_version": "2.1.0",
        "android_version": "0.1.2-preview",
        "android_version_code": 4,
        "uv_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
    }
    apk = tmp_path / "fixture.apk"
    with ZipFile(apk, "w") as package:
        package.writestr("assets/BUILD-INFO.json", json.dumps(provenance))
        package.writestr("lib/x86_64/fixture.so", native)
    dirty = []
    debug_components = []

    def git(command, **kwargs):
        if "status" in command:
            return " M src/changed.py\n" if dirty else ""
        return commit + "\n" if command[-1] == "HEAD" else tree + "\n"

    def run(command, **kwargs):
        output = ""
        if "badging" in command:
            output = manifest
        elif "xmltree" in command:
            output = "\n".join(debug_components)
        elif "--print-certs" in command:
            output = f"Signer #1 certificate SHA-256 digest: {cert_digest}\n"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    monkeypatch.setattr(verifier, "inspect_apk", lambda _: {})
    monkeypatch.setattr(verifier.subprocess, "run", run)
    monkeypatch.setattr(verifier.subprocess, "check_output", git)
    arguments = argparse.Namespace(apk=apk, sdk=tmp_path, java=tmp_path / "java", certificate=certificate)
    assert verifier.verify(arguments)["passed"]
    for component in ("LockProbeService", "DesignPreviewActivity"):
        debug_components.append(component)
        with pytest.raises(ValueError, match="debug component"):
            verifier.verify(arguments)
        debug_components.clear()
    dirty.append(True)
    with pytest.raises(ValueError, match="clean source checkout"):
        verifier.verify(arguments)
    dirty.clear()
    lock.write_bytes(b"changed dependency lock after metadata was created")
    with pytest.raises(ValueError, match="source or version"):
        verifier.verify(arguments)


@pytest.mark.parametrize("suffix", ["", ".test"])
def test_release_device_preserves_uninstalled_packages_with_retained_data(tmp_path, monkeypatch, suffix):
    import argparse
    import subprocess

    verifier = device_verifier

    calls = []
    retained = verifier.APP_ID + suffix

    def run(command, **kwargs):
        calls.append(command)
        output, code = "", 0
        if "getconf" in command:
            output = "4096\n"
        elif "getprop" in command:
            output = {"ro.build.version.sdk": "35", "ro.product.cpu.abi": "x86_64", "ro.kernel.qemu": "1"}[command[-1]]
        elif "path" in command:
            code = 1  # No active APK path, but uninstall -k retained private data.
        elif "packages" in command and command[-1] == retained:
            output = f"package:{retained}\n"
        return subprocess.CompletedProcess(command, code, stdout=output, stderr="")

    def unexpected_verification(_):
        raise AssertionError("APK installation/verification reached before retained data was checked")

    monkeypatch.setattr(verifier.subprocess, "run", run)
    monkeypatch.setattr(verifier, "verify_apk", unexpected_verification)
    arguments = argparse.Namespace(
        adb=tmp_path / "adb",
        serial="disposable-fixture",
        evidence_dir=tmp_path / "evidence",
        api=35,
        abi="x86_64",
        page_size=4096,
    )
    with pytest.raises(ValueError, match="retained package data"):
        verifier.accept(arguments)
    assert not any("install" in command or "clear" in command for command in calls)
