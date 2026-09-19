"""Backward-compatible public check-in API and module entry point."""

from __future__ import annotations

import os
from datetime import datetime

from .cache import CheckinContext
from .client import SwuClient
from .service import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_RETRY_DELAY,
    EXPECTED_DATA_ERRORS,
    CheckinService,
    business_response_succeeded,
    parse_coordinate,
    parse_dormitory_data,
    submission_from_legacy_context,
)
from .service import (
    run_checkin as run_checkin_result,
)
from .status import CheckinStatus, VacationStatus
from .storage import record_run_status

# Internal compatibility aliases retained for existing imports and deployment tests.
_business_response_succeeded = business_response_succeeded
_parse_coordinate = parse_coordinate
_parse_dormitory_data = parse_dormitory_data
_record_run_status = record_run_status


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _check_vacation_status(
    ctx: CheckinContext,
    timeout: int,
    *,
    now: datetime | None = None,
) -> VacationStatus:
    """Compatibility wrapper around the client and leave-policy evaluator."""

    try:
        if ctx.token is None:
            return VacationStatus.UNKNOWN
        return SwuClient(ctx.token, timeout).get_leave_record_set().evaluate(now=now)
    except EXPECTED_DATA_ERRORS:
        return VacationStatus.UNKNOWN


def _confirm_checkin(token: str, timeout: int) -> bool:
    """Compatibility wrapper for submission read-back confirmation."""

    client = SwuClient(token, timeout)
    return CheckinService(timeout=timeout)._confirm_checkin(client)


def _submit_checkin(ctx: CheckinContext, timeout: int) -> CheckinStatus:
    """Compatibility wrapper for a single prepared-context submission."""

    try:
        if ctx.token is None:
            return CheckinStatus.DATA_ERROR
        submission = submission_from_legacy_context(ctx)
        return CheckinService(timeout=timeout)._submit_checkin(SwuClient(ctx.token, timeout), submission)
    except EXPECTED_DATA_ERRORS:
        return CheckinStatus.DATA_ERROR


def check_in(username: str, password: str, timeout: int = 10) -> CheckinStatus:
    """Execute one check-in attempt and return the historical status enum."""

    return CheckinService(timeout=timeout).check_in_once(username, password)


def probe_check_in(username: str, password: str, timeout: int = 10) -> CheckinStatus:
    """Execute one read-only probe and return the historical status enum."""

    return CheckinService(timeout=timeout).probe_once(username, password)


def check_in_with_retry(
    username: str,
    password: str,
    timeout: int = 10,
    max_attempts: int | None = None,
    retry_delay: int | None = None,
) -> CheckinStatus:
    """Execute check-in with the existing retry policy and return only its status."""

    result = run_checkin_result(
        username,
        password,
        timeout,
        max_attempts=max_attempts or _env_int("SWUDK_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS),
        retry_delay=retry_delay or _env_int("SWUDK_RETRY_DELAY", DEFAULT_RETRY_DELAY),
    )
    return CheckinStatus(result.code)


def main() -> int:
    """Backward-compatible programmatic entry point with no CLI arguments."""

    from .cli import main as cli_main

    return cli_main([])


if __name__ == "__main__":
    from .cli import main as cli_main

    raise SystemExit(cli_main())
