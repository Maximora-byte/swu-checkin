"""Real Git routing regressions; unknown paths and identities retain full CI."""

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ci_preview_scope.py"
SPEC = importlib.util.spec_from_file_location("ci_preview_scope", SCRIPT)
assert SPEC and SPEC.loader
scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scope)


@pytest.fixture
def repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def git(*args):
        return subprocess.check_output(["git", *args], text=True, encoding="utf-8").strip()

    git("init", "-q")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    for name in [*scope.PREVIEWS, "src/code.py"]:
        path = Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("before", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    event = {"pull_request": {"user": {"login": "imgbot[bot]", "id": 31301654, "type": "Bot"}, "base": {"sha": base}}}

    def finish():
        git("add", ".")
        git("commit", "--allow-empty", "-qm", "head")
        event["pull_request"]["head"] = {"sha": git("rev-parse", "HEAD")}
        return event

    return event, finish


def test_official_existing_preview_only(repository):
    _, finish = repository
    Path(next(iter(scope.PREVIEWS))).write_text("after", encoding="utf-8")
    assert scope.preview_only("pull_request", finish())


@pytest.mark.parametrize(
    "case", ["mixed", "renamed", "new", "deleted", "empty", "wrong-id", "human", "push", "bad-sha"]
)
def test_other_changes_keep_full_quality_checks(repository, case):
    event, finish = repository
    path = Path(next(iter(scope.PREVIEWS)))
    if case != "empty":
        path.write_text("after", encoding="utf-8")
    if case == "mixed":
        Path("src/code.py").write_text("changed", encoding="utf-8")
    elif case == "renamed":
        os.replace("src/code.py", "android/artwork/new.png")
    elif case == "new":
        Path("android/artwork/new.png").write_text("new", encoding="utf-8")
    elif case == "deleted":
        path.unlink()
    elif case == "wrong-id":
        event["pull_request"]["user"]["id"] = 1
    elif case == "human":
        event["pull_request"]["user"]["type"] = "User"
    event = finish()
    if case == "bad-sha":
        event["pull_request"]["head"]["sha"] = "unknown"
    assert not scope.preview_only("push" if case == "push" else "pull_request", event)
