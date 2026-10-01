"""Chinese Windows desktop entry point; launching never submits a check-in."""

from __future__ import annotations

import argparse
import queue
import threading
from collections.abc import Callable, Sequence
from typing import Any

from .desktop_errors import ERROR_MESSAGES, DesktopError, DesktopErrorCode
from .models import CheckinResult

LOCATION_WARNING = "本工具不测量真实 GPS；提交使用学校记录的固定寝室坐标，不代表您当前的位置。"
MANUAL_CONFIRMATION = "本人当前在寝且符合学校规则，了解本工具不测量真实GPS"
SCHEDULE_CONFIRMATION = (
    "启用后，计划任务会使用已保存账号自动提交签到，不会每次询问。\n"
    "仅在您能确保每次运行时本人在寝且符合学校规则的情况下启用；不满足时须提前关闭。\n\n"
    + LOCATION_WARNING
    + "\n\n确认授权自动签到？"
)
SAFE_ERROR = "操作未完成。请检查网络、账号、Windows 权限或本地配置后重试；未显示敏感诊断信息。"


class DesktopController:
    """Run one backend operation at a time, delivering results on the UI thread."""

    def __init__(self) -> None:
        self.busy = False
        self.events: queue.Queue[tuple[bool, Any]] = queue.Queue()
        self.callback: Callable[[bool, Any], None] | None = None

    def start(self, operation: Callable[[], Any], callback: Callable[[bool, Any], None]) -> bool:
        if self.busy:
            return False
        self.busy = True
        self.callback = callback

        def work() -> None:
            try:
                value = operation()
            except DesktopError as error:
                self.events.put((False, error.code if isinstance(error.code, DesktopErrorCode) else SAFE_ERROR))
            except Exception:
                # Exception strings may contain passwords, URLs, tokens, or server payloads.
                self.events.put((False, SAFE_ERROR))
            else:
                self.events.put((True, value))

        threading.Thread(target=work, name="desktop-operation", daemon=True).start()
        return True

    def poll(self) -> bool:
        try:
            success, value = self.events.get_nowait()
        except queue.Empty:
            return False
        self.busy = False
        callback, self.callback = self.callback, None
        if callback is not None:
            callback(success, value)
        return True


def describe_result(value: object) -> str:
    if isinstance(value, DesktopErrorCode):
        return ERROR_MESSAGES[value]
    if isinstance(value, CheckinResult):
        operation = "只读检测" if value.mode == "probe" else "签到"
        return f"{operation}结果：{value.message}（尝试 {value.attempts} 次，用时 {value.duration_ms} 毫秒）"
    if isinstance(value, str):
        return value
    return "操作完成"


class DesktopApp:
    def __init__(self, root: Any, backend: Any) -> None:
        # Headless --self-test and --scheduled never import Tk or open a window.
        import tkinter as tk
        from tkinter import messagebox, ttk

        self.root = root
        self.backend = backend
        self.dialogs = messagebox
        self.controller = DesktopController()
        self.controls: list[Any] = []
        root.title("西南大学寝室签到助手")
        root.geometry("720x720")
        root.minsize(680, 660)
        root.protocol("WM_DELETE_WINDOW", self.close)
        panel = ttk.Frame(root, padding=20)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="西南大学寝室签到助手", font=("Microsoft YaHei UI", 17, "bold")).pack(anchor="w")
        ttk.Label(panel, text="打开软件不会联网或提交签到。请先检测，再按需手动执行。", wraplength=620).pack(
            anchor="w", pady=(6, 12)
        )
        ttk.Label(panel, text=LOCATION_WARNING, foreground="#9b3500", wraplength=620).pack(anchor="w", pady=(0, 12))
        fields = ttk.Frame(panel)
        fields.pack(fill="x")
        fields.columnconfigure(1, weight=1)
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        for row, (label, variable, hidden) in enumerate(
            (("学号 / 账号", self.username, False), ("密码", self.password, True))
        ):
            ttk.Label(fields, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            entry = ttk.Entry(fields, textvariable=variable, show="•" if hidden else "")
            entry.grid(row=row, column=1, sticky="ew", pady=5)
            self.controls.append(entry)
        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", pady=12)
        for text, command in (
            ("保存账号", self.save_credentials),
            ("检测登录", self.diagnose),
            ("只读检测", self.probe),
            ("手动签到…", self.check_in),
            ("本地状态", self.local_status),
        ):
            button = ttk.Button(buttons, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            self.controls.append(button)
        ttk.Label(panel, text="只有点击“保存账号”才会保存；使用 Windows 当前用户加密保护。", wraplength=620).pack(
            anchor="w"
        )
        schedule = ttk.LabelFrame(panel, text="Windows 每日计划任务（默认关闭）", padding=10)
        schedule.pack(fill="x", pady=12)
        self.schedule = tk.BooleanVar(value=False)
        self.schedule_mode = tk.StringVar(value="probe")
        self.mode_controls: list[Any] = []
        for text, mode in (("只读检测（不提交）", "probe"), ("自动签到（会提交）", "checkin")):
            control = ttk.Radiobutton(schedule, text=text, variable=self.schedule_mode, value=mode)
            control.pack(anchor="w")
            self.controls.append(control)
            self.mode_controls.append(control)
        self.schedule_toggle = ttk.Checkbutton(
            schedule, text="启用每日计划任务", variable=self.schedule, command=self.change_schedule
        )
        self.schedule_toggle.pack(anchor="w", pady=(5, 0))
        self.controls.append(self.schedule_toggle)
        self.schedule_status = tk.StringVar(value="计划任务状态未知（正在读取本地状态）")
        ttk.Label(schedule, textvariable=self.schedule_status).pack(anchor="w")
        ttk.Label(
            schedule,
            text="北京时间每日 21:15 / 21:45；电脑须开机联网且用户已登录。睡眠 / 关机不保证运行。\n"
            "切换模式前请先关闭任务，再选择模式并重新启用。计划任务需要先保存账号。",
            wraplength=640,
        ).pack(anchor="w", pady=(5, 0))
        self.progress = tk.StringVar(value="就绪（未联网）")
        ttk.Label(panel, textvariable=self.progress).pack(anchor="w", pady=(0, 5))
        self.output = tk.Text(panel, height=9, wrap="word", state="disabled", font=("Microsoft YaHei UI", 10))
        self.output.pack(fill="both", expand=True)
        self.schedule_state_known = False
        self.current_schedule_mode: str | None = None
        self._restore_local_state()
        root.after(100, self._poll)

    def _restore_local_state(self) -> None:
        def load() -> tuple[tuple[str, str] | None, str | None]:
            return self.backend.load_credentials(), self.backend.schedule_mode()

        def restored(success: bool, value: Any) -> None:
            if not success:
                self.schedule_state_known = False
                self._sync_schedule()
                return
            self.schedule_state_known = True
            credentials, self.current_schedule_mode = value
            if credentials:
                self.username.set(credentials[0])
                self.password.set(credentials[1])
            self._sync_schedule()
            self.append("已读取本地配置；尚未连接学校服务。")

        self.run("读取本地配置（不联网）", load, restored)

    def _sync_schedule(self) -> None:
        if not self.schedule_state_known:
            self.schedule_status.set("计划任务状态未知：无法确认计划任务状态")
            self.schedule_toggle.configure(state="disabled")
            for control in self.mode_controls:
                control.configure(state="disabled")
            return
        self.schedule_status.set("计划任务已启用" if self.current_schedule_mode else "计划任务已关闭")
        self.schedule_toggle.configure(state="normal")
        self.schedule.set(self.current_schedule_mode is not None)
        if self.current_schedule_mode:
            self.schedule_mode.set(self.current_schedule_mode)
        for control in self.mode_controls:
            control.configure(state="disabled" if self.current_schedule_mode else "normal")

    def append(self, message: str) -> None:
        self.output.configure(state="normal")
        self.output.insert("end", message + "\n")
        self.output.see("end")
        self.output.configure(state="disabled")

    def _credentials(self) -> tuple[str, str] | None:
        username, password = self.username.get().strip(), self.password.get()
        if not username or not password:
            self.dialogs.showwarning("请填写账号", "请输入账号和密码。", parent=self.root)
            return None
        return username, password

    def run(self, label: str, operation: Callable[[], Any], finish: Callable[[bool, Any], None] | None = None) -> None:
        def completed(success: bool, value: Any) -> None:
            for control in self.controls:
                control.configure(state="normal")
            self.progress.set("操作完成" if success else "操作失败")
            self.append(describe_result(value))
            if finish:
                finish(success, value)
            self._sync_schedule()

        if self.controller.start(operation, completed):
            for control in self.controls:
                control.configure(state="disabled")
            self.progress.set(label + "，请稍候…")
            self.append(label + "…")

    def _poll(self) -> None:
        self.controller.poll()
        self.root.after(100, self._poll)

    def save_credentials(self) -> None:
        if self.controller.busy or not (credentials := self._credentials()):
            return

        def save() -> str:
            self.backend.save_credentials(*credentials)
            return "账号已由 Windows 当前用户加密保存；尚未验证登录。"

        self.run("保存账号", save)

    def diagnose(self) -> None:
        if self.controller.busy or not (credentials := self._credentials()):
            return
        self.run(
            "检测登录（只读）",
            lambda: (
                "登录检测通过（未提交签到）"
                if self.backend.diagnose(*credentials)
                else "登录检测未通过，请检查账号、密码和网络。"
            ),
        )

    def probe(self) -> None:
        if self.controller.busy or not (credentials := self._credentials()):
            return
        self.run("检测签到状态（只读）", lambda: self.backend.probe(*credentials))

    def check_in(self) -> None:
        if self.controller.busy or not (credentials := self._credentials()):
            return
        if not self.dialogs.askyesno(
            "确认手动签到",
            LOCATION_WARNING + "\n\n" + MANUAL_CONFIRMATION + "\n\n是否确认并提交签到？",
            parent=self.root,
            default="no",
        ):
            return

        def finished(success: bool, _value: Any) -> None:
            if success and isinstance(self.backend.last_warning, str) and self.backend.last_warning:
                self.append(self.backend.last_warning)

        self.run("提交签到，请勿关闭窗口", lambda: self.backend.check_in(*credentials), finished)

    def local_status(self) -> None:
        self.run("读取本地状态", self.backend.status_text)

    def change_schedule(self) -> None:
        if self.controller.busy or not self.schedule_state_known:
            self._sync_schedule()
            return
        enabled, mode = self.schedule.get(), self.schedule_mode.get()
        if (
            enabled
            and mode == "checkin"
            and not self.dialogs.askyesno("确认自动签到授权", SCHEDULE_CONFIRMATION, parent=self.root, default="no")
        ):
            self._sync_schedule()
            return

        previous_known = self.schedule_state_known
        previous_mode = self.current_schedule_mode

        def change() -> str:
            self.backend.set_schedule(enabled, mode=mode)
            try:
                confirmed_mode = self.backend.schedule_mode()
            except DesktopError as error:
                if error.code is DesktopErrorCode.TASK_QUERY_FAILED:
                    raise
                raise DesktopError(DesktopErrorCode.TASK_STATE_UNCERTAIN) from None
            except Exception:
                raise DesktopError(DesktopErrorCode.TASK_STATE_UNCERTAIN) from None
            if (enabled and confirmed_mode != mode) or (not enabled and confirmed_mode is not None):
                raise DesktopError(DesktopErrorCode.TASK_STATE_UNCERTAIN)
            self.current_schedule_mode = confirmed_mode
            return (
                "每日计划任务已启用：" + ("只读检测" if mode == "probe" else "自动签到（会提交）")
                if enabled
                else "每日计划任务已关闭。"
            )

        def changed(success: bool, value: Any) -> None:
            if success:
                self.schedule_state_known = True
            else:
                self.current_schedule_mode = previous_mode
                self.schedule_state_known = (
                    False
                    if value in (DesktopErrorCode.TASK_QUERY_FAILED, DesktopErrorCode.TASK_STATE_UNCERTAIN)
                    else previous_known
                )
            self._sync_schedule()

        self.run("更新计划任务", change, changed)

    def close(self) -> None:
        if self.controller.busy:
            self.dialogs.showwarning(
                "操作进行中", "请等待当前操作结束后再关闭，以免无法确认操作结果。", parent=self.root
            )
            return
        self.root.destroy()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="西南大学寝室签到助手：默认打开桌面窗口")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--scheduled", action="store_true", help="运行已明确启用的计划任务")
    modes.add_argument("--self-test", action="store_true", help="仅验证离线依赖，不读取账号或连接学校")
    args = parser.parse_args(argv)
    from .desktop_backend import DesktopBackend

    try:
        backend = DesktopBackend()
        if args.self_test:
            return backend.self_test()
        if args.scheduled:
            return backend.run_scheduled()
        import tkinter as tk

        root = tk.Tk()
        DesktopApp(root, backend)
        root.mainloop()
        return 0
    except Exception as error:
        # No traceback: even authentication exceptions can contain secrets.
        if not args.self_test and not args.scheduled:
            try:
                from tkinter import messagebox

                messagebox.showerror(
                    "无法启动签到助手",
                    ERROR_MESSAGES.get(error.code, SAFE_ERROR) if isinstance(error, DesktopError) else SAFE_ERROR,
                )
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
