import json

import pytest

from swu_checkin.actions_result import load_checkin_result, main, parse_checkin_result
from swu_checkin.models import CheckinResult
from swu_checkin.status import CheckinStatus


def _payload() -> dict[str, object]:
    return CheckinResult.from_status(
        CheckinStatus.SUCCESS,
        attempts=1,
        duration_ms=12,
        mode="checkin",
    ).to_dict()


def test_actions_parser_accepts_valid_json_and_writes_outputs(tmp_path):
    result_path = tmp_path / "result.json"
    output_path = tmp_path / "github-output"
    result_path.write_text(json.dumps(_payload()), encoding="utf-8")

    assert main([str(result_path), str(output_path)]) == 0
    outputs = output_path.read_text(encoding="utf-8")
    assert "status_code=1" in outputs
    assert "status_msg=签到成功" in outputs
    assert "status_name=success" in outputs
    assert "full_result={" in outputs
    assert load_checkin_result(result_path) == _payload()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {**_payload(), "schema_version": 2},
        {key: value for key, value in _payload().items() if key != "code"},
        {**_payload(), "code": 99},
        {**_payload(), "status": "success", "code": 4},
        {**_payload(), "mode": "probe"},
    ],
)
def test_actions_parser_rejects_invalid_or_inconsistent_results(payload):
    with pytest.raises(ValueError):
        parse_checkin_result(payload)


def test_actions_parser_rejects_malformed_json_without_outputs(tmp_path):
    result_path = tmp_path / "result.json"
    output_path = tmp_path / "github-output"
    result_path.write_text("not-json", encoding="utf-8")

    assert main([str(result_path), str(output_path)]) == 2
    assert not output_path.exists()
