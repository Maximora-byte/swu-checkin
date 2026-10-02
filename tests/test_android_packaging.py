"""Static/offline safeguards; never substitutes for actual Android device tests."""

import importlib.util
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_android_manifest_has_only_internet_and_no_backup():
    manifest = ElementTree.parse(ROOT / "android/app/src/main/AndroidManifest.xml").getroot()
    ns = "{http://schemas.android.com/apk/res/android}"
    assert [item.attrib[ns + "name"] for item in manifest.findall("uses-permission")] == ["android.permission.INTERNET"]
    app = manifest.find("application")
    assert app.attrib[ns + "allowBackup"] == "false"
    assert app.attrib[ns + "usesCleartextTraffic"] == "false"
    assert not app.findall("receiver")
    assert not app.findall("service")


def test_android_requirements_are_explicit_and_no_ocr():
    import tomllib

    locked = {item["name"]: item["version"] for item in tomllib.loads((ROOT / "uv.lock").read_text())["package"]}
    requirements = (ROOT / "android/requirements-android.txt").read_text().splitlines()
    names = set()
    for line in requirements:
        if not line or line.startswith("#"):
            continue
        name, version = line.split("==")
        assert locked[name] == version
        names.add(name)
    assert {"requests", "beautifulsoup4", "tzdata"} <= names
    assert not names.intersection({"ddddocr", "pillow", "onnxruntime", "numpy", "opencv-python-headless"})


def test_apk_inspector_rejects_wrong_python_or_abi(tmp_path):
    inspect = load_script("apk_inspector", "scripts/android/verify_apk.py").inspect_apk
    apk = tmp_path / "app.apk"
    with ZipFile(apk, "w") as archive:
        archive.writestr("lib/arm64-v8a/libpython3.13.so", b"fixture")
    with pytest.raises(ValueError, match="two 64-bit"):
        inspect(apk)
    with ZipFile(apk, "a") as archive:
        archive.writestr("lib/x86_64/libpython3.13.so", b"fixture")
    assert inspect(apk)["python"] == "3.13"
    with ZipFile(apk, "a") as archive:
        archive.writestr("assets/onnxruntime.so", b"fixture")
    with pytest.raises(ValueError, match="OCR"):
        inspect(apk)


def test_offline_probe_imports_core_without_school_requests(tmp_path, monkeypatch):
    import requests

    def forbidden(*args, **kwargs):
        raise AssertionError("offline probe attempted a network request")

    monkeypatch.setattr(requests.Session, "request", forbidden)
    module = load_script("android_probe", "android/app/src/main/python/android_probe.py")
    import json

    report = json.loads(module.run(str(tmp_path), False))
    # Other tests may import OCR in the pytest process; device test uses a fresh interpreter.
    assert report["core_import"]
    assert report["timezone"]
    assert report["private_storage"]
    assert report["formal_lock_contention"]
    assert report["formal_lock_released"]
    assert report["https"] == "not_run"
    assert str(tmp_path) not in json.dumps(report)


def test_probe_rejects_relative_directory(monkeypatch):
    import json

    module = load_script("android_probe", "android/app/src/main/python/android_probe.py")
    report = json.loads(module.run("relative-path", False))
    assert not report["passed"]
    assert report["unexpected_failure"]


def test_apk_inspector_checks_compressed_python_archives(tmp_path):
    from io import BytesIO

    inspect = load_script("apk_inspector_nested", "scripts/android/verify_apk.py").inspect_apk
    packages = BytesIO()
    with ZipFile(packages, "w") as archive:
        archive.writestr("PIL/__init__.pyc", b"fixture")
    apk = tmp_path / "app.apk"
    with ZipFile(apk, "w") as archive:
        for abi in ("arm64-v8a", "x86_64"):
            archive.writestr(f"lib/{abi}/libpython3.13.so", b"fixture")
        archive.writestr("assets/chaquopy/requirements-common.imy", packages.getvalue())
    with pytest.raises(ValueError, match="OCR"):
        inspect(apk)


def successful_instrumentation_report(verifier):
    records = []
    for cls, method in sorted(verifier.EXPECTED_TESTS):
        records.extend(
            [
                f"INSTRUMENTATION_STATUS: class={cls}",
                f"INSTRUMENTATION_STATUS: test={method}",
                "INSTRUMENTATION_STATUS_CODE: 0",
            ]
        )
    return "\n".join(records) + "\nOK (3 tests)\nINSTRUMENTATION_CODE: -1\n"


@pytest.mark.parametrize(
    "report",
    [
        "",
        "OK (0 tests)",
        "OK (2 tests)",
        "OK (3 tests)\nFAILURES!!!",
        "INSTRUMENTATION_FAILED: crash",
        "OK (3 tests)",
        "OK (3 tests)\nINSTRUMENTATION_CODE: 0",
    ],
)
def test_instrumentation_report_fails_closed(report):
    verifier = load_script("instrumentation_verifier", "scripts/android/verify_instrumentation.py")
    with pytest.raises(ValueError):
        verifier.verify(report)


def test_instrumentation_report_accepts_all_tests():
    verifier = load_script("instrumentation_verifier", "scripts/android/verify_instrumentation.py")
    assert verifier.verify(successful_instrumentation_report(verifier)) == 3


def test_instrumentation_report_rejects_wrong_identity_or_skipped_test():
    verifier = load_script("instrumentation_verifier", "scripts/android/verify_instrumentation.py")
    report = successful_instrumentation_report(verifier)
    for changed in [
        report.replace("lockIsSharedAndProcessDeathReleasesIt", "unrelatedTest"),
        report.replace("STATUS_CODE: 0", "STATUS_CODE: -3", 1),
        report.replace("INSTRUMENTATION_CODE: -1", "INSTRUMENTATION_CODE: 0"),
        report + "INSTRUMENTATION_CODE: -1\n",
    ]:
        with pytest.raises(ValueError):
            verifier.verify(changed)


def test_debug_lock_service_is_private_and_separate_process():
    manifest = ElementTree.parse(ROOT / "android/app/src/debug/AndroidManifest.xml").getroot()
    ns = "{http://schemas.android.com/apk/res/android}"
    (service,) = manifest.find("application").findall("service")
    assert service.attrib[ns + "exported"] == "false"
    assert service.attrib[ns + "process"] == ":lockprobe"
    assert service.attrib[ns + "name"] == ".LockProbeService"
    assert not service.findall("intent-filter")
