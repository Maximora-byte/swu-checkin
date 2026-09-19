"""Authenticated SWU business API transport."""

from __future__ import annotations

import json
from typing import cast

import requests

from .api_models import ApiSchemaError, DormitoryInfo, LeaveRecords, StudentProfile, Transition
from .status import VacationStatus

USER_INFO_URL = "https://of.swu.edu.cn/gateway/fighter-middle/api/auth/user"
DORMITORY_URL = "https://of.swu.edu.cn/gateway/fighter-baida/api/cqlc/getDormitory"
TRANSITION_TODAY_URL = "https://of.swu.edu.cn//gateway/fighter-baida/api/cqtj/getTransitionByToday"
LEAVE_RECORDS_URL = "https://of.swu.edu.cn/gateway/fighter-baida/api/xsqjxj/listSelfLeaveData"
CHECKIN_FORM_URL = "https://of.swu.edu.cn/gateway/fighter-baida/api/form-instance/save"
LEAVE_PAGE_SIZE = 100
MAX_LEAVE_PAGES = 20


class SwuClient:
    """Small authenticated HTTP client with no check-in policy decisions."""

    def __init__(self, token: str, timeout: int = 10, *, session: requests.Session | None = None) -> None:
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
    def _json_object(response: requests.Response, *, label: str) -> dict[str, object]:
        response.raise_for_status()
        payload: object = response.json()
        if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
            raise ValueError(f"{label} response is not an object")
        return cast("dict[str, object]", payload)

    def _student_payload(self) -> dict[str, object]:
        response = self._session.get(
            USER_INFO_URL,
            params={"appType": "fighter-portal"},
            headers=self._headers(),
            timeout=self.timeout,
        )
        return self._json_object(response, label="student")

    def get_student_profile(self) -> StudentProfile:
        return StudentProfile.from_response(self._student_payload())

    def get_student_id(self) -> str:
        """Compatibility wrapper returning the historical string value."""

        return self.get_student_profile().student_id

    def _dormitory_payload(self) -> dict[str, object]:
        response = self._session.post(
            DORMITORY_URL,
            headers=self._headers(json_content=True),
            data=json.dumps({}),
            timeout=self.timeout,
        )
        return self._json_object(response, label="dormitory")

    def get_dormitory_info(self) -> DormitoryInfo:
        return DormitoryInfo.from_response(self._dormitory_payload())

    def get_dormitory(self) -> dict[str, object]:
        """Compatibility wrapper returning the historical response object."""

        return self._dormitory_payload()

    def _transition_payload(self) -> dict[str, object]:
        response = self._session.post(
            TRANSITION_TODAY_URL,
            headers=self._headers(),
            data={"pageNum": 1, "pageSize": 1},
            timeout=self.timeout,
        )
        return self._json_object(response, label="transition")

    def get_transition(self) -> Transition | None:
        return Transition.from_response(self._transition_payload())

    def get_transition_today(self) -> dict[str, object] | None:
        """Compatibility wrapper returning the historical transition mapping."""

        payload = self._transition_payload()
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("transition response is missing data")
        records = data.get("records")
        if not isinstance(records, list):
            raise ValueError("transition records are invalid")
        if not records:
            return None
        record = records[0]
        if not isinstance(record, dict) or not all(isinstance(key, str) for key in record):
            raise ValueError("transition record is invalid")
        return cast("dict[str, object]", record)

    def _leave_page(self, page_num: int) -> tuple[list[object], LeaveRecords]:
        response = self._session.get(
            LEAVE_RECORDS_URL,
            params={"pageNum": page_num, "pageSize": LEAVE_PAGE_SIZE},
            headers=self._headers(),
            timeout=self.timeout,
        )
        payload = self._json_object(response, label="leave")
        parsed = LeaveRecords.from_response(payload)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ApiSchemaError("leave data is not an object")
        records = data.get("records")
        if not isinstance(records, list):
            raise ApiSchemaError("leave records is not a list")
        return records, parsed

    def _paginated_leave_records(self, *, stop_on_active_leave: bool) -> tuple[list[object], LeaveRecords]:
        raw_records: list[object] = []
        parsed_records = LeaveRecords(records=())
        for page_num in range(1, MAX_LEAVE_PAGES + 1):
            page_items, page_records = self._leave_page(page_num)
            if len(page_items) > LEAVE_PAGE_SIZE:
                raise ApiSchemaError("leave page exceeds the requested size")
            raw_records.extend(page_items)
            parsed_records = LeaveRecords(
                records=parsed_records.records + page_records.records,
                malformed=parsed_records.malformed or page_records.malformed,
            )
            if stop_on_active_leave and parsed_records.evaluate() is VacationStatus.ACTIVE_LEAVE:
                return raw_records, parsed_records
            if not page_items:
                return raw_records, parsed_records
        raise ApiSchemaError("leave pagination completeness cannot be confirmed")

    def get_leave_record_set(self) -> LeaveRecords:
        return self._paginated_leave_records(stop_on_active_leave=True)[1]

    def get_leave_records(self) -> list[object]:
        """Compatibility wrapper returning the historical records list."""

        return self._paginated_leave_records(stop_on_active_leave=False)[0]

    def submit_checkin_form(self, *, form_id: str | int, payload: dict[str, object]) -> object:
        response = self._session.post(
            CHECKIN_FORM_URL,
            headers=self._headers(json_content=True),
            params={"formId": form_id, "isSubmitProcess": False},
            data=json.dumps(payload),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
