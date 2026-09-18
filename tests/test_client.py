import json
from unittest.mock import Mock

import pytest
import requests

from swu_checkin.client import (
    CHECKIN_FORM_URL,
    DORMITORY_URL,
    LEAVE_RECORDS_URL,
    TRANSITION_TODAY_URL,
    USER_INFO_URL,
    SwuClient,
)


def _response(payload: object) -> Mock:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


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


def test_client_leave_records_and_malformed_json_fail_closed():
    session = Mock()
    session.get.return_value = _response({"data": {"records": [{"lcztmc": "审核中"}]}})
    client = SwuClient("token", session=session)

    assert client.get_leave_records() == [{"lcztmc": "审核中"}]
    assert session.get.call_args.args[0] == LEAVE_RECORDS_URL

    session.get.return_value = _response({"data": {"records": None}})
    with pytest.raises(ValueError, match="records"):
        client.get_leave_records()


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
