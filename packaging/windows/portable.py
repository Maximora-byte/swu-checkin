"""Package the existing frozen onedir app as a self-contained, extractable ZIP."""

import argparse
import hashlib
import os
import re
import time
import zipfile
from pathlib import Path

ROOT_NAME = "SWUCheckin"
MANIFEST = "SHA256SUMS.txt"
RESERVED = {MANIFEST, "README-PORTABLE.txt", "BUILD-INFO.json", "TOOLCHAIN.txt", "Tcl-8.6.15-LICENSE.txt"}


def create_portable(app: Path, output: Path, resources: Path) -> None:
    """Do not mutate the installer input or add any installer/bootstrap script."""
    required = ("SWUCheckin.exe", "_internal/build-info/BUILD-INFO.json", "_internal/build-info/TOOLCHAIN.txt")
    if any(not (app / name).is_file() for name in required):
        raise ValueError("A complete frozen application with provenance is required")
    if output.resolve().is_relative_to(app.resolve()):
        raise ValueError("Portable archive must be outside the application directory")
    files: dict[str, Path] = {}
    for path in sorted(app.rglob("*")):
        if path.is_symlink():
            raise ValueError("Portable archives cannot contain symbolic links")
        if not path.is_file():
            continue
        name = path.relative_to(app).as_posix()
        if name in RESERVED:
            continue
        # These names cannot be extracted consistently by Windows Explorer.
        if any(
            re.search(r'[<>:"\\|?*\x00-\x1f]', part) or part.endswith((".", " "))
            for part in path.relative_to(app).parts
        ):
            raise ValueError("Portable archive contains a non-Windows filename")
        files[name] = path
    files.update(
        {
            "README-PORTABLE.txt": resources / "README-PORTABLE.txt",
            "BUILD-INFO.json": app / "_internal/build-info/BUILD-INFO.json",
            "TOOLCHAIN.txt": app / "_internal/build-info/TOOLCHAIN.txt",
            "Tcl-8.6.15-LICENSE.txt": resources / "licenses/Tcl-8.6.15-LICENSE.txt",
        }
    )
    if any(not path.is_file() for path in files.values()):
        raise ValueError("Portable instructions, license and provenance must be present")
    # ZIP timestamps have a 1980 lower bound. SOURCE_DATE_EPOCH comes from git.
    epoch = max(int(os.environ.get("SOURCE_DATE_EPOCH", "315532800")), 315532800)
    timestamp = time.gmtime(epoch)[:6]
    lines = []
    temporary = output.with_suffix(".zip.tmp")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, path in sorted(files.items()):
                data = path.read_bytes()
                lines.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
                _write(archive, name, data, timestamp)
            _write(archive, MANIFEST, ("\n".join(lines) + "\n").encode(), timestamp)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def _write(archive: zipfile.ZipFile, name: str, data: bytes, timestamp: tuple[int, ...]) -> None:
    entry = zipfile.ZipInfo(f"{ROOT_NAME}/{name}", date_time=timestamp)
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.create_system = 0  # Regular Windows files, no Unix symlinks or mode bits.
    entry.external_attr = 0x20
    archive.writestr(entry, data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    create_portable(args.app.resolve(), args.output.resolve(), Path(__file__).resolve().parent)


if __name__ == "__main__":
    main()
