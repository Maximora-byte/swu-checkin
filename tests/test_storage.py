import json
import stat

import pytest

from swu_checkin.status import CheckinStatus
from swu_checkin.storage import StatusStorageError, load_run_status, record_run_status


def test_storage_atomically_replaces_with_0640_and_caps_attempts(monkeypatch, tmp_path):
    status_file = tmp_path / "status.json"
    replacements = []
    real_replace = __import__("os").replace

    def tracked_replace(source, target):
        replacements.append((source, target))
        real_replace(source, target)

    monkeypatch.setattr("swu_checkin.storage.os.replace", tracked_replace)
    for _ in range(11):
        record_run_status(str(status_file), CheckinStatus.DATA_ERROR)
    record_run_status(str(status_file), CheckinStatus.SUCCESS)

    payload = json.loads(status_file.read_text(encoding="utf-8"))
    assert len(payload["attempts"]) == 10
    assert payload["attempts"][-1]["code"] == 1
    assert payload["successful"] is True
    assert stat.S_IMODE(status_file.stat().st_mode) == 0o640
    assert len(replacements) == 12
    assert all(str(source).startswith(str(tmp_path / ".status.")) for source, _target in replacements)


def test_load_status_returns_only_validated_non_sensitive_fields(tmp_path):
    status_file = tmp_path / "status.json"
    record_run_status(str(status_file), CheckinStatus.SUCCESS)

    status = load_run_status(str(status_file))

    assert status is not None
    assert status.successful is True
    assert status.attempts[-1].code == 1
    assert status.attempts[-1].message == "签到成功"


def test_load_status_rejects_unexpected_fields(tmp_path):
    status_file = tmp_path / "status.json"
    status_file.write_text(
        json.dumps({"date": "2026-09-19", "attempts": [], "successful": False, "token": "unexpected"}),
        encoding="utf-8",
    )

    with pytest.raises(StatusStorageError):
        load_run_status(str(status_file))


@pytest.mark.parametrize("previous", ["[]", "null", "42", '"text"', "true", "{broken", "{}"])
def test_record_status_recovers_from_corrupt_or_wrong_shape_json(tmp_path, previous):
    status_file = tmp_path / "status.json"
    status_file.write_text(previous, encoding="utf-8")

    record_run_status(str(status_file), CheckinStatus.SUCCESS)

    status = load_run_status(str(status_file))
    assert status is not None
    assert status.successful
    assert len(status.attempts) == 1
    assert status.attempts[0].code == CheckinStatus.SUCCESS


def test_record_status_discards_invalid_utf8_history(tmp_path):
    status_file = tmp_path / "status.json"
    status_file.write_bytes(b"\xff\xfe")
    with pytest.raises(StatusStorageError):
        load_run_status(str(status_file))

    record_run_status(str(status_file), CheckinStatus.DATA_ERROR)

    status = load_run_status(str(status_file))
    assert status is not None
    assert not status.successful
    assert len(status.attempts) == 1


def test_record_status_discards_unvalidated_history_fields(tmp_path):
    status_file = tmp_path / "status.json"
    record_run_status(str(status_file), CheckinStatus.DATA_ERROR)
    payload = json.loads(status_file.read_text(encoding="utf-8"))
    payload["attempts"][0]["message"] = "unexpected-private-data"
    status_file.write_text(json.dumps(payload), encoding="utf-8")

    record_run_status(str(status_file), CheckinStatus.SUCCESS)

    status = load_run_status(str(status_file))
    assert status is not None
    assert len(status.attempts) == 1
    assert "unexpected-private-data" not in status_file.read_text(encoding="utf-8")
