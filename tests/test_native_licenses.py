"""Native packages must carry original notices and reject missing or changed files."""

import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("native_licenses", ROOT / "packaging/license_inventory.py")
assert SPEC is not None and SPEC.loader is not None
LICENSES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LICENSES)


class Distribution:
    metadata = {"Name": "example-wheel"}
    version = "1.0"

    def __init__(self, root: Path, names: tuple[str, ...]):
        self.root = root
        self.files = [PurePosixPath(name) for name in names]

    def locate_file(self, name):
        return self.root / str(name)


def test_preserves_nested_wheel_notices_and_hashes(tmp_path):
    installed = tmp_path / "installed"
    expected = {
        "example/ThirdPartyNotices.txt": b"Original third-party notice\n",
        "example.dist-info/licenses/AUTHORS": b"Original author attribution\n",
    }
    for name, original in expected.items():
        path = installed / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(original)
    output = tmp_path / "output"
    inventory = LICENSES.collect(ROOT, output, [Distribution(installed, tuple(expected))], include_runtime=False)
    assert inventory["missing"] == []
    for item in inventory["components"][0]["files"]:
        original = next(data for name, data in expected.items() if item["path"].endswith(name))
        assert (output / item["path"]).read_bytes() == original
        assert item["sha256"] == hashlib.sha256(original).hexdigest()
    LICENSES.verify(output)


def test_missing_original_notice_fails_and_records_component(tmp_path):
    output = tmp_path / "output"
    with pytest.raises(RuntimeError, match="Original dependency licenses missing"):
        LICENSES.collect(ROOT, output, [Distribution(tmp_path, ("example.py",))], include_runtime=False)
    inventory = json.loads((output / "LICENSE-INVENTORY.json").read_text())
    assert inventory["missing"] == ["example-wheel"]
    with pytest.raises(RuntimeError, match="Incomplete"):
        LICENSES.verify(output)


def test_copied_notice_tamper_fails(tmp_path):
    (tmp_path / "LICENSE.txt").write_bytes(b"Original\n")
    output = tmp_path / "output"
    inventory = LICENSES.collect(ROOT, output, [Distribution(tmp_path, ("LICENSE.txt",))], include_runtime=False)
    item = inventory["components"][0]["files"][0]
    (output / item["path"]).write_bytes(b"Changed\n")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        LICENSES.verify(output)


@pytest.mark.parametrize("name", ("../LICENSE", "/LICENSE", "C:/LICENSE", "C:LICENSE", "..\\LICENSE"))
def test_inventory_never_trusts_escaping_paths(tmp_path, name):
    (tmp_path / "LICENSE-INVENTORY.json").write_text(
        json.dumps(
            {"schema_version": 1, "missing": [], "components": [{"files": [{"path": name, "sha256": "0" * 64}]}]}
        )
    )
    with pytest.raises(RuntimeError, match="Unsafe license inventory path"):
        LICENSES.verify(tmp_path)


def test_runtime_update_requires_license_update(tmp_path, monkeypatch):
    monkeypatch.setattr(LICENSES.platform, "python_version", lambda: "3.13.16")
    with pytest.raises(RuntimeError, match="Update pinned native license"):
        LICENSES.collect(ROOT, tmp_path, [], include_runtime=True)


def test_exact_flatbuffers_wheel_omission_has_original_tag_fallback(tmp_path):
    original = b"# Copyright 2014 Google Inc. All rights reserved.\n# Original wheel source\n"
    path = tmp_path / "flatbuffers/__init__.py"
    path.parent.mkdir()
    path.write_bytes(original)
    dist = Distribution(tmp_path, ("flatbuffers/__init__.py",))
    dist.metadata = {"Name": "flatbuffers"}
    dist.version = "25.12.19"
    output = tmp_path / "output"
    inventory = LICENSES.collect(ROOT, output, [dist], include_runtime=False)
    assert inventory["missing"] == []
    assert len(inventory["components"][0]["files"]) == 2
    assert (output / "licenses/flatbuffers/flatbuffers-init-original.txt").read_bytes() == original
    assert (output / "licenses/flatbuffers/FlatBuffers-25.12.19-LICENSE.txt").read_bytes() == (
        ROOT / "packaging/licenses/FlatBuffers-25.12.19-LICENSE.txt"
    ).read_bytes()
    LICENSES.verify(output)


def test_new_flatbuffers_version_cannot_reuse_unreviewed_fallback(tmp_path):
    dist = Distribution(tmp_path, ())
    dist.metadata = {"Name": "flatbuffers"}
    dist.version = "25.12.20"
    with pytest.raises(RuntimeError, match="Original dependency licenses missing"):
        LICENSES.collect(ROOT, tmp_path, [dist], include_runtime=False)


def test_pinned_original_sources_are_intact():
    resources = ROOT / "packaging/licenses"
    sources = json.loads((resources / "SOURCES.json").read_text())["files"]
    for name, entry in sources.items():
        assert entry["source"].startswith("https://")
        assert hashlib.sha256((resources / name).read_bytes()).hexdigest() == entry["sha256"]
