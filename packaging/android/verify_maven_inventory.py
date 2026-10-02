"""Reject changed resolved Gradle runtime inputs until their notices are reviewed."""

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "android/app/src/main/assets/licenses/inventory.json"
COORDINATE = re.compile(r"(?:\+---|\\---) ([\w.-]+):([\w.-]+)(?::([^ ]+))?(?: -> ([^ ]+))?")


def resolved_coordinates(report: str) -> set[str]:
    if "releaseRuntimeClasspath" not in report or "BUILD SUCCESSFUL" not in report:
        raise ValueError("incomplete release runtime dependency report")
    result = set()
    for line in report.splitlines():
        if "(c)" in line:
            continue  # Constraints are not dependencies.
        match = COORDINATE.search(line)
        if not match:
            continue
        group, artifact, version, selected = match.groups()
        version = selected or version
        if not version or "FAILED" in line:
            raise ValueError("unresolved runtime dependency")
        result.add(f"{group}:{artifact}:{version}")
    if not result:
        raise ValueError("empty runtime dependency report")
    return result


def verify(report: str) -> int:
    actual = resolved_coordinates(report)
    expected = {item["coordinate"] for item in json.loads(INVENTORY.read_text(encoding="utf-8"))["maven_components"]}
    if actual != expected:
        raise ValueError(
            f"unreviewed Maven dependencies; added={sorted(actual - expected)}, removed={sorted(expected - actual)}"
        )
    return len(actual)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    arguments = parser.parse_args()
    print(
        json.dumps({"reviewed_maven_components": verify(arguments.report.read_text(encoding="utf-8"))}, sort_keys=True)
    )
