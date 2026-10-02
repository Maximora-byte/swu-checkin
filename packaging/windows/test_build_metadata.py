"""Offline checks for the packaging provenance/checksum helper."""

import hashlib
import importlib.util
import json
from pathlib import Path

HELPER_PATH = Path(__file__).with_name("build_metadata.py")
spec = importlib.util.spec_from_file_location("build_metadata", HELPER_PATH)
assert spec is not None and spec.loader is not None
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def test_manifest_sorted_stable_and_excludes_itself(tmp_path):
    (tmp_path / "z.txt").write_bytes(b"z")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_bytes(b"a")
    output = tmp_path / "SHA256SUMS.txt"
    helper.manifest(tmp_path, output)
    expected = f"{hashlib.sha256(b'a').hexdigest()}  sub/a.txt\n{hashlib.sha256(b'z').hexdigest()}  z.txt\n"
    assert output.read_text(encoding="utf-8") == expected
    helper.manifest(tmp_path, output)
    assert output.read_text(encoding="utf-8") == expected


def test_metadata_records_dirty_source_without_contents(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    (root / "uv.lock").write_bytes(b"locked")
    (root / "example.py").write_bytes(b"private source content")
    python_home = tmp_path / "python"
    python_home.mkdir()
    (python_home / "LICENSE.txt").write_text("Python license", encoding="utf-8")
    monkeypatch.setattr(helper.sys, "base_prefix", str(python_home))
    monkeypatch.setattr(helper.importlib.metadata, "distributions", lambda: [])
    # License collection is independently exercised against original wheel
    # notices. This source-provenance fixture has no installed native runtime.
    monkeypatch.setattr(
        helper,
        "collect",
        lambda root, output, distributions: (output / "PYTHON-LICENSE.txt").write_text(
            (python_home / "LICENSE.txt").read_text(encoding="utf-8"), encoding="utf-8"
        ),
    )
    monkeypatch.setattr(helper, "verify", lambda output: None)
    monkeypatch.setattr(helper, "git", lambda root, *args: "abc123" if args[0] == "rev-parse" else " M example.py")
    monkeypatch.setattr(helper.subprocess, "check_output", lambda *args, **kwargs: b"example.py\0uv.lock\0")
    output = tmp_path / "metadata"
    helper.metadata(root, output)
    info = json.loads((output / "BUILD-INFO.json").read_text(encoding="utf-8"))
    assert info["application_version"] == "1.2.3"
    assert info["source_commit"] == "abc123"
    assert info["source_dirty"] is True
    assert info["uv_lock_sha256"] == hashlib.sha256(b"locked").hexdigest()
    assert "private source content" not in json.dumps(info)
    assert (output / "PYTHON-LICENSE.txt").read_text(encoding="utf-8") == "Python license"
    first_hash = info["source_tree_sha256"]
    (root / "example.py").write_bytes(b"changed")
    helper.metadata(root, output)
    info = json.loads((output / "BUILD-INFO.json").read_text(encoding="utf-8"))
    assert info["source_tree_sha256"] != first_hash
