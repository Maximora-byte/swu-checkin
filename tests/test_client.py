import json
from unittest.mock import Mock

import pytest
import requests

from swu_checkin.api_models import ApiSchemaError, DormitoryInfo, LeaveRecords, StudentProfile, Transition
from swu_checkin.client import (
    CHECKIN_FORM_URL,
    DORMITORY_URL,
    LEAVE_PAGE_SIZE,
    LEAVE_RECORDS_URL,
    MAX_LEAVE_PAGES,
    TRANSITION_TODAY_URL,
    USER_INFO_URL,
    SwuClient,
)
from swu_checkin.status import VacationStatus


def _response(payload: object) -> Mock:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def _leave_response(records: object) -> Mock:
    return _response({"data": {"records": records}})


def _inactive_records(count: int, *, start: int = 0) -> list[dict[str, object]]:
    return [{"id": index, "lcztmc": "审核中"} for index in range(start, start + count)]


def _active_leave() -> dict[str, object]:
    return {"lcztmc": "已同意", "kssj": "2000-01-01 00:00", "jssj": "2100-01-01 00:00"}


def test_client_uses_token_headers_timeout_and_response_validation():
    session = Mock()
    session.get.return_value = _response({"data": {"subject": {"username": "20260000000"}}})
    client = SwuClient("secret-token", timeout=7, session=session)

    assert client.get_student_id() == "20260000000"
    session.get.assert_called_once_with(
        USER_INFO_URL,
        params={"appType": "fighter-portal"},
        headers={"fighter-auth-token": "secret-token"},
        timeout=7,
    )
    session.get.return_value.raise_for_status.assert_called_once_with()


def test_client_business_api_request_shapes_are_preserved():
    session = Mock()
    session.post.side_effect = [
        _response({"data": {"columnList": []}}),
        _response({"data": {"records": [{"id": "record"}]}}),
        _response({"code": 200}),
    ]
    client = SwuClient("token", timeout=9, session=session)

    assert client.get_dormitory() == {"data": {"columnList": []}}
    assert client.get_transition_today() == {"id": "record"}
    assert client.submit_checkin_form(form_id="form", payload={"id": "record"}) == {"code": 200}

    dormitory_call, transition_call, submit_call = session.post.call_args_list
    assert dormitory_call.args[0] == DORMITORY_URL
    assert dormitory_call.kwargs["data"] == json.dumps({})
    assert dormitory_call.kwargs["timeout"] == 9
    assert transition_call.args[0] == TRANSITION_TODAY_URL
    assert transition_call.kwargs["data"] == {"pageNum": 1, "pageSize": 1}
    assert submit_call.args[0] == CHECKIN_FORM_URL
    assert submit_call.kwargs["params"] == {"formId": "form", "isSubmitProcess": False}
    assert json.loads(submit_call.kwargs["data"]) == {"id": "record"}


def test_leave_pagination_stops_when_first_page_is_not_full():
    session = Mock()
    records = _inactive_records(2)
    session.get.return_value = _leave_response(records)
    client = SwuClient("token", session=session)

    assert client.get_leave_records() == records
    session.get.assert_called_once_with(
        LEAVE_RECORDS_URL,
        params={"pageNum": 1, "pageSize": LEAVE_PAGE_SIZE},
        headers={"fighter-auth-token": "token"},
        timeout=10,
    )


def test_leave_pagination_merges_full_page_and_partial_page():
    first_page = _inactive_records(LEAVE_PAGE_SIZE)
    second_page = _inactive_records(2, start=LEAVE_PAGE_SIZE)
    session = Mock()
    session.get.side_effect = [_leave_response(first_page), _leave_response(second_page)]

    records = SwuClient("token", session=session).get_leave_records()

    assert records == first_page + second_page
    assert [call.kwargs["params"] for call in session.get.call_args_list] == [
        {"pageNum": 1, "pageSize": LEAVE_PAGE_SIZE},
        {"pageNum": 2, "pageSize": LEAVE_PAGE_SIZE},
    ]


def test_later_full_page_active_leave_safely_stops_pagination():
    session = Mock()
    session.get.side_effect = [
        _leave_response(_inactive_records(LEAVE_PAGE_SIZE)),
        _leave_response([_active_leave(), *_inactive_records(LEAVE_PAGE_SIZE - 1, start=LEAVE_PAGE_SIZE)]),
    ]

    records = SwuClient("token", session=session).get_leave_record_set()

    assert records.evaluate() is VacationStatus.ACTIVE_LEAVE
    assert session.get.call_count == 2


def test_malformed_earlier_page_without_active_leave_is_unknown():
    session = Mock()
    session.get.side_effect = [
        _leave_response([None, *_inactive_records(LEAVE_PAGE_SIZE - 1)]),
        _leave_response(_inactive_records(1, start=LEAVE_PAGE_SIZE)),
    ]

    records = SwuClient("token", session=session).get_leave_record_set()

    assert records.evaluate() is VacationStatus.UNKNOWN


def test_later_active_leave_wins_over_malformed_earlier_page():
    session = Mock()
    session.get.side_effect = [
        _leave_response([None, *_inactive_records(LEAVE_PAGE_SIZE - 1)]),
        _leave_response([_active_leave(), *_inactive_records(LEAVE_PAGE_SIZE - 1, start=LEAVE_PAGE_SIZE)]),
    ]

    records = SwuClient("token", session=session).get_leave_record_set()

    assert records.malformed is True
    assert records.evaluate() is VacationStatus.ACTIVE_LEAVE
    assert session.get.call_count == 2


def test_empty_leave_records_are_no_active_leave():
    session = Mock()
    session.get.return_value = _leave_response([])

    records = SwuClient("token", session=session).get_leave_record_set()

    assert records.evaluate() is VacationStatus.NO_ACTIVE_LEAVE


@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": {}}, {"data": {"records": None}}])
def test_leave_pagination_rejects_invalid_envelope_or_records(payload: object):
    session = Mock()
    session.get.return_value = _response(payload)

    with pytest.raises(ApiSchemaError):
        SwuClient("token", session=session).get_leave_records()


def test_leave_page_larger_than_requested_size_fails_closed():
    session = Mock()
    session.get.return_value = _leave_response(_inactive_records(LEAVE_PAGE_SIZE + 1))

    with pytest.raises(ApiSchemaError, match="exceeds"):
        SwuClient("token", session=session).get_leave_record_set()


def test_full_maximum_leave_pages_fail_closed_without_extra_request():
    session = Mock()
    session.get.side_effect = [
        _leave_response(_inactive_records(LEAVE_PAGE_SIZE, start=page_num * LEAVE_PAGE_SIZE))
        for page_num in range(MAX_LEAVE_PAGES)
    ]

    with pytest.raises(ApiSchemaError, match="completeness"):
        SwuClient("token", session=session).get_leave_record_set()

    assert session.get.call_count == MAX_LEAVE_PAGES
    assert [call.kwargs["params"]["pageNum"] for call in session.get.call_args_list] == list(
        range(1, MAX_LEAVE_PAGES + 1)
    )
    assert {call.kwargs["params"]["pageSize"] for call in session.get.call_args_list} == {LEAVE_PAGE_SIZE}


def test_client_propagates_http_errors_without_logging_token(capsys):
    session = Mock()
    response = _response({})
    response.raise_for_status.side_effect = requests.HTTPError("service unavailable")
    session.get.return_value = response
    client = SwuClient("never-print-this-token", session=session)

    with pytest.raises(requests.HTTPError):
        client.get_student_id()

    captured = capsys.readouterr()
    assert "never-print-this-token" not in captured.out + captured.err


def test_client_typed_methods_validate_before_returning_models():
    session = Mock()
    session.get.side_effect = [
        _response({"data": {"subject": {"username": "20260000000"}}}),
        _response({"data": {"records": [{"lcztmc": "审核中"}]}}),
    ]
    session.post.side_effect = [
        _response(
            {
                "data": {
                    "columnList": [
                        {"prop": "qddz", "latitude": 29.0, "longitude": 106.0},
                        {"prop": "qsqddd", "value": "橘园"},
                        {"prop": "qdbj", "value": "001"},
                    ]
                }
            }
        ),
        _response({"data": {"records": [{"id": "record-1", "formId": "form-1", "qdzt": "未签到"}]}}),
    ]
    client = SwuClient("token", session=session)

    assert client.get_student_profile() == StudentProfile("20260000000")
    assert client.get_dormitory_info() == DormitoryInfo(29.0, 106.0, "橘园", "001")
    assert client.get_transition() == Transition("record-1", "form-1", "未签到")
    assert client.get_leave_record_set() == LeaveRecords.from_items([{"lcztmc": "审核中"}])


def test_client_transition_accepts_status_only_terminal_record():
    session = Mock()
    session.post.return_value = _response({"data": {"records": [{"qdzt": "已签到"}]}})

    transition = SwuClient("token", session=session).get_transition()

    assert transition == Transition(record_id=None, form_id=None, checkin_status="已签到")
    assert transition.is_checked_in is True
