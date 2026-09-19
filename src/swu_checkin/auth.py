"""Internal authentication failures and legacy status mapping."""

from __future__ import annotations

from enum import Enum

from .status import CheckinStatus


class AuthFailureReason(Enum):
    """Stable internal reasons for authentication failures."""

    CREDENTIAL_REJECTED = "credential_rejected"
    CAPTCHA_FAILED = "captcha_failed"
    NETWORK_ERROR = "network_error"
    LOGIN_PAGE_CHANGED = "login_page_changed"
    OAUTH_FLOW_CHANGED = "oauth_flow_changed"
    TICKET_FAILED = "ticket_failed"
    TOKEN_EXCHANGE_FAILED = "token_exchange_failed"
    UNKNOWN = "unknown"


_SAFE_MESSAGES = {
    AuthFailureReason.CREDENTIAL_REJECTED: "校园网账号或密码未通过认证",
    AuthFailureReason.CAPTCHA_FAILED: "验证码识别或校验失败",
    AuthFailureReason.NETWORK_ERROR: "认证服务网络请求失败",
    AuthFailureReason.LOGIN_PAGE_CHANGED: "登录页面结构与预期不一致",
    AuthFailureReason.OAUTH_FLOW_CHANGED: "OAuth/CAS 认证流程与预期不一致",
    AuthFailureReason.TICKET_FAILED: "认证 ticket 获取或校验失败",
    AuthFailureReason.TOKEN_EXCHANGE_FAILED: "认证 token 交换或校验失败",
    AuthFailureReason.UNKNOWN: "认证过程发生未知错误",
}


class AuthError(RuntimeError):
    """A classified authentication error that never exposes raw server data."""

    def __init__(self, reason: AuthFailureReason, message: str | None = None) -> None:
        self.reason = reason
        # Authentication exceptions deliberately expose only reviewed constants.
        # A caller-provided value is accepted only when it is one of those constants.
        safe_message = message if message in _SAFE_MESSAGES.values() else _SAFE_MESSAGES[reason]
        self.message = safe_message
        super().__init__(safe_message)


def auth_failure_status(reason: AuthFailureReason) -> CheckinStatus:
    """Map internal auth detail onto the unchanged public status enum."""

    if reason in {AuthFailureReason.CREDENTIAL_REJECTED, AuthFailureReason.CAPTCHA_FAILED}:
        return CheckinStatus.LOGIN_FAILED
    return CheckinStatus.DATA_ERROR
