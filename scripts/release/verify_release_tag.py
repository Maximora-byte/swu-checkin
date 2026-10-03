"""Verify that a release tag exactly matches the project version."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path


def project_version(pyproject: Path) -> str:
    with pyproject.open("rb") as source:
        payload = tomllib.load(source)
    project = payload.get("project")
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml is missing [project]")
    version = project.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("pyproject.toml project.version is invalid")
    return version


def verify_release_tag(tag: str, version: str) -> None:
    if not tag.startswith("v") or tag[1:] != version:
        raise ValueError(f"release tag {tag!r} does not match project version {version!r}")


def release_channel(pyproject: Path) -> str:
    with pyproject.open("rb") as source:
        payload = tomllib.load(source)
    channel = payload.get("tool", {}).get("swu-checkin", {}).get("release", {}).get("channel", "prerelease")
    if channel not in ("stable", "prerelease"):
        raise ValueError("release channel must be stable or prerelease")
    return channel


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--tag", help="release tag such as v1.1.0")
    parser.add_argument("--channel", action="store_true", help="print the validated release channel")
    args = parser.parse_args()
    try:
        version = project_version(args.pyproject)
        channel = release_channel(args.pyproject)
        if args.tag is not None:
            verify_release_tag(args.tag, version)
    except ValueError as error:
        parser.error(str(error))
    print(channel if args.channel else version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
