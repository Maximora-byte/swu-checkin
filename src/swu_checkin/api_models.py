"""Typed, fail-closed models for the SWU business API boundary."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from .status import VacationStatus
from .time_utils import now_shanghai, parse_swu_datetime

CURRENT_LOCATION_FIELDS = frozenset({"address", "latitude", "longitude", "qdbj"})


class ApiSchemaError(ValueError):
    """An SWU API response cannot be interpreted safely."""


class DormitorySchemaError(ApiSchemaError):
    """The dormitory response cannot be interpreted without ambiguity."""


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ApiSchemaError(f"{label} is not an object")
    return cast("Mapping[str, object]", value)


def _sequence(value: object, *, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ApiSchemaError(f"{label} is not a list")
    return value


def _required_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiSchemaError(f"{label} is missing")
    return value.strip()


def _identifier(value: object, *, label: str) -> str | int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ApiSchemaError(f"{label} has an invalid type")
    if isinstance(value, str) and not value.strip():
        raise ApiSchemaError(f"{label} is missing")
    return value


def parse_coordinate(value: object, *, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ApiSchemaError(f"{name} is not a valid coordinate")
    try:
        coordinate = float(value)
    except (TypeError, ValueError) as error:
        raise ApiSchemaError(f"{name} is not a valid coordinate") from error
    if not math.isfinite(coordinate) or not minimum <= coordinate <= maximum:
        raise ApiSchemaError(f"{name} is outside the valid range")
    return coordinate


@dataclass(frozen=True)
class StudentProfile:
    student_id: str

    @classmethod
    def from_response(cls, payload: object) -> StudentProfile:
        root = _mapping(payload, label="student response")
        data = _mapping(root.get("data"), label="student data")
        subject = _mapping(data.get("subject"), label="student subject")
        return cls(student_id=_required_text(subject.get("username"), label="student id"))


@dataclass(frozen=True)
class DormitoryInfo:
    latitude: float
    longitude: float
    building: str
    room: str

    @classmethod
    def from_response(cls, payload: object) -> DormitoryInfo:
        try:
            root = _mapping(payload, label="dormitory response")
            data = _mapping(root.get("data"), label="dormitory data")
            columns = _sequence(data.get("columnList"), label="dormitory columns")
            return cls.from_columns(columns)
        except ApiSchemaError as error:
            if isinstance(error, DormitorySchemaError):
                raise
            raise DormitorySchemaError(str(error)) from error

    @classmethod
    def from_columns(cls, columns: Sequence[object]) -> DormitoryInfo:
        location_candidates: list[Mapping[str, object]] = []
        building: object = None
        room: object = None
        for raw_item in columns:
            if not isinstance(raw_item, dict) or not all(isinstance(key, str) for key in raw_item):
                continue
            item = cast("Mapping[str, object]", raw_item)
            prop = item.get("prop")
            if prop == "qddz":
                location_candidates.append(item)
            elif "prop" not in item and CURRENT_LOCATION_FIELDS.issubset(item):
                location_candidates.append(item)
            elif prop == "qsqddd":
                building = item.get("value")
            elif prop == "qdbj":
                room = item.get("value")

        if len(location_candidates) != 1:
            raise DormitorySchemaError("dormitory response has an invalid or ambiguous schema")
        try:
            building_text = _required_text(building, label="dormitory building")
            room_text = _required_text(room, label="dormitory room")
            location = location_candidates[0]
            latitude = parse_coordinate(location.get("latitude"), name="latitude", minimum=-90, maximum=90)
            longitude = parse_coordinate(location.get("longitude"), name="longitude", minimum=-180, maximum=180)
        except ApiSchemaError as error:
            raise DormitorySchemaError(str(error)) from error
        return cls(latitude=latitude, longitude=longitude, building=building_text, room=room_text)


@dataclass(frozen=True)
class Transition:
    record_id: str | int
    form_id: str | int
    checkin_status: str

    @property
    def is_checked_in(self) -> bool:
        return self.checkin_status == "已签到"

    @classmethod
    def from_record(cls, payload: object) -> Transition:
        record = _mapping(payload, label="transition record")
        return cls(
            record_id=_identifier(record.get("id"), label="transition id"),
            form_id=_identifier(record.get("formId"), label="transition form id"),
            checkin_status=_required_text(record.get("qdzt"), label="transition status"),
        )

    @classmethod
    def from_response(cls, payload: object) -> Transition | None:
        root = _mapping(payload, label="transition response")
        data = _mapping(root.get("data"), label="transition data")
        records = _sequence(data.get("records"), label="transition records")
        if not records:
            return None
        return cls.from_record(records[0])


@dataclass(frozen=True)
class LeaveRecord:
    approval_status: str
    start: datetime | None = None
    end: datetime | None = None

    @classmethod
    def from_payload(cls, payload: object) -> LeaveRecord:
        record = _mapping(payload, label="leave record")
        approval_status = _required_text(record.get("lcztmc"), label="leave approval status")
        if approval_status != "已同意":
            return cls(approval_status=approval_status)
        start_raw = _required_text(record.get("kssj"), label="leave start")
        end_raw = _required_text(record.get("jssj"), label="leave end")
        try:
            start = parse_swu_datetime(start_raw)
            end = parse_swu_datetime(end_raw)
        except (TypeError, ValueError) as error:
            raise ApiSchemaError("leave time is invalid") from error
        if end < start:
            raise ApiSchemaError("leave end precedes start")
        return cls(approval_status=approval_status, start=start, end=end)


@dataclass(frozen=True)
class LeaveRecords:
    records: tuple[LeaveRecord, ...]
    malformed: bool = False

    @classmethod
    def from_response(cls, payload: object) -> LeaveRecords:
        root = _mapping(payload, label="leave response")
        data = _mapping(root.get("data"), label="leave data")
        return cls.from_items(_sequence(data.get("records"), label="leave records"))

    @classmethod
    def from_items(cls, items: Sequence[object]) -> LeaveRecords:
        records: list[LeaveRecord] = []
        malformed = False
        for item in items:
            try:
                records.append(LeaveRecord.from_payload(item))
            except ApiSchemaError:
                malformed = True
        return cls(records=tuple(records), malformed=malformed)

    def evaluate(self, *, now: datetime | None = None) -> VacationStatus:
        current = now or now_shanghai()
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        for record in self.records:
            if record.approval_status != "已同意":
                continue
            if record.start is None or record.end is None:
                return VacationStatus.UNKNOWN
            if record.start <= current.astimezone(record.start.tzinfo) <= record.end:
                return VacationStatus.ACTIVE_LEAVE
        return VacationStatus.UNKNOWN if self.malformed else VacationStatus.NO_ACTIVE_LEAVE


@dataclass(frozen=True)
class CheckinSubmission:
    student: StudentProfile
    dormitory: DormitoryInfo
    transition: Transition
