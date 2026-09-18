import importlib
import subprocess
import sys
from unittest.mock import Mock

import pytest

import swu_checkin
from swu_checkin.check_in import check_in, check_in_with_retry, probe_check_in
from swu_checkin.models import CheckinResult
from swu_checkin.status import CheckinStatus

check_in_module = importlib.import_module("swu_checkin.check_in")


def test_legacy_check_in_returns_status(monkeypatch: pytest.MonkeyPatch):
    check_in_once = Mock(return_value=CheckinStatus.SUCCESS)
    monkeypatch.setattr(check_in_module.CheckinService, "check_in_once", check_in_once)

    result = check_in("student", "password", 12)

    assert result is CheckinStatus.SUCCESS
    assert swu_checkin.check_in is check_in
    check_in_once.assert_called_once_with("student", "password")


def test_legacy_probe_returns_status(monkeypatch: pytest.MonkeyPatch):
    probe_once = Mock(return_value=CheckinStatus.PROBE_PENDING)
    monkeypatch.setattr(check_in_module.CheckinService, "probe_once", probe_once)

    assert probe_check_in("student", "password") is CheckinStatus.PROBE_PENDING


def test_legacy_retry_returns_status(monkeypatch: pytest.MonkeyPatch):
    structured = CheckinResult.from_status(
        CheckinStatus.ON_LEAVE,
        attempts=1,
        duration_ms=0,
        mode="checkin",
    )
    run = Mock(return_value=structured)
    monkeypatch.setattr(check_in_module, "run_checkin_result", run)

    result = check_in_with_retry("student", "password", max_attempts=2, retry_delay=3)

    assert result is CheckinStatus.ON_LEAVE
    run.assert_called_once_with(
        "student",
        "password",
        10,
        max_attempts=2,
        retry_delay=3,
    )


def test_legacy_module_entrypoint_accepts_new_cli_arguments():
    completed = subprocess.run(
        [sys.executable, "-m", "swu_checkin.check_in", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "--json" in completed.stdout
    assert "--probe" in completed.stdout
