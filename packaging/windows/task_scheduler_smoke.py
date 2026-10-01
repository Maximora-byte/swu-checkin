"""Harmless task registration smoke, only on disposable GitHub Windows runners."""

import csv
import io
import os
import re
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PureWindowsPath
from uuid import uuid4
from xml.etree import ElementTree as ET

from swu_checkin.desktop_backend import TASK_NS, DesktopBackend, task_xml

NS = {"t": TASK_NS}


def harmless_xml(command: str, sid: str, now: datetime) -> bytes:
    # Use the production generator and byte encoding. Change only the action
    # arguments; production timing/modes are never registered by this smoke.
    root = ET.fromstring(task_xml(command, sid, now + timedelta(days=7)))
    arguments = root.find(".//t:Exec/t:Arguments", NS)
    assert arguments is not None
    arguments.text = "/d /c exit 0"
    data = ET.tostring(root, encoding="utf-16", xml_declaration=True)
    validate_xml(ET.fromstring(data), command, sid, now)
    return data


def validate_xml(root: ET.Element, command: str, sid: str, now: datetime) -> None:
    expected = {
        "Command": command,
        "Arguments": "/d /c exit 0",
        "WorkingDirectory": str(PureWindowsPath(command).parent),
        "UserId": sid,
        "RunLevel": "LeastPrivilege",
        "LogonType": "InteractiveToken",
        "StartWhenAvailable": "false",
    }
    for field, value in expected.items():
        if root.findtext(f".//t:{field}", namespaces=NS) != value:
            print("Harmless task property mismatch: " + field)
            raise RuntimeError("Harmless task property verification failed")
    boundaries = root.findall(".//t:StartBoundary", NS)
    if len(boundaries) != 2 or any(
        datetime.fromisoformat(node.text or "") <= now + timedelta(days=6) for node in boundaries
    ):
        raise RuntimeError("Harmless task trigger is not safely in the future")


def run_smoke() -> None:
    if (
        sys.platform != "win32"
        or os.getenv("GITHUB_ACTIONS") != "true"
        or os.getenv("RUNNER_ENVIRONMENT") != "github-hosted"
        or not os.getenv("RUNNER_TEMP")
    ):
        raise RuntimeError("Task smoke requires a disposable GitHub-hosted Windows runner")
    name = "SWUCheckin-CI-" + uuid4().hex
    if re.fullmatch(r"SWUCheckin-CI-[0-9a-f]{32}", name) is None:
        raise RuntimeError("Unsafe smoke task name")
    command = str(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe")
    now = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix="swu-task-smoke-", dir=os.environ["RUNNER_TEMP"]) as directory:
        backend = DesktopBackend(Path(directory))
        if backend._task_exists(name):
            raise RuntimeError("Random task name already exists; refusing to overwrite")
        identity = backend._system_command("whoami.exe", ["/user", "/fo", "csv", "/nh"])
        if identity.returncode:
            raise RuntimeError("Unable to resolve smoke task user")
        sid = next(csv.reader(io.StringIO(identity.stdout)))[1]
        if re.fullmatch(r"S-1-[0-9-]+", sid) is None:
            raise RuntimeError("Invalid smoke task user")
        path = Path(directory) / "task.xml"
        path.write_bytes(harmless_xml(command, sid, now))
        create_attempted = False
        removed = False
        try:
            print("Harmless task stage: register")
            create_attempted = True
            created = backend._system_command("schtasks.exe", ["/Create", "/TN", name, "/XML", str(path), "/F"])
            if created.returncode or not backend._task_exists(name):
                raise RuntimeError("Harmless task registration failed")
            print("Harmless task stage: query registered XML")
            exported = backend._system_command("schtasks.exe", ["/Query", "/TN", name, "/XML"])
            if exported.returncode:
                raise RuntimeError("Harmless task export failed")
            validate_xml(ET.fromstring(exported.stdout), command, sid, now)
            print("Harmless task stage: delete")
            deleted = backend._system_command("schtasks.exe", ["/Delete", "/TN", name, "/F"])
            if deleted.returncode or backend._task_exists(name):
                raise RuntimeError("Harmless task deletion verification failed")
            removed = True
            print("Harmless Task Scheduler smoke passed: registered, queried, properties verified, deleted, absent")
        finally:
            # Only the fresh random name whose absence this invocation checked.
            # Never enumerate/delete production or other users' tasks.
            if create_attempted and not removed:
                try:
                    backend._system_command("schtasks.exe", ["/Delete", "/TN", name, "/F"])
                    if backend._task_exists(name):
                        raise RuntimeError("Smoke task cleanup not confirmed")
                except Exception:
                    raise RuntimeError("Smoke task cleanup not confirmed; discard runner") from None


if __name__ == "__main__":
    try:
        run_smoke()
    except Exception:
        # No raw task XML, user identity, paths, stdout/stderr or exception text.
        print("Harmless Task Scheduler smoke failed; see fixed verification stage", file=sys.stderr)
        raise SystemExit(1) from None
