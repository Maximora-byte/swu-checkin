from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, call

import pytest

SCRIPT = Path(__file__).parents[1] / "deploy" / "swu-checkin-set-credentials.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("swu_checkin_set_credentials", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("content", "valid"),
    [
        ("", False),
        ('SWUDK_NOTIFY_CHANNEL="telegram"\n', False),
        ("SWUDK_NOTIFY_TARGET=\n", False),
        ('SWUDK_NOTIFY_TARGET="   "\n', False),
        ('  SWUDK_NOTIFY_TARGET = "valid-target"  \n', True),
        ("SWUDK_NOTIFY_TARGET=valid-target\n", True),
        ("# comment\n\nSWUDK_NOTIFY_TARGET=valid-target # comment\n", True),
        ('SWUDK_NOTIFY_TARGET="unterminated\n', False),
        ("this is not an assignment\nSWUDK_NOTIFY_TARGET=valid-target\n", False),
    ],
)
def test_validate_notify_config(tmp_path: Path, content: str, valid: bool) -> None:
    module = _load_script()
    notify_file = tmp_path / "notify.env"
    notify_file.write_text(content, encoding="utf-8")

    assert module._validate_notify_config(notify_file) is valid


def test_validate_notify_config_fails_closed_on_read_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_script()
    notify_file = tmp_path / "notify.env"
    notify_file.write_text('SWUDK_NOTIFY_TARGET="valid-target"\n', encoding="utf-8")
    original_read_text = Path.read_text

    def deny_notify_file(path: Path, *args, **kwargs) -> str:
        if path == notify_file:
            raise PermissionError("denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny_notify_file)

    assert module._validate_notify_config(notify_file) is False


def test_main_keeps_notify_timer_disabled_on_read_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script()
    notify_file = tmp_path / "notify.env"
    notify_file.write_text('SWUDK_NOTIFY_TARGET="valid-target"\n', encoding="utf-8")
    run = _prepare_successful_setup(monkeypatch, module, notify_file)
    original_read_text = Path.read_text

    def deny_notify_file(path: Path, *args, **kwargs) -> str:
        if path == notify_file:
            raise PermissionError("denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny_notify_file)

    assert module.main() == 0

    assert call(["systemctl", "enable", "--now", "swu-checkin.timer"], check=True) in run.call_args_list
    assert call(["systemctl", "enable", "--now", "swu-checkin-notify.timer"], check=True) not in run.call_args_list
    assert "通知 timer 未启用" in capsys.readouterr().out


@pytest.mark.parametrize(
    "content",
    [
        "",
        'SWUDK_NOTIFY_CHANNEL="telegram"\n',
        "SWUDK_NOTIFY_TARGET=\n",
        'SWUDK_NOTIFY_TARGET="   "\n',
        'SWUDK_NOTIFY_TARGET="unterminated\nSENSITIVE_TOKEN=do-not-print\n',
        "SWUDK_NOTIFY_TARGET=secret-target\nmalformed\nAPI_TOKEN=secret-token\n",
    ],
)
def test_main_keeps_checkin_timer_enabled_but_rejects_invalid_notify_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    content: str,
) -> None:
    module = _load_script()
    notify_file = tmp_path / "notify.env"
    notify_file.write_text(content, encoding="utf-8")
    run = _prepare_successful_setup(monkeypatch, module, notify_file)

    assert module.main() == 0

    assert call(["systemctl", "enable", "--now", "swu-checkin.timer"], check=True) in run.call_args_list
    assert call(["systemctl", "enable", "--now", "swu-checkin-notify.timer"], check=True) not in run.call_args_list
    output = capsys.readouterr().out
    assert "通知 timer 未启用" in output
    assert "do-not-print" not in output
    assert "SENSITIVE_TOKEN" not in output
    assert "secret-target" not in output
    assert "secret-token" not in output
    assert "API_TOKEN" not in output


def test_main_keeps_notify_timer_disabled_when_file_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script()
    notify_file = tmp_path / "missing-notify.env"
    run = _prepare_successful_setup(monkeypatch, module, notify_file)

    assert module.main() == 0

    assert call(["systemctl", "enable", "--now", "swu-checkin.timer"], check=True) in run.call_args_list
    assert call(["systemctl", "enable", "--now", "swu-checkin-notify.timer"], check=True) not in run.call_args_list
    assert "未检测到 /etc/swu-checkin/notify.env" in capsys.readouterr().out


@pytest.mark.parametrize(
    "content",
    [
        'SWUDK_NOTIFY_TARGET="valid-target"\nSWUDK_NOTIFY_CHANNEL="telegram"\n',
        "SWUDK_NOTIFY_TARGET=valid-target\n",
    ],
)
def test_main_enables_both_timers_for_valid_notify_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str
) -> None:
    module = _load_script()
    notify_file = tmp_path / "notify.env"
    notify_file.write_text(content, encoding="utf-8")
    run = _prepare_successful_setup(monkeypatch, module, notify_file)

    assert module.main() == 0

    assert call(["systemctl", "enable", "--now", "swu-checkin.timer"], check=True) in run.call_args_list
    assert call(["systemctl", "enable", "--now", "swu-checkin-notify.timer"], check=True) in run.call_args_list


def _prepare_successful_setup(monkeypatch: pytest.MonkeyPatch, module: ModuleType, notify_file: Path) -> Mock:
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr("builtins.input", lambda _prompt: "username")
    passwords = iter(["password", "password"])
    monkeypatch.setattr(module.getpass, "getpass", lambda _prompt: next(passwords))
    monkeypatch.setattr(module, "_write_credentials", Mock())
    monkeypatch.setattr(module, "NOTIFY_FILE", notify_file)
    run = Mock()
    run.return_value.returncode = 0
    monkeypatch.setattr(module.subprocess, "run", run)
    return run
