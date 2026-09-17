import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_notifier_target_is_externalized_from_public_systemd_unit():
    unit = _read("deploy/systemd/swu-checkin-notify.service")

    assert "EnvironmentFile=/etc/swu-checkin/notify.env" in unit
    assert "SWUDK_NOTIFY_TARGET=" not in unit
    assert not re.search(r"Environment=SWUDK_NOTIFY_TARGET=\d+", unit)


def test_notifier_keeps_required_openclaw_access_narrow():
    unit = _read("deploy/systemd/swu-checkin-notify.service")

    assert "User=root" in unit
    assert "Group=root" in unit
    assert "ProtectHome=read-only" in unit
    assert "ReadWritePaths=/root/.openclaw/state" in unit
    assert "CacheDirectory=swu-checkin" in unit
    assert "StateDirectory=" not in unit


def test_checkin_service_uses_dedicated_account_and_private_state():
    unit = _read("deploy/systemd/swu-checkin.service")
    probe = _read("deploy/systemd/swu-checkin-probe.service")

    assert "User=swu-checkin" in unit
    assert "Group=swu-checkin" in unit
    assert "StateDirectory=swu-checkin" in unit
    assert "StateDirectoryMode=0700" in unit
    assert "User=swu-checkin" in probe
    assert "Group=swu-checkin" in probe


def test_timers_use_explicit_shanghai_schedule_without_late_catchup():
    timer = _read("deploy/systemd/swu-checkin.timer")
    notify_timer = _read("deploy/systemd/swu-checkin-notify.timer")

    assert timer.count("Asia/Shanghai") == 2
    assert "Persistent=false" in timer
    assert "Asia/Shanghai" in notify_timer
    assert "Persistent=false" in notify_timer


def test_actions_use_locked_dependencies_and_shanghai_timezone():
    workflow = _read(".github/workflows/checkin.yml")
    ci = _read(".github/workflows/ci.yml")

    assert "TZ: Asia/Shanghai" in workflow
    assert "uv sync --locked --no-dev --python 3.13" in workflow
    assert "uv run --locked --no-dev swu-checkin" in workflow
    assert "pip install" not in workflow
    assert "uv sync --locked --all-groups --python 3.13" in ci


def test_actions_treat_status_5_as_success_and_fail_on_real_errors():
    workflow = _read(".github/workflows/checkin.yml")

    assert '"$status_code" != "5"' in workflow
    assert "steps.checkin.outputs.status_code != '5'" in workflow
    assert 'steps.checkin.outputs.status_code }}" = "5"' in workflow
    assert "exit 1" in workflow
