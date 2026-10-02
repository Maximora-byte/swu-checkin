"""Real Android bridge/core with synthetic transport and no school traffic."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from swu_checkin.runtime_lock import RuntimeLock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


load("android_client", "android/app/src/main/python/android_client.py")
demo = load("android_test_demo", "android/app/src/androidTest/assets/android_demo.py")


class Broker:
    cancelled = False

    def isCancelled(self):
        return self.cancelled


@pytest.fixture
def adapter(tmp_path):
    broker = Broker()
    client = demo.make_android_demo(broker, str(tmp_path / "manual.lock"), provider=lambda image: "Ab12")
    return client, client.demo_backend, broker


def run(adapter, mode, confirmed=False, **kwargs):
    return json.loads(adapter.run(mode, demo.USER, kwargs.get("password", demo.SECRET), confirmed))


def test_query_and_diagnose_never_submit_and_no_token_file(adapter, tmp_path):
    client, backend, _broker = adapter
    assert run(client, "probe")["status"] == "probe_pending"
    assert all(run(client, "diagnose")["checks"].values())
    assert backend.submissions == 0
    assert {path.name for path in tmp_path.iterdir()} == {"manual.lock"}
    assert client.tokens.get(demo.USER).student_id == demo.USER


def test_submit_needs_confirmation_and_confirms_server_state(adapter):
    client, backend, _broker = adapter
    assert run(client, "checkin")["error"] == "confirmation_required"
    assert backend.submissions == 0
    assert run(client, "probe")["status"] == "probe_pending"
    assert run(client, "checkin", True)["status"] == "success"
    assert backend.submissions == 1
    assert run(client, "checkin", True)["status"] == "already_checked_in"
    assert backend.submissions == 1


def test_cancel_after_read_before_submit_cannot_send(adapter):
    client, backend, broker = adapter
    original = backend.get_dormitory_info

    def cancel():
        broker.cancelled = True
        return original()

    backend.get_dormitory_info = cancel
    assert run(client, "checkin", True)["error"] == "cancelled"
    assert backend.submissions == 0


def test_captcha_cancel_stops_before_authentication(adapter):
    client, backend, _broker = adapter
    client._provider = lambda image: None
    assert run(client, "probe")["status"] == "login_failed"
    assert backend.submissions == 0
    assert client.tokens.get(demo.USER) is None


def test_cached_token_cannot_cross_account_or_credential_change(adapter):
    client, backend, _broker = adapter
    assert run(client, "probe")["status"] == "probe_pending"
    assert run(client, "probe", password="different-password")["error"] == "operation_failed"
    assert client.tokens.get(demo.USER) is None
    backend.student = "different-student"
    assert run(client, "checkin", True)["status"] == "data_error"
    assert backend.submissions == 0


def test_cross_process_ownership_blocks_operation(adapter):
    client, backend, _broker = adapter
    with RuntimeLock(client.lock_path):
        assert run(client, "checkin", True)["error"] == "busy"
    assert backend.submissions == 0


def test_failure_never_returns_exception_secrets(adapter):
    client, backend, _broker = adapter

    def fail():
        raise RuntimeError("synthetic-password bearer-sensitive-token https://private.example")

    backend.get_student_id = fail
    result = run(client, "probe")
    assert result == {"schema_version": 1, "error": "operation_failed"}


def test_absent_task_is_not_submitted(adapter):
    client, backend, _broker = adapter
    backend.state = "no_task"
    assert run(client, "checkin", True)["status"] == "no_task"
    assert backend.submissions == 0
