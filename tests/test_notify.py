import json
import subprocess
from unittest.mock import Mock

import pytest

from swu_checkin import notify


def _write_status(state_dir, *, code: int = 1, message: str = "签到成功") -> None:
    payload = {"date": "2026-09-17", "attempts": [{"code": code, "message": message}]}
    (state_dir / "status.json").write_text(json.dumps(payload), encoding="utf-8")


def test_notifier_requires_external_target(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys):
    _write_status(tmp_path)
    monkeypatch.setenv("SWUDK_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("SWUDK_NOTIFY_TARGET", raising=False)
    monkeypatch.setattr(notify, "today_shanghai", lambda: "2026-09-17")
    run = Mock()
    monkeypatch.setattr(notify.subprocess, "run", run)

    assert notify.main() == 2
    run.assert_not_called()
    assert "缺少 SWUDK_NOTIFY_TARGET" in capsys.readouterr().err


def test_notifier_timeout_does_not_mark_day_as_sent(monkeypatch: pytest.MonkeyPatch, tmp_path):
    _write_status(tmp_path)
    monkeypatch.setenv("SWUDK_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("SWUDK_NOTIFY_TARGET", "test-target")
    monkeypatch.setattr(notify, "today_shanghai", lambda: "2026-09-17")
    monkeypatch.setattr(notify.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("openclaw", 60)))

    assert notify.main() == 1
    assert not (tmp_path / "notified-2026-09-17").exists()
