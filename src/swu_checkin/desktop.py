"""Chinese desktop entry point; launching never submits a check-in."""

from __future__ import annotations

import argparse
import queue
import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from . import __version__
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
SAFE_ERROR = "操作未完成。请检查网络、账号、系统权限或本地配置后重试；未显示敏感诊断信息。"


@dataclass(frozen=True)
class DesktopPresentation:
    native_quit_command: str | None = None
    scheduling: bool = True
    explicit_credentials: bool = False
    font_family: str = "Microsoft YaHei UI"
    credential_notice: str = "只有点击“保存账号”才会保存；使用 Windows 当前用户加密保护。"
    saved_notice: str = "账号已由 Windows 当前用户加密保存；尚未验证登录。"


MACOS_PRESENTATION = DesktopPresentation(
    native_quit_command="::tk::mac::Quit",
    scheduling=False,
    explicit_credentials=True,
    font_family="PingFang SC",
    credential_notice="账号默认仅在内存中；只有点击“保存账号”才存入 macOS 钥匙串。令牌仅保存在本次窗口内存。",
    saved_notice="账号已保存到 macOS 钥匙串；尚未验证登录。",
)


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


# Shared with the Android client's light theme so both front ends read as one product.
_PALETTE = {
    "brand": "#1F4A3A",
    "brand_text": "#FFFFFF",
    "brand_muted": "#CFE3D6",
    "background": "#F3F6F2",
    "card": "#FFFEFB",
    "border": "#DDE5DC",
    "text": "#1D3028",
    "muted": "#5F6E64",
    "primary": "#245C47",
    "primary_active": "#1B4A39",
    "primary_disabled": "#A8C2B4",
    "secondary": "#E6EEE7",
    "secondary_active": "#D5E3D8",
    "caution": "#8A5A12",
    "caution_bg": "#FFF1D6",
    "caution_active": "#FFE3B0",
    "caution_text": "#5E4313",
    "error": "#AD3E38",
    "error_bg": "#FFE9E5",
    "done_bg": "#DDEEE3",
    "busy_bg": "#FFEDCE",
    "log_bg": "#F6F8F5",
    "disabled_text": "#9AA69E",
}


def _apply_styles(style: Any, family: str) -> None:
    """Cross-platform ttk styling; ``clam`` honours colours on Windows and macOS alike."""

    palette = _PALETTE
    style.theme_use("clam")
    base = (family, 10)
    style.configure(".", font=base, background=palette["background"], foreground=palette["text"])
    style.configure("Page.TFrame", background=palette["background"])
    style.configure("Card.TFrame", background=palette["card"])
    for name, background, foreground, font in (
        ("HeaderCaption.TLabel", palette["brand"], palette["brand_muted"], (family, 9)),
        ("HeaderTitle.TLabel", palette["brand"], palette["brand_text"], (family, 18, "bold")),
        ("HeaderBody.TLabel", palette["brand"], palette["brand_muted"], (family, 10)),
        ("CardTitle.TLabel", palette["card"], palette["text"], (family, 12, "bold")),
        ("CardStrong.TLabel", palette["card"], palette["text"], (family, 10, "bold")),
        ("CardMuted.TLabel", palette["card"], palette["muted"], (family, 9)),
        ("Caution.TLabel", palette["caution_bg"], palette["caution_text"], (family, 10)),
        ("CautionIcon.TLabel", palette["caution_bg"], palette["caution"], (family, 10, "bold")),
    ):
        style.configure(name, background=background, foreground=foreground, font=font)
    for name, background, foreground in (
        ("PillIdle.TLabel", "#2E5E4B", palette["brand_text"]),
        ("PillBusy.TLabel", palette["busy_bg"], palette["caution_text"]),
        ("PillDone.TLabel", palette["done_bg"], palette["primary"]),
        ("PillError.TLabel", palette["error_bg"], palette["error"]),
    ):
        style.configure(name, background=background, foreground=foreground, font=(family, 10, "bold"), padding=(14, 6))

    def button(name: str, background: str, foreground: str, active: str) -> None:
        style.configure(
            name,
            background=background,
            foreground=foreground,
            bordercolor=background,
            lightcolor=background,
            darkcolor=background,
            focuscolor=foreground,
            relief="flat",
            padding=(12, 6),
            font=(family, 10, "bold"),
        )
        style.map(
            name,
            background=[("disabled", palette["secondary"]), ("pressed", active), ("active", active)],
            bordercolor=[("disabled", palette["secondary"]), ("active", active)],
            lightcolor=[("disabled", palette["secondary"]), ("active", active)],
            darkcolor=[("disabled", palette["secondary"]), ("active", active)],
            foreground=[("disabled", palette["disabled_text"])],
        )

    button("Primary.TButton", palette["primary"], palette["brand_text"], palette["primary_active"])
    button("Secondary.TButton", palette["secondary"], palette["text"], palette["secondary_active"])
    button("Caution.TButton", palette["caution_bg"], palette["caution_text"], palette["caution_active"])
    style.configure(
        "Field.TEntry",
        fieldbackground=palette["card"],
        foreground=palette["text"],
        bordercolor=palette["border"],
        lightcolor=palette["border"],
        darkcolor=palette["border"],
        insertcolor=palette["text"],
        padding=(8, 4),
    )
    style.map(
        "Field.TEntry",
        bordercolor=[("focus", palette["primary"])],
        lightcolor=[("focus", palette["primary"])],
        fieldbackground=[("disabled", palette["log_bg"])],
    )
    for name in ("Card.TRadiobutton", "Card.TCheckbutton"):
        style.configure(name, background=palette["card"], foreground=palette["text"], font=base)
        style.map(
            name,
            background=[("active", palette["card"])],
            foreground=[("disabled", palette["disabled_text"])],
            indicatorcolor=[("selected", palette["primary"]), ("disabled", palette["secondary"])],
        )
    style.configure(
        "Vertical.TScrollbar",
        background=palette["secondary"],
        troughcolor=palette["log_bg"],
        bordercolor=palette["log_bg"],
        arrowcolor=palette["muted"],
        lightcolor=palette["secondary"],
        darkcolor=palette["secondary"],
    )


def _card(parent: Any, title: str, *, pady: tuple[int, int] = (0, 0), expand: bool = False) -> Any:
    """A bordered white card; returns the inner grid frame whose row 0 holds the title."""

    import tkinter as tk
    from tkinter import ttk

    outer = tk.Frame(
        parent,
        background=_PALETTE["card"],
        highlightthickness=1,
        highlightbackground=_PALETTE["border"],
        highlightcolor=_PALETTE["border"],
    )
    outer.pack(fill="both" if expand else "x", expand=expand, pady=pady)
    inner = ttk.Frame(outer, style="Card.TFrame", padding=(18, 12, 18, 14))
    inner.pack(fill="both", expand=True)
    ttk.Label(inner, text=title, style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
    return inner


class DesktopApp:
    presentation = DesktopPresentation()

    def __init__(self, root: Any, backend: Any, presentation: DesktopPresentation | None = None) -> None:
        # The normal GUI and macOS offline self-test use this same window.
        import tkinter as tk
        from tkinter import messagebox, ttk

        self.presentation = presentation or self.presentation
        self.root = root
        self.backend = backend
        self.dialogs = messagebox
        self.controller = DesktopController()
        self.controls: list[Any] = []
        family = self.presentation.font_family
        root.title(f"SWU 查寝 {__version__} · MatchAll")
        # macOS adds a keychain button row to the account card.
        height = 740 if self.presentation.explicit_credentials else 700
        root.geometry(f"960x{height}")
        root.minsize(900, height - 40)
        root.configure(background=_PALETTE["background"])
        self._register_close_handlers()
        _apply_styles(ttk.Style(root), family)

        # Header band: brand, version and a live status pill.
        header = tk.Frame(root, background=_PALETTE["brand"], padx=24, pady=14)
        header.pack(fill="x")
        heading = tk.Frame(header, background=_PALETTE["brand"])
        heading.pack(side="left", fill="x", expand=True)
        ttk.Label(heading, text="SWU 查寝 · MatchAll", style="HeaderCaption.TLabel").pack(anchor="w")
        ttk.Label(heading, text="西南大学寝室签到助手", style="HeaderTitle.TLabel").pack(anchor="w", pady=(2, 2))
        ttk.Label(
            heading,
            text=f"版本 {__version__}  ·  打开软件不会联网或提交签到。请先检测，再按需手动执行。",
            style="HeaderBody.TLabel",
        ).pack(anchor="w")
        self.progress = tk.StringVar(value="就绪（未联网）")
        self.status_pill = ttk.Label(header, textvariable=self.progress, style="PillIdle.TLabel")
        self.status_pill.pack(side="right", anchor="center")
        self.progress.trace_add("write", lambda *_args: self._refresh_status_pill())

        body = ttk.Frame(root, style="Page.TFrame", padding=(20, 12, 20, 16))
        body.pack(fill="both", expand=True)
        warning = tk.Frame(body, background=_PALETTE["caution_bg"], padx=14, pady=7)
        warning.pack(fill="x", pady=(0, 12))
        ttk.Label(warning, text="注意", style="CautionIcon.TLabel").pack(side="left", anchor="n", padx=(0, 10))
        ttk.Label(warning, text=LOCATION_WARNING, style="Caution.TLabel", wraplength=820).pack(
            side="left", fill="x", expand=True
        )

        columns = ttk.Frame(body, style="Page.TFrame")
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=5, uniform="column")
        columns.columnconfigure(1, weight=6, uniform="column")
        columns.rowconfigure(0, weight=1)
        left = ttk.Frame(columns, style="Page.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right = ttk.Frame(columns, style="Page.TFrame")
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        # Account card.
        account = _card(left, "校园账号")
        account.columnconfigure(0, weight=1)
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        row = 1
        for label, variable, hidden in (("学号 / 账号", self.username, False), ("密码", self.password, True)):
            ttk.Label(account, text=label, style="CardMuted.TLabel").grid(row=row, column=0, sticky="w")
            entry = ttk.Entry(account, textvariable=variable, show="•" if hidden else "", style="Field.TEntry")
            entry.grid(row=row + 1, column=0, sticky="ew", pady=(2, 8), ipady=1)
            self.controls.append(entry)
            row += 2
        account_buttons = ttk.Frame(account, style="Card.TFrame")
        account_buttons.grid(row=row, column=0, sticky="ew")
        account_actions = [("保存账号", self.save_credentials)]
        if self.presentation.explicit_credentials:
            account_actions += [("读取已存账号", self.load_credentials), ("清除已存账号…", self.delete_credentials)]
        account_buttons.columnconfigure((0, 1), weight=1, uniform="account")
        for index, (text, command) in enumerate(account_actions):
            # Save spans the first row; macOS keychain actions share the second.
            button = ttk.Button(account_buttons, text=text, command=command, style="Secondary.TButton")
            if index == 0:
                button.grid(row=0, column=0, columnspan=2, sticky="ew")
            else:
                button.grid(row=1, column=index - 1, sticky="ew", pady=(6, 0), padx=(0, 3) if index == 1 else (3, 0))
            self.controls.append(button)
        ttk.Label(account, text=self.presentation.credential_notice, style="CardMuted.TLabel", wraplength=360).grid(
            row=row + 1, column=0, sticky="w", pady=(8, 0)
        )

        # Primary actions card: read-only first, submission clearly separated.
        actions = _card(left, "签到操作", pady=(12, 0))
        actions.columnconfigure((0, 1), weight=1, uniform="action")
        for index, (text, command, style) in enumerate(
            (
                ("只读检测", self.probe, "Primary.TButton"),
                ("检测登录", self.diagnose, "Secondary.TButton"),
                ("本地状态", self.local_status, "Secondary.TButton"),
                ("手动签到…", self.check_in, "Caution.TButton"),
            )
        ):
            button = ttk.Button(actions, text=text, command=command, style=style)
            button.grid(
                row=1 + index // 2,
                column=index % 2,
                sticky="ew",
                padx=(0 if index % 2 == 0 else 4, 0 if index % 2 else 4),
                pady=4,
            )
            self.controls.append(button)
        ttk.Label(
            actions,
            text="检测不会提交签到；手动签到前会再次请你确认本人在寝。",
            style="CardMuted.TLabel",
            wraplength=340,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

        if self.presentation.scheduling:
            schedule = _card(right, "Windows 每日计划任务（默认关闭）")
            self.schedule = tk.BooleanVar(value=False)
            self.schedule_mode = tk.StringVar(value="probe")
            self.mode_controls: list[Any] = []
            modes = ttk.Frame(schedule, style="Card.TFrame")
            modes.grid(row=1, column=0, sticky="w")
            for text, mode in (("只读检测（不提交）", "probe"), ("自动签到（会提交）", "checkin")):
                control = ttk.Radiobutton(
                    modes, text=text, variable=self.schedule_mode, value=mode, style="Card.TRadiobutton"
                )
                control.pack(side="left", padx=(0, 18))
                self.controls.append(control)
                self.mode_controls.append(control)
            self.schedule_toggle = ttk.Checkbutton(
                schedule,
                text="启用每日计划任务",
                variable=self.schedule,
                command=self.change_schedule,
                style="Card.TCheckbutton",
            )
            self.schedule_toggle.grid(row=2, column=0, sticky="w", pady=(8, 0))
            self.controls.append(self.schedule_toggle)
            self.schedule_status = tk.StringVar(value="计划任务状态未知（正在读取本地状态）")
            ttk.Label(schedule, textvariable=self.schedule_status, style="CardStrong.TLabel").grid(
                row=3, column=0, sticky="w", pady=(6, 0)
            )
            ttk.Label(
                schedule,
                text="北京时间每日 21:15、21:45 运行；电脑须开机联网且用户已登录，睡眠或关机时不保证运行。"
                "切换模式前请先关闭任务，再选择模式并重新启用。计划任务需要先保存账号。",
                style="CardMuted.TLabel",
                wraplength=430,
            ).grid(row=4, column=0, sticky="w", pady=(6, 0))
        else:
            notice = _card(right, "macOS 预览版")
            ttk.Label(
                notice,
                text="仅支持手动操作；不创建后台任务或登录启动项。"
                "未提供 Developer ID 签名和 Apple 公证；仍需真实 Mac 干净用户验收。",
                style="CardMuted.TLabel",
                wraplength=430,
            ).grid(row=1, column=0, sticky="w")

        log = _card(right, "运行记录", pady=(12, 0), expand=True)
        log.columnconfigure(0, weight=1)
        log.rowconfigure(1, weight=1)
        self.output = tk.Text(
            log,
            height=9,
            wrap="word",
            state="disabled",
            font=(family, 10),
            background=_PALETTE["log_bg"],
            foreground=_PALETTE["text"],
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=10,
            pady=8,
            spacing1=2,
            spacing3=2,
        )
        self.output.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log, orient="vertical", command=self.output.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.output.configure(yscrollcommand=scrollbar.set)
        self.schedule_state_known = False
        self.current_schedule_mode: str | None = None
        self._restore_local_state()
        root.after(100, self._poll)

    def _refresh_status_pill(self) -> None:
        text = self.progress.get()
        if text.endswith("请稍候…"):
            style = "PillBusy.TLabel"
        elif text == "操作失败":
            style = "PillError.TLabel"
        elif text == "操作完成":
            style = "PillDone.TLabel"
        else:
            style = "PillIdle.TLabel"
        self.status_pill.configure(style=style)

    def _register_close_handlers(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if self.presentation.native_quit_command:
            # macOS menu/Dock Quit otherwise exits without WM_DELETE_WINDOW.
            self.root.createcommand(self.presentation.native_quit_command, self.close)

    def _restore_local_state(self) -> None:
        if self.presentation.explicit_credentials:
            self.append("未读取钥匙串；如需使用已存账号，请点击“读取已存账号”。")
            return

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
        if not self.presentation.scheduling:
            return
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
            return self.presentation.saved_notice

        self.run("保存账号", save)

    def load_credentials(self) -> None:
        if self.controller.busy or not self.presentation.explicit_credentials:
            return

        def loaded(success: bool, value: Any) -> None:
            if success:
                if value is not None:
                    self.username.set(value[0])
                    self.password.set(value[1])
                self.append("已读取钥匙串账号（未联网）。" if value is not None else "钥匙串中尚无已存账号。")

        self.run("读取钥匙串账号（不联网）", self.backend.load_credentials, loaded)

    def delete_credentials(self) -> None:
        if self.controller.busy or not self.presentation.explicit_credentials:
            return
        if not self.dialogs.askyesno(
            "清除已存账号",
            "从 macOS 钥匙串清除此应用保存的账号，并清空当前窗口账号与内存令牌？",
            parent=self.root,
            default="no",
        ):
            return

        def removed(success: bool, _value: Any) -> None:
            if success:
                self.username.set("")
                self.password.set("")
                self.append("已清除本应用的已存账号、当前输入与内存令牌。")

        self.run("清除已存账号", self.backend.delete_credentials, removed)

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
        if not self.presentation.scheduling:
            return
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
    presentation = DesktopPresentation()
    if sys.platform == "darwin":
        from .macos_backend import MacOSBackend

        if args.scheduled:
            return 1
        backend_factory = MacOSBackend
        presentation = MACOS_PRESENTATION
    else:
        from .desktop_backend import DesktopBackend

        backend_factory = DesktopBackend

    try:
        backend = backend_factory()
        if args.self_test:
            return backend.self_test()
        if args.scheduled:
            return backend.run_scheduled()
        import tkinter as tk

        root = tk.Tk()
        if sys.platform == "darwin":
            DesktopApp(root, backend, presentation)
        else:
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
