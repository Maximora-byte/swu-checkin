from datetime import UTC, datetime

import pytest

from swu_checkin.api_models import (
    ApiSchemaError,
    DormitoryInfo,
    DormitorySchemaError,
    LeaveRecord,
    LeaveRecords,
    PendingTransition,
    StudentProfile,
    Transition,
)
from swu_checkin.status import VacationStatus


def _dormitory_response() -> dict[str, object]:
    return {
        "data": {
            "columnList": [
                {"address": "示例地址", "latitude": "29.123", "longitude": 106.456, "qdbj": "范围"},
                {"prop": "qsqddd", "value": " 橘园 "},
                {"prop": "qdbj", "value": " 001 "},
            ]
        }
    }


def test_normal_api_payloads_create_typed_models():
    profile = StudentProfile.from_response({"data": {"subject": {"username": "20260000000"}}})
    dormitory = DormitoryInfo.from_response(_dormitory_response())
    transition = Transition.from_response({"data": {"records": [{"id": "record-1", "formId": 42, "qdzt": "未签到"}]}})
    leave = LeaveRecord.from_payload({"lcztmc": "已同意", "kssj": "2026-09-19 08:00", "jssj": "2026-09-19 09:00"})

    assert profile.student_id == "20260000000"
    assert dormitory == DormitoryInfo(latitude=29.123, longitude=106.456, building="橘园", room="001")
    assert transition == Transition(record_id="record-1", form_id=42, checkin_status="未签到")
    assert transition.require_pending() == PendingTransition(record_id="record-1", form_id=42)
    assert leave.approval_status == "已同意"
    assert leave.start is not None
    assert leave.end is not None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": {}},
        {"data": {"subject": {}}},
        {"data": {"subject": {"username": 20260000000}}},
        {"data": {"subject": {"username": ""}}},
    ],
)
def test_student_profile_rejects_missing_or_wrong_fields(payload: object):
    with pytest.raises(ApiSchemaError):
        StudentProfile.from_response(payload)


def test_transition_rejects_missing_status():
    with pytest.raises(ApiSchemaError):
        Transition.from_record({"id": "record-1", "formId": "form-1"})


def test_terminal_transition_allows_status_only():
    transition = Transition.from_record({"qdzt": "已签到"})

    assert transition.is_checked_in is True
    assert transition.record_id is None
    assert transition.form_id is None


@pytest.mark.parametrize("record", [{"qdzt": "未签到"}, {"id": "record-1", "qdzt": "未签到"}])
def test_pending_transition_requires_both_submission_identifiers(record: object):
    transition = Transition.from_record(record)

    with pytest.raises(ApiSchemaError, match="missing id or form id"):
        transition.require_pending()


@pytest.mark.parametrize(
    "record",
    [
        {"id": True, "formId": "form-1", "qdzt": "未签到"},
        {"id": "record-1", "formId": False, "qdzt": "未签到"},
        {"id": 1.5, "formId": "form-1", "qdzt": "未签到"},
        {"id": "record-1", "formId": "form-1", "qdzt": 1},
    ],
)
def test_transition_rejects_wrong_types_and_bool_identifiers(record: object):
    with pytest.raises(ApiSchemaError):
        Transition.from_record(record)


@pytest.mark.parametrize("status", [" 已签到", "已签到 ", " 未签到 "])
def test_transition_protocol_status_does_not_trim_whitespace(status: str):
    with pytest.raises(ApiSchemaError, match="status is invalid"):
        Transition.from_record({"qdzt": status})


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": {"columnList": []}},
        {"data": {"columnList": [{"prop": "qddz", "latitude": True, "longitude": 106}]}},
        {
            "data": {
                "columnList": [
                    {"address": "x", "latitude": 29, "longitude": 106},
                    {"prop": "qsqddd", "value": "橘园"},
                    {"prop": "qdbj", "value": "001"},
                ]
            }
        },
    ],
)
def test_dormitory_model_rejects_malformed_data(payload: object):
    with pytest.raises(DormitorySchemaError):
        DormitoryInfo.from_response(payload)


@pytest.mark.parametrize(
    "record",
    [
        None,
        {},
        {"lcztmc": 1},
        {"lcztmc": "已同意", "kssj": "invalid", "jssj": "invalid"},
        {"lcztmc": "已同意", "kssj": "2026-09-19 10:00", "jssj": "2026-09-19 09:00"},
    ],
)
def test_leave_records_mark_malformed_data_and_fail_closed(record: object):
    records = LeaveRecords.from_response({"data": {"records": [record]}})

    assert records.malformed is True
    assert records.evaluate(now=datetime(2026, 9, 19, tzinfo=UTC)) is VacationStatus.UNKNOWN


def test_valid_active_leave_still_wins_when_another_record_is_malformed():
    records = LeaveRecords.from_items(
        [
            None,
            {"lcztmc": "已同意", "kssj": "2026-09-19 08:00", "jssj": "2026-09-19 10:00"},
        ]
    )

    assert records.evaluate(now=datetime(2026, 9, 19, 0, 30, tzinfo=UTC)) is VacationStatus.ACTIVE_LEAVE


@pytest.mark.parametrize("approval_status", [" 已同意", "已同意 ", " 已同意 "])
def test_leave_protocol_status_does_not_trim_whitespace(approval_status: str):
    records = LeaveRecords.from_items(
        [{"lcztmc": approval_status, "kssj": "2026-09-19 08:00", "jssj": "2026-09-19 10:00"}]
    )

    assert records.malformed is True
    assert records.evaluate(now=datetime(2026, 9, 19, 0, 30, tzinfo=UTC)) is VacationStatus.UNKNOWN
