import stat
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from swu_checkin import token_store
from swu_checkin.auth import AuthError, AuthFailureReason
from swu_checkin.service import CheckinService
from swu_checkin.token_store import CachedToken, TokenStore, TokenStoreError


class _ReversingProtector:
    """Test double for the platform encryption boundary."""

    def protect(self, data: bytes) -> bytes:
        return data[::-1]

    def unprotect(self, data: bytes) -> bytes:
        return data[::-1]


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

    assert service._authenticated_client("student", "password") is client
    login.assert_not_called()
    store.save.assert_not_called()


def test_invalid_cache_is_deleted_then_login_is_validated_and_saved():
    store = Mock()
    store.get.return_value = CachedToken("stale-token", "old-student")
    stale_client = Mock()
    stale_client.get_student_id.side_effect = ValueError("invalid token")
    fresh_client = Mock()
    fresh_client.get_student_id.return_value = "20260000000"
    clients = iter([stale_client, fresh_client])
    login = Mock(return_value="fresh-token")
    service = CheckinService(
        token_provider=login,
        client_factory=lambda *_args: next(clients),
        token_store=store,
    )

    assert service._authenticated_client("student", "password") is fresh_client
    store.delete.assert_called_once_with("student")
    login.assert_called_once_with("student", "password", 10)
    store.save.assert_called_once_with("student", "fresh-token", "20260000000")


def test_cache_validation_timeout_keeps_cache_and_does_not_mask_network_error():
    store = Mock()
    store.get.return_value = CachedToken("cached-token", "20260000000")
    client = Mock()
    client.get_student_id.side_effect = requests.Timeout("ticket=secret")
    login = Mock()
    service = CheckinService(
        token_provider=login,
        client_factory=lambda *_args: client,
        token_store=store,
    )

    with pytest.raises(AuthError) as caught:
        service._authenticated_client("student", "password")

    assert caught.value.reason is AuthFailureReason.NETWORK_ERROR
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
        service._authenticated_client("student", "password")

    assert caught.value.reason is AuthFailureReason.TOKEN_EXCHANGE_FAILED
    store.save.assert_not_called()


def test_cache_identity_mismatch_is_deleted_and_reauthenticated():
    store = Mock()
    store.get.return_value = CachedToken("cached-token", "expected-student")
    cached_client = Mock()
    cached_client.get_student_id.return_value = "different-student"
    fresh_client = Mock()
    fresh_client.get_student_id.return_value = "fresh-student"
    clients = iter([cached_client, fresh_client])
    service = CheckinService(
        token_provider=Mock(return_value="fresh-token"),
        client_factory=lambda *_args: next(clients),
        token_store=store,
    )

    assert service._authenticated_client("student", "password") is fresh_client
    store.delete.assert_called_once_with("student")
    store.save.assert_called_once_with("student", "fresh-token", "fresh-student")
