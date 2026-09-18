"""Authenticated SWU business API transport."""

from __future__ import annotations

import json
from typing import Any

import requests

USER_INFO_URL = "https://of.swu.edu.cn/gateway/fighter-middle/api/auth/user"
DORMITORY_URL = "https://of.swu.edu.cn/gateway/fighter-baida/api/cqlc/getDormitory"
TRANSITION_TODAY_URL = "https://of.swu.edu.cn//gateway/fighter-baida/api/cqtj/getTransitionByToday"
LEAVE_RECORDS_URL = "https://of.swu.edu.cn/gateway/fighter-baida/api/xsqjxj/listSelfLeaveData?pageNum=1&pageSize=10"
CHECKIN_FORM_URL = "https://of.swu.edu.cn/gateway/fighter-baida/api/form-instance/save"


class SwuClient:
    """Small authenticated HTTP client with no check-in policy decisions."""

    def __init__(self, token: str, timeout: int = 10, *, session: Any | None = None):
        if not isinstance(token, str) or not token:
            raise ValueError("token is required")
        self._token = token
        self.timeout = timeout
        self._session = session or requests.Session()

    def _headers(self, *, json_content: bool = False) -> dict[str, str]:
        headers = {"fighter-auth-token": self._token}
        if json_content:
            headers["Content-Type"] = "application/json;charset=UTF-8"
        return headers

    @staticmethod
    def _json_object(response: Any, *, label: str) -> dict[str, Any]:
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"{label} response is not an object")
        return payload

    def get_student_id(self) -> str:
        response = self._session.get(
            USER_INFO_URL,
            params={"appType": "fighter-portal"},
            headers=self._headers(),
            timeout=self.timeout,
        )
        payload = self._json_object(response, label="student")
        student_id = payload["data"]["subject"]["username"]
        if not isinstance(student_id, str) or not student_id:
            raise ValueError("student id is missing")
        return student_id

    def get_dormitory(self) -> dict[str, Any]:
        response = self._session.post(
            DORMITORY_URL,
            headers=self._headers(json_content=True),
            data=json.dumps({}),
            timeout=self.timeout,
        )
        return self._json_object(response, label="dormitory")

    def get_transition_today(self) -> dict[str, Any] | None:
        response = self._session.post(
            TRANSITION_TODAY_URL,
            headers=self._headers(),
            data={"pageNum": 1, "pageSize": 1},
            timeout=self.timeout,
        )
        payload = self._json_object(response, label="transition")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("transition response is missing data")
        records = data.get("records")
        if not isinstance(records, list):
            raise ValueError("transition records are invalid")
        if not records:
            return None
        record = records[0]
        if not isinstance(record, dict):
            raise ValueError("transition record is invalid")
        return record

    def get_leave_records(self) -> list[dict[str, Any] | object]:
        response = self._session.get(
            LEAVE_RECORDS_URL,
            headers=self._headers(),
            timeout=self.timeout,
        )
        payload = self._json_object(response, label="leave")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("leave response is missing data")
        records = data.get("records")
        if not isinstance(records, list):
            raise ValueError("leave records are invalid")
        return records

    def submit_checkin_form(self, *, form_id: object, payload: dict[str, Any]) -> object:
        response = self._session.post(
            CHECKIN_FORM_URL,
            headers=self._headers(json_content=True),
            params={"formId": form_id, "isSubmitProcess": False},
            data=json.dumps(payload),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
