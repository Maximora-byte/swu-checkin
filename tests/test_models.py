import json

import pytest

from swu_checkin.models import SCHEMA_VERSION, STATUS_NAMES, CheckinResult
from swu_checkin.status import CheckinStatus, status_message


@pytest.mark.parametrize("status", list(CheckinStatus))
def test_checkin_result_maps_every_status(status: CheckinStatus):
    mode = "probe" if status is CheckinStatus.PROBE_PENDING else "checkin"
    result = CheckinResult.from_status(status, attempts=2, duration_ms=17, mode=mode)
    payload = result.to_dict()

    assert result.status == STATUS_NAMES[status]
    assert result.code == int(status)
    assert result.message == status_message(status)
    assert payload == {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "status": STATUS_NAMES[status],
        "code": int(status),
        "message": status_message(status),
        "attempts": 2,
        "duration_ms": 17,
    }
    assert json.loads(result.to_json()) == payload


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("checkin", CheckinStatus.NO_TASK),
        ("checkin", CheckinStatus.SUCCESS),
        ("checkin", CheckinStatus.ALREADY_CHECKED_IN),
        ("checkin", CheckinStatus.LOGIN_FAILED),
        ("checkin", CheckinStatus.DATA_ERROR),
        ("checkin", CheckinStatus.ON_LEAVE),
        ("probe", CheckinStatus.NO_TASK),
        ("probe", CheckinStatus.ALREADY_CHECKED_IN),
        ("probe", CheckinStatus.LOGIN_FAILED),
        ("probe", CheckinStatus.DATA_ERROR),
        ("probe", CheckinStatus.ON_LEAVE),
        ("probe", CheckinStatus.PROBE_PENDING),
    ],
)
def test_checkin_result_accepts_only_mode_status_matrix(mode: str, code: CheckinStatus):
    result = CheckinResult.from_status(code, attempts=1, duration_ms=0, mode=mode)

    assert result.mode == mode
    assert result.code == int(code)


@pytest.mark.parametrize(
    ("mode", "code"),
    [("checkin", CheckinStatus.PROBE_PENDING), ("probe", CheckinStatus.SUCCESS)],
)
def test_checkin_result_rejects_status_not_allowed_for_mode(mode: str, code: CheckinStatus):
    with pytest.raises(ValueError, match="not valid for mode"):
        CheckinResult.from_status(code, attempts=1, duration_ms=0, mode=mode)


def test_checkin_result_from_dict_accepts_exact_schema():
    payload = CheckinResult.from_status(
        CheckinStatus.PROBE_PENDING,
        attempts=1,
        duration_ms=0,
        mode="probe",
    ).to_dict()

    assert CheckinResult.from_dict(payload).to_dict() == payload


@pytest.mark.parametrize("schema_version", [1.0, True, "1"])
def test_checkin_result_from_dict_rejects_non_integer_schema_version(schema_version: object):
    payload = CheckinResult.from_status(
        CheckinStatus.SUCCESS,
        attempts=1,
        duration_ms=0,
        mode="checkin",
    ).to_dict()
    payload["schema_version"] = schema_version

    with pytest.raises(ValueError, match="schema version"):
        CheckinResult.from_dict(payload)


def test_checkin_result_from_dict_rejects_extra_fields():
    payload = CheckinResult.from_status(
        CheckinStatus.SUCCESS,
        attempts=1,
        duration_ms=0,
        mode="checkin",
    ).to_dict()
    payload["extra"] = "not-allowed"

    with pytest.raises(ValueError, match="fields do not match"):
        CheckinResult.from_dict(payload)


def test_checkin_result_from_dict_rejects_non_string_mode():
    payload = CheckinResult.from_status(
        CheckinStatus.SUCCESS,
        attempts=1,
        duration_ms=0,
        mode="checkin",
    ).to_dict()
    payload["mode"] = ["checkin"]

    with pytest.raises(ValueError, match="mode must be"):
        CheckinResult.from_dict(payload)


@pytest.mark.parametrize(
    ("attempts", "duration_ms"),
    [(0, 0), (-1, 0), (True, 0), (1, -1), (1, True)],
)
def test_checkin_result_rejects_invalid_metrics(attempts: int, duration_ms: int):
    with pytest.raises(ValueError):
        CheckinResult.from_status(
            CheckinStatus.SUCCESS,
            attempts=attempts,
            duration_ms=duration_ms,
            mode="checkin",
        )


def test_checkin_result_contains_no_sensitive_fields():
    payload = CheckinResult.from_status(
        CheckinStatus.SUCCESS,
        attempts=1,
        duration_ms=0,
        mode="checkin",
    ).to_dict()

    assert not ({"username", "password", "token", "ticket", "state", "captcha", "callback_url"} & payload.keys())
