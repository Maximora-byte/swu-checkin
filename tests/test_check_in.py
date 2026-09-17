from unittest.mock import Mock, patch

from swu_checkin.cache import CheckinContext
from swu_checkin.check_in import _business_response_succeeded, _submit_checkin, probe_check_in


def _context() -> CheckinContext:
    return CheckinContext(
        token="test-token",
        student_id="20260000000",
        building="橘园",
        room="001",
        latitude=29.0,
        longitude=106.0,
        transition={"formId": "form-1", "id": "record-1", "qdzt": "未签到"},
    )


def _response(payload: object) -> Mock:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def test_business_response_requires_explicit_success_signal():
    assert _business_response_succeeded({"code": 200, "message": "保存成功"})
    assert _business_response_succeeded({"success": True})
    assert not _business_response_succeeded({"code": 500, "message": "保存失败"})
    assert not _business_response_succeeded({"message": "保存成功"})
    assert not _business_response_succeeded("保存成功")


@patch("swu_checkin.check_in.time.sleep", return_value=None)
@patch("swu_checkin.check_in.get_transition_today")
@patch("swu_checkin.check_in.requests.post")
def test_submit_requires_server_side_confirmation(post: Mock, get_transition: Mock, _sleep: Mock):
    post.return_value = _response({"code": 200, "message": "保存成功"})
    get_transition.return_value = {"qdzt": "未签到"}

    assert _submit_checkin(_context(), 10) == 4
    assert get_transition.call_count == 4


@patch("swu_checkin.check_in.time.sleep", return_value=None)
@patch("swu_checkin.check_in.get_transition_today")
@patch("swu_checkin.check_in.requests.post")
def test_submit_succeeds_only_after_readback(post: Mock, get_transition: Mock, _sleep: Mock):
    post.return_value = _response({"code": 200, "message": "保存成功"})
    get_transition.side_effect = [{"qdzt": "未签到"}, {"qdzt": "已签到"}]

    assert _submit_checkin(_context(), 10) == 1
    assert get_transition.call_count == 2


@patch("swu_checkin.check_in.requests.post")
@patch("swu_checkin.check_in.get_transition_today")
@patch("swu_checkin.check_in._check_vacation_enabled", return_value=False)
@patch("swu_checkin.check_in.get_token", return_value="test-token")
def test_probe_never_submits(_token: Mock, _vacation: Mock, get_transition: Mock, post: Mock):
    get_transition.return_value = {"id": "record-1", "formId": "form-1", "qdzt": "未签到"}

    assert probe_check_in("student", "password") == 6
    post.assert_not_called()
