import stat
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from swu_checkin import token_store
from swu_checkin.api_models import DormitoryInfo, LeaveRecords, StudentProfile
from swu_checkin.auth import AuthError, AuthFailureReason
from swu_checkin.service import CheckinService
from swu_checkin.status import CheckinStatus
from swu_checkin.token_store import CachedToken, TokenStore, TokenStoreError


class _ReversingProtector:
    """Test double for the platform encryption boundary."""

    def protect(self, data: bytes) -> bytes:
        return data[::-1]

    def unprotect(self, data: bytes) -> bytes:
        return data[::-1]


def _http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError("sensitive response text", response=response)


def _diagnostic_client() -> Mock:
    client = Mock()
    client.get_student_id.return_value = "20260000000"
    client.get_leave_record_set.return_value = LeaveRecords.from_items([])
    client.get_student_profile.return_value = StudentProfile("20260000000")
    client.get_dormitory_info.return_value = DormitoryInfo(29.0, 106.0, "building", "room")
    client.get_transition.return_value = None
    return client


def test_posix_token_cache_is_atomic_and_owner_only(tmp_path: Path):
    path = tmp_path / "cache" / "auth-token-cache"
    store = TokenStore(path)

    store.save("student", "bearer-secret", "20260000000")

    assert store.get("student") == CachedToken("bearer-secret", "20260000000")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(path.parent.glob(f".{path.name}.*"))
    assert b'"student"' not in path.read_bytes()


def test_cache_is_single_account_and_new_username_replaces_old(tmp_path: Path):
    store = TokenStore(tmp_path / "auth-token-cache")
    store.save("first", "first-token", "first-id")

    store.save("second", "second-token", "second-id")

    assert store.get("first") is None
    assert store.get("second") == CachedToken("second-token", "second-id")


def test_posix_cache_refuses_broad_permissions(tmp_path: Path):
    path = tmp_path / "auth-token-cache"
    store = TokenStore(path)
    store.save("student", "bearer-secret", "20260000000")
    path.chmod(0o644)

    with pytest.raises(TokenStoreError, match="permissions"):
        store.get("student")


def test_cache_refuses_symbolic_link(tmp_path: Path):
    target = tmp_path / "target"
    target.write_text("not a cache", encoding="utf-8")
    path = tmp_path / "auth-token-cache"
    path.symlink_to(target)

    with pytest.raises(TokenStoreError, match="symbolic link"):
        TokenStore(path).get("student")


def test_windows_dpapi_backend_boundary_never_writes_plaintext(tmp_path: Path):
    path = tmp_path / "auth-token-cache"
    store = TokenStore(path, protector=_ReversingProtector())

    store.save("student", "bearer-secret", "20260000000")

    assert b"bearer-secret" not in path.read_bytes()
    assert store.get("student") == CachedToken("bearer-secret", "20260000000")


def test_windows_default_selects_current_user_dpapi(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(token_store.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("SWUDK_STATUS_FILE", raising=False)

    store = TokenStore()

    assert isinstance(store._protector, token_store.WindowsDpapiProtector)
    assert store.path == tmp_path / "SWUCheckin" / "auth-token-cache"


def test_cache_hit_is_validated_and_skips_login():
    store = Mock()
    store.get.return_value = CachedToken("cached-token", "20260000000")
    client = Mock()
    client.get_student_id.return_value = "20260000000"
    login = Mock(side_effect=AssertionError("login must not run"))
    service = CheckinService(
        token_provider=login,
        client_factory=lambda *_args: client,
        token_store=store,
    )

    assert service._authenticated_client("20260000000", "password") is client
    login.assert_not_called()
    store.save.assert_not_called()


@pytest.mark.parametrize("status_code", [401, 403])
def test_cached_auth_rejection_is_deleted_then_login_is_validated_and_saved(status_code: int):
    store = Mock()
    store.get.return_value = CachedToken("stale-token", "20260000000")
    stale_client = Mock()
    stale_client.get_student_id.side_effect = _http_error(status_code)
    fresh_client = Mock()
    fresh_client.get_student_id.return_value = "20260000000"
    clients = iter([stale_client, fresh_client])
    login = Mock(return_value="fresh-token")
    service = CheckinService(
        token_provider=login,
        client_factory=lambda *_args: next(clients),
        token_store=store,
    )

    assert service._authenticated_client("20260000000", "password") is fresh_client
    store.delete.assert_called_once_with("20260000000")
    login.assert_called_once_with("20260000000", "password", 10)
    store.save.assert_called_once_with("20260000000", "fresh-token", "20260000000")


@pytest.mark.parametrize(
    "failure",
    [
        requests.Timeout("timeout password=secret"),
        requests.ConnectionError("connection token=secret"),
        _http_error(503),
    ],
)
def test_transient_cache_validation_failure_keeps_cache_and_skips_login(failure: requests.RequestException):
    store = Mock()
    store.get.return_value = CachedToken("cached-token", "20260000000")
    client = Mock()
    client.get_student_id.side_effect = failure
    login = Mock()
    service = CheckinService(
        token_provider=login,
        client_factory=lambda *_args: client,
        token_store=store,
    )

    with pytest.raises(AuthError) as caught:
        service._authenticated_client("20260000000", "password")

    assert caught.value.reason is AuthFailureReason.NETWORK_ERROR
    assert "secret" not in str(caught.value)
    store.delete.assert_not_called()
    login.assert_not_called()


def test_candidate_token_is_not_saved_before_identity_validation():
    store = Mock()
    store.get.return_value = None
    client = Mock()
    client.get_student_id.side_effect = ValueError("malformed profile")
    service = CheckinService(
        token_provider=Mock(return_value="candidate-token"),
        client_factory=lambda *_args: client,
        token_store=store,
    )

    with pytest.raises(AuthError) as caught:
        service._authenticated_client("20260000000", "password")

    assert caught.value.reason is AuthFailureReason.TOKEN_EXCHANGE_FAILED
    store.save.assert_not_called()


def test_fresh_token_identity_mismatch_fails_closed_without_saving():
    store = Mock()
    store.get.return_value = None
    client = Mock()
    client.get_student_id.return_value = "wrong-student"
    service = CheckinService(
        token_provider=Mock(return_value="candidate-token"),
        client_factory=lambda *_args: client,
        token_store=store,
    )

    with pytest.raises(AuthError) as caught:
        service._authenticated_client("20260000000", "password")

    assert caught.value.reason is AuthFailureReason.TOKEN_EXCHANGE_FAILED
    store.delete.assert_not_called()
    store.save.assert_not_called()


def test_cached_identity_must_also_match_requested_username_before_use():
    store = Mock()
    store.get.return_value = CachedToken("cached-token", "other-student")
    cached_client = Mock()
    cached_client.get_student_id.return_value = "other-student"
    fresh_client = Mock()
    fresh_client.get_student_id.return_value = "20260000000"
    clients = iter([cached_client, fresh_client])
    service = CheckinService(
        token_provider=Mock(return_value="fresh-token"),
        client_factory=lambda *_args: next(clients),
        token_store=store,
    )

    assert service._authenticated_client("20260000000", "password") is fresh_client
    store.delete.assert_called_once_with("20260000000")
    store.save.assert_called_once_with("20260000000", "fresh-token", "20260000000")


def test_wrong_identity_after_stale_cache_fails_closed_without_saving():
    store = Mock()
    store.get.return_value = CachedToken("stale-token", "20260000000")
    stale_client = Mock()
    stale_client.get_student_id.side_effect = _http_error(401)
    wrong_client = Mock()
    wrong_client.get_student_id.return_value = "wrong-student"
    clients = iter([stale_client, wrong_client])
    service = CheckinService(
        token_provider=Mock(return_value="wrong-token"),
        client_factory=lambda *_args: next(clients),
        token_store=store,
    )

    with pytest.raises(AuthError) as caught:
        service._authenticated_client("20260000000", "password")

    assert caught.value.reason is AuthFailureReason.TOKEN_EXCHANGE_FAILED
    store.delete.assert_called_once_with("20260000000")
    store.save.assert_not_called()


def test_doctor_forces_fresh_auth_even_when_valid_cache_exists():
    store = Mock()
    store.get.return_value = CachedToken("cached-token", "20260000000")
    login = Mock(side_effect=AuthError(AuthFailureReason.CREDENTIAL_REJECTED))
    service = CheckinService(token_provider=login, token_store=store)

    report = service.diagnose("20260000000", "wrong-password")

    assert report.authentication is False
    login.assert_called_once_with("20260000000", "wrong-password", 10)
    store.get.assert_not_called()
    store.save.assert_not_called()
    store.delete.assert_not_called()


def test_doctor_fresh_auth_success_never_reads_or_mutates_cache():
    store = Mock()
    client = _diagnostic_client()
    login = Mock(return_value="fresh-token")
    service = CheckinService(
        token_provider=login,
        client_factory=lambda *_args: client,
        token_store=store,
    )

    report = service.diagnose("20260000000", "password")

    assert report.authentication is True
    login.assert_called_once_with("20260000000", "password", 10)
    store.get.assert_not_called()
    store.save.assert_not_called()
    store.delete.assert_not_called()
    client.submit_checkin_form.assert_not_called()


@pytest.mark.parametrize(
    "failing_method",
    ["get_leave_record_set", "get_dormitory_info", "get_transition"],
)
def test_doctor_api_failure_after_fresh_auth_never_saves_cache(failing_method: str):
    store = Mock()
    client = _diagnostic_client()
    getattr(client, failing_method).side_effect = ValueError("malformed read-only response")
    service = CheckinService(
        token_provider=Mock(return_value="fresh-token"),
        client_factory=lambda *_args: client,
        token_store=store,
    )

    report = service.diagnose("20260000000", "password")

    assert report.authentication is True
    store.get.assert_not_called()
    store.save.assert_not_called()
    store.delete.assert_not_called()
    client.submit_checkin_form.assert_not_called()


def test_normal_fresh_login_validates_identity_then_saves_cache():
    store = Mock()
    store.get.return_value = None
    client = _diagnostic_client()
    login = Mock(return_value="fresh-token")
    service = CheckinService(
        token_provider=login,
        client_factory=lambda *_args: client,
        token_store=store,
    )

    assert service.check_in_once("20260000000", "password") is CheckinStatus.NO_TASK

    store.get.assert_called_once_with("20260000000")
    login.assert_called_once_with("20260000000", "password", 10)
    client.get_student_id.assert_called_once_with()
    store.save.assert_called_once_with("20260000000", "fresh-token", "20260000000")


@pytest.mark.parametrize("method_name", ["check_in_once", "probe_once"])
def test_normal_run_and_probe_still_use_valid_cache(method_name: str):
    store = Mock()
    store.get.return_value = CachedToken("cached-token", "20260000000")
    client = Mock()
    client.get_student_id.return_value = "20260000000"
    client.get_leave_record_set.return_value = LeaveRecords.from_items([])
    client.get_transition.return_value = None
    login = Mock(side_effect=AssertionError("runtime must use the valid cache"))
    service = CheckinService(
        token_provider=login,
        client_factory=lambda *_args: client,
        token_store=store,
    )

    status = getattr(service, method_name)("20260000000", "password")

    assert status is CheckinStatus.NO_TASK
    store.get.assert_called_once_with("20260000000")
    login.assert_not_called()
