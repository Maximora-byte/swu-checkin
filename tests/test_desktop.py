"""Desktop safety tests use fake backends and widgets; never contact school services."""

from __future__ import annotations

import sys
import threading
import types
from unittest.mock import Mock

import pytest

from swu_checkin import desktop
from swu_checkin.desktop_errors import ERROR_MESSAGES, DesktopErrorCode
from swu_checkin.models import CheckinResult
from swu_checkin.status import CheckinStatus


@pytest.fixture
def backend(monkeypatch):
    instance = Mock()
    instance.self_test.return_value = 0
    instance.run_scheduled.return_value = 0
    module = types.ModuleType("swu_checkin.desktop_backend")
    module.DesktopBackend = Mock(return_value=instance)
    monkeypatch.setitem(sys.modules, "swu_checkin.desktop_backend", module)
    return instance


def test_self_test_does_not_import_tk_or_load_credentials(monkeypatch, backend):
    monkeypatch.setitem(sys.modules, "tkinter", None)
    assert desktop.main(["--self-test"]) == 0
    backend.self_test.assert_called_once_with()
    backend.load_credentials.assert_not_called()
    backend.check_in.assert_not_called()
    backend.run_scheduled.assert_not_called()


def test_scheduled_only_uses_authorized_backend_task(monkeypatch, backend):
    monkeypatch.setitem(sys.modules, "tkinter", None)
    assert desktop.main(["--scheduled"]) == 0
    backend.run_scheduled.assert_called_once_with()
    backend.check_in.assert_not_called()


def test_run_flag_cannot_bypass_confirmation(backend):
    with pytest.raises(SystemExit) as error:
        desktop.main(["--run"])
    assert error.value.code == 2
    backend.check_in.assert_not_called()
    backend.run_scheduled.assert_not_called()


def test_flags_are_mutually_exclusive(backend):
    with pytest.raises(SystemExit):
        desktop.main(["--scheduled", "--self-test"])
    backend.assert_not_called()


def test_default_launch_opens_window_only(monkeypatch, backend):
    tk = types.ModuleType("tkinter")
    root = Mock()
    tk.Tk = Mock(return_value=root)
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    app = Mock()
    monkeypatch.setattr(desktop, "DesktopApp", app)
    assert desktop.main([]) == 0
    app.assert_called_once_with(root, backend)
    root.mainloop.assert_called_once_with()
    backend.check_in.assert_not_called()
    backend.run_scheduled.assert_not_called()
    backend.diagnose.assert_not_called()


def test_headless_failure_does_not_expose_exception(backend, capsys):
    backend.self_test.side_effect = RuntimeError("password=DO_NOT_PRINT")
    assert desktop.main(["--self-test"]) == 1
    captured = capsys.readouterr()
    assert "DO_NOT_PRINT" not in captured.out + captured.err


def test_controller_rejects_overlap_and_calls_callback_on_poll():
    controller = desktop.DesktopController()
    entered, release = threading.Event(), threading.Event()
    callback = Mock()

    def operation():
        entered.set()
        assert release.wait(3)
        return "完成"

    assert controller.start(operation, callback)
    assert entered.wait(3)
    assert controller.busy
    assert not controller.start(Mock(), Mock())
    callback.assert_not_called()
    release.set()
    event = controller.events.get(timeout=3)
    controller.events.put(event)
    assert controller.poll()
    assert not controller.busy
    callback.assert_called_once_with(True, "完成")
    assert not controller.poll()


def test_controller_sanitizes_exception():
    controller = desktop.DesktopController()
    callback = Mock()
    operation = Mock(side_effect=RuntimeError("token=DO_NOT_PRINT"))
    controller.start(operation, callback)
    event = controller.events.get(timeout=3)
    assert "DO_NOT_PRINT" not in repr(event)
    controller.events.put(event)
    controller.poll()
    callback.assert_called_once_with(False, desktop.SAFE_ERROR)


@pytest.fixture
def app():
    app = desktop.DesktopApp.__new__(desktop.DesktopApp)
    app.root = Mock()
    app.backend = Mock()
    app.dialogs = Mock()
    app.controller = desktop.DesktopController()
    app.username = Mock()
    app.username.get.return_value = "student"
    app.password = Mock()
    app.password.get.return_value = "private-password"
    app.schedule = Mock()
    app.schedule_mode = Mock()
    app.current_schedule_mode = None
    app.schedule_state_known = True
    app.schedule_status = Mock()
    app.schedule_toggle = Mock()
    app.mode_controls = []
    app.run = Mock()
    app.append = Mock()
    return app


def test_declined_manual_confirmation_never_submits(app):
    app.dialogs.askyesno.return_value = False
    app.check_in()
    app.run.assert_not_called()
    app.backend.check_in.assert_not_called()
    assert desktop.MANUAL_CONFIRMATION in app.dialogs.askyesno.call_args.args[1]
    assert app.dialogs.askyesno.call_args.kwargs["default"] == "no"


def test_accepted_manual_confirmation_submits_once(app):
    app.dialogs.askyesno.return_value = True
    app.check_in()
    app.run.call_args.args[1]()
    app.backend.check_in.assert_called_once_with("student", "private-password")
    app.backend.save_credentials.assert_not_called()


def test_probe_never_calls_submit_or_save(app):
    app.probe()
    app.run.call_args.args[1]()
    app.backend.probe.assert_called_once_with("student", "private-password")
    app.backend.check_in.assert_not_called()
    app.backend.save_credentials.assert_not_called()


def test_only_save_button_saves_credentials(app):
    app.save_credentials()
    app.run.call_args.args[1]()
    app.backend.save_credentials.assert_called_once_with("student", "private-password")
    app.backend.check_in.assert_not_called()


def test_blank_credentials_block_action(app):
    app.username.get.return_value = " "
    app.check_in()
    app.run.assert_not_called()
    app.dialogs.askyesno.assert_not_called()


def test_busy_cannot_submit_or_close(app):
    app.controller.busy = True
    app.check_in()
    app.close()
    app.run.assert_not_called()
    app.root.destroy.assert_not_called()
    app.dialogs.showwarning.assert_called_once()


def test_idle_window_closes(app):
    app.close()
    app.root.destroy.assert_called_once_with()


def test_initialization_loads_local_state_only(app):
    app.backend.load_credentials.return_value = ("stored-user", "stored-password")
    app.backend.schedule_mode.return_value = None
    app._restore_local_state()
    value = app.run.call_args.args[1]()
    app.run.call_args.args[2](True, value)
    app.username.set.assert_called_once_with("stored-user")
    app.schedule.set.assert_called_with(False)
    app.backend.check_in.assert_not_called()
    app.backend.probe.assert_not_called()
    app.backend.diagnose.assert_not_called()
    app.backend.save_credentials.assert_not_called()
    app.backend.set_schedule.assert_not_called()


def test_automatic_schedule_requires_confirmation(app):
    app.schedule.get.return_value = True
    app.schedule_mode.get.return_value = "checkin"
    app.dialogs.askyesno.return_value = False
    app.change_schedule()
    app.run.assert_not_called()
    app.backend.set_schedule.assert_not_called()
    app.schedule.set.assert_called_with(False)


def test_automatic_schedule_explicit_consent(app):
    app.schedule.get.return_value = True
    app.schedule_mode.get.return_value = "checkin"
    app.dialogs.askyesno.return_value = True
    app.backend.schedule_mode.return_value = "checkin"
    app.change_schedule()
    assert "自动签到" in app.run.call_args.args[1]()
    app.backend.set_schedule.assert_called_once_with(True, mode="checkin")


def test_readonly_schedule_is_explicit_but_never_submits(app):
    app.schedule.get.return_value = True
    app.schedule_mode.get.return_value = "probe"
    app.backend.schedule_mode.return_value = "probe"
    app.change_schedule()
    app.run.call_args.args[1]()
    app.backend.set_schedule.assert_called_once_with(True, mode="probe")
    app.backend.check_in.assert_not_called()


def test_schedule_disable_does_not_require_submission_consent(app):
    app.schedule.get.return_value = False
    app.schedule_mode.get.return_value = "checkin"
    app.backend.schedule_mode.return_value = None
    app.change_schedule()
    app.run.call_args.args[1]()
    app.backend.set_schedule.assert_called_once_with(False, mode="checkin")
    app.dialogs.askyesno.assert_not_called()


def test_safe_result_rendering():
    result = CheckinResult.from_status(CheckinStatus.PROBE_PENDING, attempts=1, duration_ms=5, mode="probe")
    assert desktop.describe_result(result) == "只读检测结果：检测到待签到任务（未提交）（尝试 1 次，用时 5 毫秒）"


def test_controller_exposes_only_reviewed_errors():
    controller = desktop.DesktopController()
    callback = Mock()
    controller.start(Mock(side_effect=desktop.DesktopError(DesktopErrorCode.LEGACY_TASK_EXISTS)), callback)
    event = controller.events.get(timeout=3)
    controller.events.put(event)
    controller.poll()
    callback.assert_called_once_with(False, DesktopErrorCode.LEGACY_TASK_EXISTS)
    assert desktop.describe_result(callback.call_args.args[1]) == ERROR_MESSAGES[DesktopErrorCode.LEGACY_TASK_EXISTS]


def test_manual_result_warns_if_local_record_failed(app):
    app.dialogs.askyesno.return_value = True
    app.backend.last_warning = "签到结果已返回，但本地状态未能保存。"
    app.check_in()
    app.run.call_args.args[2](True, None)
    app.append.assert_called_once_with(app.backend.last_warning)


def test_startup_local_reads_use_worker(app):
    app._restore_local_state()
    app.backend.load_credentials.assert_not_called()
    app.backend.schedule_mode.assert_not_called()
    app.run.assert_called_once()


def test_active_schedule_mode_cannot_look_like_another_mode(app):
    app.current_schedule_mode = "checkin"
    control = Mock()
    app.mode_controls = [control]
    app._sync_schedule()
    app.schedule_mode.set.assert_called_once_with("checkin")
    control.configure.assert_called_once_with(state="disabled")


@pytest.mark.parametrize(
    "secret",
    ["server response raw", "https://host.invalid/?token=secret", "password-secret", r"C:\Users\private\token"],
)
def test_desktop_error_rejects_external_text(secret):
    with pytest.raises(TypeError, match="DesktopError requires a DesktopErrorCode") as caught:
        desktop.DesktopError(secret)
    assert secret not in str(caught.value)


@pytest.mark.parametrize("typed", [False, True])
def test_controller_never_renders_exception_text(typed):
    secret = "server-body https://host.invalid/?token=secret password-secret"
    error = desktop.DesktopError(DesktopErrorCode.CONFIG_INVALID) if typed else RuntimeError(secret)
    error.args = (secret,)
    controller = desktop.DesktopController()
    callback = Mock()
    controller.start(Mock(side_effect=error), callback)
    event = controller.events.get(timeout=3)
    controller.events.put(event)
    controller.poll()
    expected = DesktopErrorCode.CONFIG_INVALID if typed else desktop.SAFE_ERROR
    callback.assert_called_once_with(False, expected)
    assert secret not in desktop.describe_result(callback.call_args.args[1])


@pytest.mark.parametrize("typed", [False, True])
def test_startup_dialog_uses_fixed_error_only(monkeypatch, backend, typed):
    secret = "raw response https://host.invalid/?token=secret password-secret"
    error = desktop.DesktopError(DesktopErrorCode.WINDOWS_REQUIRED) if typed else RuntimeError(secret)
    error.args = (secret,)
    monkeypatch.setattr(sys.modules["swu_checkin.desktop_backend"].DesktopBackend, "side_effect", error)
    tk = types.ModuleType("tkinter")
    tk.messagebox = Mock()
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    assert desktop.main([]) == 1
    expected = ERROR_MESSAGES[DesktopErrorCode.WINDOWS_REQUIRED] if typed else desktop.SAFE_ERROR
    tk.messagebox.showerror.assert_called_once_with("无法启动签到助手", expected)


def test_error_message_vocabulary_is_complete_and_immutable():
    assert set(ERROR_MESSAGES) == set(DesktopErrorCode)
    with pytest.raises(TypeError):
        ERROR_MESSAGES[DesktopErrorCode.WINDOWS_REQUIRED] = "external"


def test_unknown_schedule_restore_never_displays_disabled(app):
    app._restore_local_state()
    restored = app.run.call_args.args[2]
    restored(False, "无法确认计划任务状态")
    assert app.schedule_state_known is False
    app.schedule_status.set.assert_called_with("计划任务状态未知：无法确认计划任务状态")
    app.schedule_toggle.configure.assert_called_with(state="disabled")
    app.schedule.set.assert_not_called()


def test_unknown_schedule_state_cannot_enable_or_disable(app):
    app.schedule_state_known = False
    app.change_schedule()
    app.backend.set_schedule.assert_not_called()
    app.run.assert_not_called()
    app.schedule_status.set.assert_called_with("计划任务状态未知：无法确认计划任务状态")


def test_schedule_change_query_failure_marks_unknown(app):
    app.schedule.get.return_value = False
    app.change_schedule()
    changed = app.run.call_args.args[2]
    changed(False, DesktopErrorCode.TASK_QUERY_FAILED)
    assert app.schedule_state_known is False
    app.schedule_status.set.assert_called_with("计划任务状态未知：无法确认计划任务状态")


@pytest.mark.parametrize(
    "code",
    [
        DesktopErrorCode.DIAGNOSIS_FAILED,
        DesktopErrorCode.SAVED_CREDENTIALS_REQUIRED,
        DesktopErrorCode.LEGACY_TASK_EXISTS,
        DesktopErrorCode.MODE_REQUIRED,
        DesktopErrorCode.FROZEN_REQUIRED,
    ],
)
@pytest.mark.parametrize("previous_mode", [None, "probe", "checkin"])
def test_known_schedule_failure_preserves_confirmed_state(app, code, previous_mode):
    app.current_schedule_mode = previous_mode
    app.schedule.get.return_value = False
    app.change_schedule()
    changed = app.run.call_args.args[2]
    changed(False, code)
    assert app.schedule_state_known is True
    assert app.current_schedule_mode == previous_mode
    app.schedule_toggle.configure.assert_called_with(state="normal")
    assert desktop.describe_result(code) == ERROR_MESSAGES[code]


def test_generic_schedule_failure_keeps_previous_state_and_redacts(app):
    app.current_schedule_mode = "probe"
    app.schedule.get.return_value = False
    app.change_schedule()
    change, changed = app.run.call_args.args[1:]
    app.backend.set_schedule.side_effect = RuntimeError("token-secret https://private.invalid/?password=secret")
    callback = Mock(side_effect=changed)
    app.controller.start(change, callback)
    event = app.controller.events.get(timeout=3)
    app.controller.events.put(event)
    app.controller.poll()
    callback.assert_called_once_with(False, desktop.SAFE_ERROR)
    assert app.schedule_state_known is True
    assert app.current_schedule_mode == "probe"


@pytest.mark.parametrize("code", list(DesktopErrorCode))
def test_reviewed_error_messages_render_unchanged(code):
    assert desktop.describe_result(code) == ERROR_MESSAGES[code]


def test_controller_rejects_tampered_error_code():
    error = desktop.DesktopError(DesktopErrorCode.CONFIG_INVALID)
    error.code = "token-secret server-response"
    controller = desktop.DesktopController()
    callback = Mock()
    controller.start(Mock(side_effect=error), callback)
    event = controller.events.get(timeout=3)
    controller.events.put(event)
    controller.poll()
    callback.assert_called_once_with(False, desktop.SAFE_ERROR)


@pytest.mark.parametrize("code", [DesktopErrorCode.TASK_QUERY_FAILED, DesktopErrorCode.TASK_STATE_UNCERTAIN])
def test_uncertain_schedule_completion_disables_without_claiming_state(app, code):
    app.current_schedule_mode = "probe"
    app.mode_controls = [Mock()]
    app.schedule.get.return_value = False
    app.change_schedule()
    changed = app.run.call_args.args[2]
    changed(False, code)
    assert app.schedule_state_known is False
    app.schedule_toggle.configure.assert_called_with(state="disabled")
    app.mode_controls[0].configure.assert_called_with(state="disabled")
    app.schedule.set.assert_not_called()
    app.schedule_status.set.assert_called_with("计划任务状态未知：无法确认计划任务状态")


@pytest.mark.parametrize(
    "failure", [RuntimeError("token-secret"), desktop.DesktopError(DesktopErrorCode.CONFIG_INVALID)]
)
def test_post_backend_mutation_gui_verification_failure_is_uncertain(app, failure):
    app.schedule.get.return_value = False
    app.backend.schedule_mode.side_effect = failure
    app.change_schedule()
    with pytest.raises(desktop.DesktopError) as caught:
        app.run.call_args.args[1]()
    assert caught.value.code is DesktopErrorCode.TASK_STATE_UNCERTAIN
    assert "secret" not in desktop.describe_result(caught.value.code)
