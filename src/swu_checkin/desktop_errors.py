"""Closed desktop error vocabulary; never accept unreviewed error text."""

from enum import Enum
from types import MappingProxyType


class DesktopErrorCode(Enum):
    WINDOWS_REQUIRED = "windows_required"
    TASK_IDENTITY_MISSING = "task_identity_missing"
    CREDENTIALS_EMPTY = "credentials_empty"
    SCHEDULE_ACTIVE = "schedule_active"
    CREDENTIAL_SAVE_FAILED = "credential_save_failed"
    CREDENTIAL_LOAD_FAILED = "credential_load_failed"
    READONLY_ENABLED = "readonly_enabled"
    TASK_WINDOWS_REQUIRED = "task_windows_required"
    CONFIG_DAMAGED = "config_damaged"
    CONFIG_INVALID = "config_invalid"
    SCHEDULE_MODE_INVALID = "schedule_mode_invalid"
    TASK_DISABLE_FAILED = "task_disable_failed"
    MODE_REQUIRED = "mode_required"
    FROZEN_REQUIRED = "frozen_required"
    SAVED_CREDENTIALS_REQUIRED = "saved_credentials_required"
    DIAGNOSIS_FAILED = "diagnosis_failed"
    LEGACY_TASK_EXISTS = "legacy_task_exists"
    USER_IDENTITY_FAILED = "user_identity_failed"
    TASK_STATE_UNCERTAIN = "task_state_uncertain"
    TASK_QUERY_FAILED = "task_query_failed"
    TASK_CREATE_FAILED = "task_create_failed"


ERROR_MESSAGES = MappingProxyType(
    {
        DesktopErrorCode.WINDOWS_REQUIRED: "桌面版需要 Windows 10/11 和有效的本地用户目录。",
        DesktopErrorCode.TASK_IDENTITY_MISSING: "计划任务缺少程序路径或用户身份。",
        DesktopErrorCode.CREDENTIALS_EMPTY: "账号和密码不能为空。",
        DesktopErrorCode.SCHEDULE_ACTIVE: "请先关闭定时任务，再修改已保存账号，修改后重新检测并启用。",
        DesktopErrorCode.CREDENTIAL_SAVE_FAILED: "无法安全保存凭据；请检查本地用户目录与 Windows DPAPI。",
        DesktopErrorCode.CREDENTIAL_LOAD_FAILED: "保存的凭据无法解密或已损坏，请在此 Windows 用户下重新保存。",
        DesktopErrorCode.READONLY_ENABLED: "只读安全开关已启用，不能正式签到。",
        DesktopErrorCode.TASK_WINDOWS_REQUIRED: "计划任务仅支持 Windows。",
        DesktopErrorCode.CONFIG_DAMAGED: "定时配置已损坏，请重新设置。",
        DesktopErrorCode.CONFIG_INVALID: "定时配置格式无效，请重新设置。",
        DesktopErrorCode.SCHEDULE_MODE_INVALID: "定时模式无效，请关闭后重新设置。",
        DesktopErrorCode.TASK_DISABLE_FAILED: "无法停用计划任务，请在 Windows 任务计划程序检查。",
        DesktopErrorCode.MODE_REQUIRED: "请选择有效的定时模式。",
        DesktopErrorCode.FROZEN_REQUIRED: "请使用安装版启用定时任务，开发目录可能移动。",
        DesktopErrorCode.SAVED_CREDENTIALS_REQUIRED: "启用定时前请先保存并检测账号。",
        DesktopErrorCode.DIAGNOSIS_FAILED: "保存账号的只读检测未通过，未启用计划任务。",
        DesktopErrorCode.LEGACY_TASK_EXISTS: "发现旧版 SWUCheckin-Daily 任务，请先在任务计划程序删除旧任务登记（保留账号配置），避免两套定时同时运行。",
        DesktopErrorCode.USER_IDENTITY_FAILED: "无法确认 Windows 用户身份。",
        DesktopErrorCode.TASK_STATE_UNCERTAIN: "计划任务最终状态无法确认，请检查任务计划程序后重新打开应用。",
        DesktopErrorCode.TASK_QUERY_FAILED: "无法确认计划任务状态",
        DesktopErrorCode.TASK_CREATE_FAILED: "计划任务创建失败，请检查当前用户的任务计划权限。",
    }
)


class DesktopError(RuntimeError):
    def __init__(self, code: DesktopErrorCode) -> None:
        if not isinstance(code, DesktopErrorCode):
            raise TypeError("DesktopError requires a DesktopErrorCode")
        self.code = code
        super().__init__(ERROR_MESSAGES[code])
