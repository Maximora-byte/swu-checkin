from unittest.mock import Mock, call

import pytest

from swu_checkin.cache import CheckinContext
from swu_checkin.service import CheckinService, build_checkin_payload
from swu_checkin.status import CheckinStatus


@pytest.mark.parametrize(
    ("statuses", "expected", "attempts"),
    [
        ([CheckinStatus.DATA_ERROR, CheckinStatus.DATA_ERROR, CheckinStatus.SUCCESS], "success", 3),
        ([CheckinStatus.DATA_ERROR, CheckinStatus.DATA_ERROR, CheckinStatus.DATA_ERROR], "data_error", 3),
    ],
)
def test_retry_result_tracks_attempts_without_real_sleep(statuses, expected, attempts):
    sleep = Mock()
    diagnostics = Mock()
    times = iter([10.0, 10.25])
    service = CheckinService(sleep=sleep, clock=lambda: next(times), diagnostic=diagnostics)
    service.check_in_once = Mock(side_effect=statuses)

    result = service.run_checkin("student", "password", max_attempts=3, retry_delay=8)

    assert result.status == expected
    assert result.attempts == attempts
    assert result.duration_ms == 250
    assert sleep.call_args_list == [call(8), call(16)]


def test_probe_result_is_single_attempt_and_non_negative_duration():
    times = iter([4.0, 3.5])
    service = CheckinService(clock=lambda: next(times))
    service.probe_once = Mock(return_value=CheckinStatus.PROBE_PENDING)

    result = service.run_probe("student", "password")

    assert result.mode == "probe"
    assert result.status == "probe_pending"
    assert result.attempts == 1
    assert result.duration_ms == 0


def test_payload_fields_and_values_remain_unchanged(monkeypatch):
    monkeypatch.setattr("swu_checkin.service.today_shanghai", lambda: "2026-09-18")
    monkeypatch.setattr("swu_checkin.service.epoch_milliseconds", lambda: 123456789)
    ctx = CheckinContext(
        student_id="20260000000",
        building="橘园",
        room="001",
        latitude=29.0,
        longitude=106.0,
        transition={"formId": "form-1", "id": "record-1"},
    )

    assert build_checkin_payload(ctx) == {
        "id": "record-1",
        "formId": "form-1",
        "tsrq": "2026-09-18",
        "xh": "20260000000",
        "qdsj": ["21:00", "23:30"],
        "qsqddd": "橘园",
        "qdbj": "001",
        "qddz": {
            "latitude": 29.0,
            "longitude": 106.0,
            "address": "橘园",
            "netType": "wifi",
            "operatorType": "unknown",
            "imei": "imei",
            "time": 123456789,
            "provider": "lbs",
            "isFromMock": False,
            "isGpsEnabled": True,
            "isWifiEnabled": True,
            "isMobileEnabled": False,
            "isOffset": True,
            "cityAdCode": "023",
            "districtAdCode": "500109",
            "isArea": True,
            "tip": "当前在签到范围内",
        },
    }


def test_doctor_diagnostics_are_read_only_and_never_submit():
    client = Mock()
    client.get_student_id.return_value = "20260000000"
    client.get_dormitory.return_value = {
        "data": {
            "columnList": [
                {"prop": "qddz", "latitude": 29.0, "longitude": 106.0},
                {"prop": "qsqddd", "value": "building"},
                {"prop": "qdbj", "value": "room"},
            ]
        }
    }
    client.get_transition_today.return_value = None
    service = CheckinService(
        token_provider=lambda *_args: "token",
        client_factory=lambda *_args: client,
    )

    report = service.diagnose("student", "password")

    assert report.authentication is True
    assert report.student_profile is True
    assert report.dormitory_schema is True
    assert report.checkin_api is True
    client.submit_checkin_form.assert_not_called()
