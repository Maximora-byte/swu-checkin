"""macOS adapter tests are offline and never touch the user's Keychain."""

import sys
import types
from unittest.mock import Mock

import pytest

from swu_checkin import desktop, desktop_operations, macos_backend
from swu_checkin.desktop_errors import DesktopError, DesktopErrorCode
from swu_checkin.macos_keychain import KeychainError, KeychainErrorCode
from swu_checkin.models import CheckinResult
from swu_checkin.runtime_lock import RuntimeLock, RuntimeLockBusy
from swu_checkin.status import CheckinStatus


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("SWUDK_LOCK_FILE", str(tmp_path / "shared.lock"))
    monkeypatch.delenv("SWUDK_PROBE_ONLY", raising=False)
    for name in ("run_checkin", "run_probe", "CheckinService"):
        monkeypatch.setattr(desktop_operations, name, Mock(side_effect=AssertionError("Unexpected network")))
    return macos_backend.MacOSBackend(tmp_path / "app", keychain=Mock())


def result(mode="checkin"):
    return CheckinResult.from_status(
        CheckinStatus.SUCCESS if mode == "checkin" else CheckinStatus.PROBE_PENDING,
        attempts=1,
        duration_ms=3,
        mode=mode,
    )


def test_construct_does_not_access_keychain_or_create_files(backend):
    backend.keychain.assert_not_called()
    assert backend.keychain.mock_calls == []
    assert not backend.root.exists()


def test_memory_token_cache_cannot_write_plaintext_or_cross_instance(backend, tmp_path):
    tokens = backend._options()["token_store"]
    tokens.save("synthetic", "secret-token", "123")
    assert tokens.get("synthetic").token == "secret-token"
    assert tokens.get("other") is None
    assert macos_backend.MemoryTokenStore().get("synthetic") is None
    assert not backend.root.exists()
    tokens.delete("synthetic")
    assert tokens.get("synthetic") is None


def test_explicit_credential_operations_and_clear(backend):
    backend.tokens.save("synthetic", "token", "123")
    backend.save_credentials("synthetic", "password")
    backend.keychain.save.assert_called_once_with("synthetic", "password")
    assert backend.tokens.get("synthetic") is None
    backend.keychain.load.return_value = ("synthetic", "password")
    assert backend.load_credentials() == ("synthetic", "password")
    backend.tokens.save("synthetic", "token", "123")
    backend.delete_credentials()
    backend.keychain.delete.assert_called_once_with()
    assert backend.tokens.get("synthetic") is None
    assert not backend.root.exists()


@pytest.mark.parametrize(
    "method,args", [("save_credentials", ("user", "secret")), ("load_credentials", ()), ("delete_credentials", ())]
)
@pytest.mark.parametrize("code", list(KeychainErrorCode))
def test_keychain_errors_are_closed_and_safe(backend, method, args, code):
    operation = {"save_credentials": "save", "load_credentials": "load", "delete_credentials": "delete"}[method]
    getattr(backend.keychain, operation).side_effect = KeychainError(code)
    with pytest.raises(DesktopError) as caught:
        getattr(backend, method)(*args)
    assert caught.value.code == macos_backend.KEYCHAIN_ERRORS[code]
    assert not backend.root.exists()


def test_unexpected_keychain_exception_never_leaks_or_falls_back(backend):
    backend.keychain.save.side_effect = RuntimeError("private-password")
    with pytest.raises(DesktopError) as caught:
        backend.save_credentials("user", "private-password")
    assert caught.value.code == DesktopErrorCode.KEYCHAIN_OPERATION_FAILED
    assert "private-password" not in str(caught.value)
    assert not backend.root.exists()


def test_mac_formal_entry_uses_same_shared_lock_and_exact_service_once(backend, monkeypatch):
    submit = Mock(return_value=result())
    monkeypatch.setattr(desktop_operations, "run_checkin", submit)
    with RuntimeLock():
        with pytest.raises(RuntimeLockBusy):
            backend.check_in("synthetic", "password")
    submit.assert_not_called()
    assert backend.check_in("synthetic", "password").code == CheckinStatus.SUCCESS
    submit.assert_called_once_with("synthetic", "password", 10, token_store=backend.tokens)
    assert backend.keychain.mock_calls == []


def test_readonly_switch_blocks_formal_mac(backend, monkeypatch):
    monkeypatch.setenv("SWUDK_PROBE_ONLY", "1")
    with pytest.raises(DesktopError) as caught:
        backend.check_in("synthetic", "password")
    assert caught.value.code == DesktopErrorCode.READONLY_ENABLED


def test_probe_reuses_service_without_submit(backend, monkeypatch):
    probe = Mock(return_value=result("probe"))
    monkeypatch.setattr(desktop_operations, "run_probe", probe)
    assert backend.probe("synthetic", "password").mode == "probe"
    probe.assert_called_once_with("synthetic", "password", 10, token_store=backend.tokens)
    desktop_operations.run_checkin.assert_not_called()
    assert not backend.root.exists()


def test_mac_has_no_scheduler(backend):
    assert backend.run_scheduled() == 1
    assert backend.keychain.mock_calls == []
    assert not hasattr(backend, "set_schedule")


@pytest.fixture
def app(backend):
    app = desktop.DesktopApp.__new__(desktop.DesktopApp)
    app.presentation = desktop.MACOS_PRESENTATION
    app.backend = backend
    app.root = Mock()
    app.dialogs = Mock()
    app.controller = desktop.DesktopController()
    app.username = Mock()
    app.password = Mock()
    app.run = Mock()
    app.append = Mock()
    return app


def test_mac_startup_does_not_read_credentials_or_network(app):
    app._restore_local_state()
    app._sync_schedule()
    app.change_schedule()
    app.run.assert_not_called()
    assert app.backend.keychain.mock_calls == []


def test_mac_load_is_explicit_and_does_not_display_credentials(app):
    app.backend.keychain.load.return_value = ("synthetic", "secret-password")
    app.load_credentials()
    value = app.run.call_args.args[1]()
    app.run.call_args.args[2](True, value)
    app.username.set.assert_called_once_with("synthetic")
    app.password.set.assert_called_once_with("secret-password")
    assert "secret-password" not in repr(app.append.call_args_list)
    assert "secret-password" not in desktop.describe_result(value)


def test_mac_clear_cancel_and_busy_have_no_side_effect(app):
    app.dialogs.askyesno.return_value = False
    app.delete_credentials()
    app.run.assert_not_called()
    assert app.dialogs.askyesno.call_args.kwargs["default"] == "no"
    app.controller.busy = True
    app.load_credentials()
    app.delete_credentials()
    app.run.assert_not_called()


def test_mac_clear_is_explicit_and_clears_inputs_only_after_success(app):
    app.dialogs.askyesno.return_value = True
    app.delete_credentials()
    app.run.call_args.args[2](False, None)
    app.username.set.assert_not_called()
    app.run.call_args.args[1]()
    app.run.call_args.args[2](True, None)
    app.username.set.assert_called_once_with("")
    app.password.set.assert_called_once_with("")
    app.backend.keychain.delete.assert_called_once_with()


def test_mac_scheduled_flag_rejected_before_construct_or_tk(monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    factory = Mock()
    monkeypatch.setattr(macos_backend, "MacOSBackend", factory)
    monkeypatch.setitem(sys.modules, "tkinter", None)
    assert desktop.main(["--scheduled"]) == 1
    factory.assert_not_called()


def test_mac_launch_selects_adapter_and_gui_without_network(monkeypatch, backend):
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    monkeypatch.setattr(macos_backend, "MacOSBackend", Mock(return_value=backend))
    tk = types.ModuleType("tkinter")
    root = Mock()
    tk.Tk = Mock(return_value=root)
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    gui = Mock()
    monkeypatch.setattr(desktop, "DesktopApp", gui)
    assert desktop.main([]) == 0
    gui.assert_called_once_with(root, backend, desktop.MACOS_PRESENTATION)
    assert backend.keychain.mock_calls == []
    desktop_operations.run_checkin.assert_not_called()
    root.mainloop.assert_called_once_with()
