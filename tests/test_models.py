import json

import pytest

from swu_checkin.models import SCHEMA_VERSION, STATUS_NAMES, CheckinResult
from swu_checkin.status import CheckinStatus, status_message


@pytest.mark.parametrize("status", list(CheckinStatus))
def test_checkin_result_maps_every_status(status: CheckinStatus):
    result = CheckinResult.from_status(status, attempts=2, duration_ms=17, mode="checkin")
    payload = result.to_dict()

    assert result.status == STATUS_NAMES[status]
    assert result.code == int(status)
    assert result.message == status_message(status)
    assert payload == {
        "schema_version": SCHEMA_VERSION,
        "mode": "checkin",
        "status": STATUS_NAMES[status],
        "code": int(status),
        "message": status_message(status),
        "attempts": 2,
        "duration_ms": 17,
    }
    assert json.loads(result.to_json()) == payload


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
