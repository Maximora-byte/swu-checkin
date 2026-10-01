"""Create stable build provenance, dependency licenses and checksum manifests."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def metadata(root: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    distributions = sorted(importlib.metadata.distributions(), key=lambda d: d.metadata["Name"].lower())
    source_hash = hashlib.sha256()
    names = (
        subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
        )
        .decode()
        .split("\0")
    )
    for name in sorted(set(filter(None, names))):
        path = root / name
        if path.is_file():
            source_hash.update(name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    info = {
        "application_version": tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
            "version"
        ],
        "source_commit": git(root, "rev-parse", "HEAD"),
        "source_dirty": bool(git(root, "status", "--porcelain")),
        "source_tree_sha256": source_hash.hexdigest(),
        "uv_lock_sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "dependencies": {d.metadata["Name"]: d.version for d in distributions},
    }
    (output / "BUILD-INFO.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Preserve distribution license/notice files with their original relative
    # paths; dist-info metadata is also included recursively by the spec.
    for dist in distributions:
        destination = output / "licenses" / dist.metadata["Name"]
        for file in dist.files or ():
            if any(part.lower().startswith(("license", "copying", "notice")) for part in file.parts):
                source = Path(dist.locate_file(file))
                if source.is_file() and ".." not in file.parts:
                    target = destination / str(file)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
    for name in ("LICENSE.txt", "LICENSE"):
        source = Path(sys.base_prefix) / name
        if source.is_file():
            shutil.copyfile(source, output / "PYTHON-LICENSE.txt")
            break
    else:
        raise RuntimeError("Python license not found; use the official Python Windows distribution")


def manifest(root: Path, output: Path) -> None:
    lines = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.resolve() != output.resolve():
            lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("metadata", "manifest"))
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.mode == "metadata":
        metadata(args.root.resolve(), args.output.resolve())
    else:
        manifest(args.root.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
