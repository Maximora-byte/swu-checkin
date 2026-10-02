"""Validate release artifacts through clean wheel and sdist installations."""

from __future__ import annotations

import argparse
import os
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

_FORBIDDEN_PARTS = frozenset({".git", ".pytest_cache", ".venv", "__pycache__", "secrets"})
_FORBIDDEN_NAMES = frozenset({".env", "auth-token-cache", "credentials.env", "notify.env", "status.json"})
_FORBIDDEN_SUFFIXES = frozenset({".key", ".pem"})


def _single_artifact(dist: Path, pattern: str, label: str) -> Path:
    matches = sorted(dist.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {label}, found {len(matches)}")
    return matches[0].resolve()


def _verify_archive_members(artifact: Path, members: list[str]) -> None:
    canonical_names: set[str] = set()
    for name in members:
        path = safe_archive_path(artifact, name)
        canonical = str(path).casefold()
        if canonical in canonical_names:
            raise RuntimeError(f"duplicate portable archive path in {artifact.name}")
        canonical_names.add(canonical)
        parts = tuple(part.casefold() for part in path.parts)
        if (
            _FORBIDDEN_PARTS.intersection(parts)
            or path.name.casefold() in _FORBIDDEN_NAMES
            or path.suffix.casefold() in _FORBIDDEN_SUFFIXES
        ):
            raise RuntimeError(f"forbidden private artifact content in {artifact.name}")


def safe_archive_path(artifact: Path, name: str) -> PurePosixPath:
    """Check portable archive names independently of the verifier's host OS.

    Wheels and sdists use POSIX separators. Reject Windows roots, drive-relative
    names and alternate separators too: those acquire different meanings when an
    archive is opened on Windows. Colons also create NTFS alternate data streams.
    """
    path = PurePosixPath(name)
    windows_path = PureWindowsPath(name)
    if (
        not name
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
        or "\\" in name
        or ":" in name
        or path.is_absolute()
        or windows_path.drive
        or windows_path.root
        or ".." in path.parts
        or path == PurePosixPath(".")
        or any(part.endswith((".", " ")) for part in path.parts)
    ):
        raise RuntimeError(f"unsafe archive path in {artifact.name}")
    return path


def _verify_archives(wheel: Path, sdist: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise RuntimeError(f"wheel member failed CRC validation: {bad_member}")
        _verify_archive_members(wheel, archive.namelist())
        if any((entry.external_attr >> 16) & 0o170000 == 0o120000 for entry in archive.infolist()):
            raise RuntimeError(f"wheel contains symbolic links: {wheel.name}")
    with tarfile.open(sdist, mode="r:gz") as archive:
        _verify_archive_members(sdist, archive.getnames())
        if any(not (entry.isfile() or entry.isdir()) for entry in archive.getmembers()):
            raise RuntimeError(f"sdist contains links or special files: {sdist.name}")


def _smoke_install(artifact: Path, expected_version: str, uv: str, label: str) -> None:
    with tempfile.TemporaryDirectory(prefix=f"swu-checkin-{label}-smoke-") as temp:
        root = Path(temp)
        venv = root / "venv"
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["EXPECTED_VERSION"] = expected_version
        subprocess.run(
            [uv, "venv", str(venv), "--python", "3.13"],
            cwd=root,
            env=environment,
            check=True,
        )
        scripts = venv / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        cli = scripts / ("swu-checkin.exe" if os.name == "nt" else "swu-checkin")
        subprocess.run(
            [uv, "pip", "install", "--python", str(python), str(artifact)],
            cwd=root,
            env=environment,
            check=True,
        )
        subprocess.run([str(cli), "--help"], cwd=root, env=environment, check=True)
        subprocess.run([str(cli), "status", "--help"], cwd=root, env=environment, check=True)
        subprocess.run(
            [
                str(python),
                "-c",
                (
                    "import importlib.metadata, os, swu_checkin; "
                    "expected = os.environ['EXPECTED_VERSION']; "
                    "assert swu_checkin.__version__ == expected; "
                    "assert importlib.metadata.version('swu-checkin') == expected"
                ),
            ],
            cwd=root,
            env=environment,
            check=True,
        )


def verify_artifacts(dist: Path, expected_version: str, uv: str) -> None:
    wheel = _single_artifact(dist, "*.whl", "wheel")
    sdist = _single_artifact(dist, "*.tar.gz", "sdist")
    _verify_archives(wheel, sdist)
    _smoke_install(wheel, expected_version, uv, "wheel")
    _smoke_install(sdist, expected_version, uv, "sdist")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--uv", default="uv")
    args = parser.parse_args()
    verify_artifacts(args.dist, args.expected_version, args.uv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
