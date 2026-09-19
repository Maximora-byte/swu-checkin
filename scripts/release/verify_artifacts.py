"""Validate release artifacts through clean wheel and sdist installations."""

from __future__ import annotations

import argparse
import os
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

_FORBIDDEN_PARTS = frozenset({".git", ".pytest_cache", ".venv", "__pycache__", "secrets"})
_FORBIDDEN_NAMES = frozenset({".env", "auth-token-cache", "credentials.env", "notify.env", "status.json"})
_FORBIDDEN_SUFFIXES = frozenset({".key", ".pem"})


def _single_artifact(dist: Path, pattern: str, label: str) -> Path:
    matches = sorted(dist.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {label}, found {len(matches)}")
    return matches[0].resolve()


def _verify_archive_members(artifact: Path, members: list[str]) -> None:
    for name in members:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError(f"unsafe archive path in {artifact.name}")
        if (
            _FORBIDDEN_PARTS.intersection(path.parts)
            or path.name in _FORBIDDEN_NAMES
            or path.suffix in _FORBIDDEN_SUFFIXES
        ):
            raise RuntimeError(f"forbidden private artifact content in {artifact.name}")


def _verify_archives(wheel: Path, sdist: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise RuntimeError(f"wheel member failed CRC validation: {bad_member}")
        _verify_archive_members(wheel, archive.namelist())
    with tarfile.open(sdist, mode="r:gz") as archive:
        _verify_archive_members(sdist, archive.getnames())


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
