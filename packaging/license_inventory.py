"""Preserve actual wheel notices and pinned native runtime license originals."""

import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
import sqlite3
import ssl
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath


def _safe_relative(name: str) -> bool:
    return (
        not PurePosixPath(name).is_absolute()
        and not PureWindowsPath(name).drive
        and "\\" not in name
        and ".." not in PurePosixPath(name).parts
    )


def _notice(path: Path) -> bool:
    return any(
        any(marker in part.lower() for marker in ("license", "copying", "copyright", "notice")) for part in path.parts
    )


def _record(source: Path, target: Path, output: Path, origin: str) -> dict[str, str]:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return {
        "path": target.relative_to(output).as_posix(),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "source": origin,
    }


def _pinned(root: Path, name: str) -> tuple[Path, dict[str, str]]:
    resources = root / "packaging/licenses"
    entry = json.loads((resources / "SOURCES.json").read_text(encoding="utf-8"))["files"][name]
    source = resources / name
    if hashlib.sha256(source.read_bytes()).hexdigest() != entry["sha256"]:
        raise RuntimeError("Pinned upstream license hash mismatch: " + name)
    return source, entry


def collect(root: Path, output: Path, distributions=None, *, include_runtime: bool = True) -> dict:
    """Fail when a distribution has no original notice; never synthesize license text."""
    output.mkdir(parents=True, exist_ok=True)
    components = []
    missing = []
    distributions = importlib.metadata.distributions() if distributions is None else distributions
    for dist in sorted(distributions, key=lambda item: item.metadata["Name"].lower()):
        name = dist.metadata["Name"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ValueError("Unsafe distribution name in license inventory")
        files = []
        for file in sorted(dist.files or (), key=str):
            relative = Path(str(file))
            if not _safe_relative(str(file)) or not _notice(relative):
                continue
            source = Path(dist.locate_file(file))
            if source.is_file():
                files.append(
                    _record(
                        source,
                        output / "licenses" / name / relative,
                        output,
                        f"installed wheel {name}=={dist.version}: {relative.as_posix()}",
                    )
                )
        if not files and (name.lower(), dist.version) == ("flatbuffers", "25.12.19"):
            # This exact wheel omits LICENSE. Preserve its release-tag original
            # and the actual wheel's copyright-bearing module without editing.
            source, entry = _pinned(root, "FlatBuffers-25.12.19-LICENSE.txt")
            files.append(_record(source, output / "licenses" / name / source.name, output, entry["source"]))
            copyright_file = Path(dist.locate_file("flatbuffers/__init__.py"))
            if not copyright_file.is_file() or b"Copyright 2014 Google Inc." not in copyright_file.read_bytes():
                raise RuntimeError("FlatBuffers wheel original copyright notice not found")
            files.append(
                _record(
                    copyright_file,
                    output / "licenses" / name / "flatbuffers-init-original.txt",
                    output,
                    "installed flatbuffers==25.12.19 wheel: flatbuffers/__init__.py",
                )
            )
        if not files:
            missing.append(name)
        components.append({"name": name, "version": dist.version, "files": files})
    if include_runtime:
        components.extend(_runtime(root, output))
    inventory = {
        "schema_version": 1,
        "components": components,
        "missing": missing,
        "python_changes": "No changes to CPython source; required runtime modules are frozen with PyInstaller.",
    }
    (output / "LICENSE-INVENTORY.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    if missing:
        raise RuntimeError("Original dependency licenses missing: " + ", ".join(missing))
    return inventory


def _runtime(root: Path, output: Path) -> list[dict]:
    if platform.python_version() != "3.13.15":
        raise RuntimeError("Update pinned native license sources before changing Python 3.13.15")
    import tkinter

    resources = root / "packaging/licenses"
    sources = json.loads((resources / "SOURCES.json").read_text(encoding="utf-8"))["files"]

    def original(name: str) -> dict[str, str]:
        source, entry = _pinned(root, name)
        return _record(source, output / "licenses/runtime" / name, output, entry["source"])

    python_files = [original("CPython-3.13.15-LICENSE.txt"), original("CPython-3.13.15-NOTICES.rst")]
    installed = next(
        (
            Path(sys.base_prefix) / name
            for name in ("LICENSE.txt", "LICENSE")
            if (Path(sys.base_prefix) / name).is_file()
        ),
        None,
    )
    if installed is not None:
        python_files.append(
            _record(installed, output / "PYTHON-LICENSE.txt", output, "original installed Python 3.13.15 license")
        )
    else:
        python_files.append(
            _record(
                resources / "CPython-3.13.15-LICENSE.txt",
                output / "PYTHON-LICENSE.txt",
                output,
                sources["CPython-3.13.15-LICENSE.txt"]["source"],
            )
        )
    interpreter = tkinter.Tcl()
    tcl_version = interpreter.eval("info patchlevel")
    tcl_library = Path(interpreter.eval("info library"))
    tk_script = tcl_library.parent / "tk8.6/tk.tcl"
    match = re.search(r"package require -exact Tk\s+([0-9.]+)", tk_script.read_text(encoding="utf-8"))
    if match is None:
        raise RuntimeError("Cannot identify bundled Tk patch version")
    tk_version = match.group(1)
    if tcl_version not in {"8.6.15", "8.6.18"} or tk_version not in {"8.6.15", "8.6.18"}:
        raise RuntimeError("Update pinned Tcl/Tk license sources before changing native runtime")
    if not ssl.OPENSSL_VERSION.startswith("OpenSSL 3.0.21 ") or sqlite3.sqlite_version != "3.50.4":
        raise RuntimeError("Update pinned OpenSSL/SQLite notices before changing native runtime")
    components = [
        {"name": "CPython", "version": platform.python_version(), "files": python_files},
        {"name": "Tcl", "version": tcl_version, "files": [original(f"Tcl-{tcl_version}-LICENSE.txt")]},
        {"name": "Tk", "version": tk_version, "files": [original(f"Tk-{tk_version}-LICENSE.txt")]},
        {"name": "OpenSSL (Python runtime)", "version": "3.0.21", "files": [original("OpenSSL-3.0.21-LICENSE.txt")]},
        {
            "name": "SQLite (Python runtime)",
            "version": sqlite3.sqlite_version,
            "files": [original("SQLite-3.50.4-LICENSE.md")],
        },
    ]
    if sys.platform == "darwin":
        # These exact versions are selected by CPython v3.13.15's official
        # Mac/BuildScript/build-installer.py. Wheel-bundled copies retain their
        # independent ThirdPartyNotices in their component files above.
        components.extend(
            [
                {
                    "name": "liblzma (official macOS Python runtime)",
                    "version": "5.2.3",
                    "files": [original("XZ-5.2.3-COPYING.txt")],
                },
                {
                    "name": "NCurses (official macOS Python runtime)",
                    "version": "6.5",
                    "files": [original("NCurses-6.5-COPYING.txt")],
                },
            ]
        )
    return components


def verify(output: Path) -> None:
    """Check collected files before freezing them into signed application resources."""
    inventory = json.loads((output / "LICENSE-INVENTORY.json").read_text(encoding="utf-8"))
    if inventory["schema_version"] != 1 or inventory["missing"] or not inventory["components"]:
        raise RuntimeError("Incomplete native license inventory")
    for component in inventory["components"]:
        if not component["files"]:
            raise RuntimeError("Missing original license files")
        for item in component["files"]:
            path = Path(item["path"])
            if not _safe_relative(item["path"]):
                raise RuntimeError("Unsafe license inventory path")
            if hashlib.sha256((output / path).read_bytes()).hexdigest() != item["sha256"]:
                raise RuntimeError("Bundled license checksum mismatch")
