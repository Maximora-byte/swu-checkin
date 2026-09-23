import os
import re
import time
from io import BytesIO

# The check-in client does not use ONNX Runtime telemetry. Disable it before
# importing ddddocr so restricted service users do not trigger device-ID
# persistence warnings during OCR initialization.
os.environ["ORT_DISABLE_TELEMETRY"] = "1"

import ddddocr
import requests
from PIL import Image

from .auth import AuthError, AuthFailureReason
from .client import SwuClient
from .des import des
from .identity import submit_identity_selection_if_needed
from .oauth_flow import (
    OAuthDiscoveryError,
    build_cas_callback_url,
    build_login_form_data,
    describe_auth_response,
    discover_login_flow,
    extract_ticket_from_url,
    follow_trusted_auth_redirects,
    validate_cas_callback_response,
    validate_idm_login_response,
)

# ===== 常量定义 =====
TOKEN_EXCHANGE_URL = "https://of.swu.edu.cn/gateway/fighter-middle/api/integrate/uaap/cas/exchange-token"

_CREDENTIAL_REJECTION_MARKERS = (
    "用户名或密码",
    "账号或密码",
    "用户名密码错误",
    "密码错误",
)
_CAPTCHA_REJECTION_MARKERS = ("验证码错误", "验证码不正确", "validateCode")


# ===== 辅助函数 =====
def mask_sensitive_data(data: str, show_chars: int = 4) -> str:
    """
    脱敏处理敏感数据

    Args:
        data: 敏感字符串
        show_chars: 显示的字符数（前后各显示一半）

    Returns:
        脱敏后的字符串，例如：abc***xyz
    """
    if not data or len(data) <= show_chars:
        return "****"

    half = show_chars // 2
    return f"{data[:half]}{'*' * (len(data) - show_chars)}{data[-half:]}"


SENSITIVE_LOG_PATTERNS = (
    re.compile(r"(?i)\b(?:password|token|ticket|captcha|state|random)\s*[:=]\s*\S+"),
    re.compile(r"验证码\s*[:=]\s*\S+"),
    re.compile(r"(?i)https?://\S*(?:token|ticket|code|state)=\S+"),
)


def safe_print(message: str) -> None:
    """输出不包含凭据值的消息。"""
    if any(pattern.search(message) for pattern in SENSITIVE_LOG_PATTERNS):
        return
    print(message)


def debug_print(message: object) -> None:
    """在显式启用时输出不含凭据的诊断信息。"""
    if os.getenv("SWUDK_DEBUG_CREDENTIALS") == "1":
        safe_print(f"[DEBUG] {message}")


def transform_ticket(ticket: str) -> str:
    """
    转换 ticket 编码
    数字: +5 模 10
    大写字母: +10 (超Z循环)
    小写字母: +15 (超z循环)
    """
    result = ""
    for char in ticket:
        if char in "-:/":
            result += char
        elif "0" <= char <= "9":
            result += str((int(char) + 5) % 10)
        elif "A" <= char <= "Z":
            new_ord = ord(char) + 10
            if new_ord > ord("Z"):
                new_ord -= 26
            result += chr(new_ord)
        elif "a" <= char <= "z":
            new_ord = ord(char) + 15
            if new_ord > ord("z"):
                new_ord -= 26
            result += chr(new_ord)
        else:
            result += char
    return result


def validate_login_result_text(html: str) -> None:
    """Classify explicit server-side login rejection without exposing its body."""

    if any(marker in html for marker in _CREDENTIAL_REJECTION_MARKERS):
        raise AuthError(AuthFailureReason.CREDENTIAL_REJECTED)
    if any(marker in html for marker in _CAPTCHA_REJECTION_MARKERS):
        raise AuthError(AuthFailureReason.CAPTCHA_FAILED)


def recognize_captcha(
    session: requests.Session,
    captcha_url: str,
    timeout: int = 10,
    max_attempts: int = 3,
) -> str:
    """
    OCR 识别验证码，支持重试机制

    Args:
        session: requests 会话
        timeout: 超时时间
        max_attempts: 最大尝试次数

    Returns:
        识别出的验证码字符串

    Raises:
        AuthError: 网络失败或多次尝试后仍无法识别
    """
    ocr = ddddocr.DdddOcr(show_ad=False, use_gpu=False)

    for attempt in range(1, max_attempts + 1):
        try:
            response = session.get(captcha_url, timeout=timeout, allow_redirects=False)
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError:
                if response.status_code in {408, 425, 429} or 500 <= response.status_code <= 599:
                    raise
                raise OAuthDiscoveryError("验证码端点未返回成功响应") from None
            if response.status_code != 200:
                raise OAuthDiscoveryError("验证码端点未返回成功响应")
            img = Image.open(BytesIO(response.content))
            result = ocr.classification(img)

            # 验证码基本验证：应该是4位数字或字母
            if result and len(result) >= 3:
                debug_print(f"验证码识别成功 (尝试 {attempt}/{max_attempts})")
                return result
            else:
                safe_print(f"验证码识别结果异常 (尝试 {attempt}/{max_attempts})，重新获取")
        except requests.exceptions.RequestException as error:
            safe_print(f"验证码识别失败 (尝试 {attempt}/{max_attempts}): {type(error).__name__}")
            if attempt >= max_attempts:
                raise AuthError(AuthFailureReason.NETWORK_ERROR) from None
        except OAuthDiscoveryError:
            raise
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            safe_print(f"验证码识别失败 (尝试 {attempt}/{max_attempts}): {type(error).__name__}")

        if attempt < max_attempts:
            time.sleep(0.5)  # 短暂延迟后重试

    raise AuthError(AuthFailureReason.CAPTCHA_FAILED)


# ===== 主要登录流程 =====
def get_token(username: str, password: str, timeout: int = 10) -> str:
    """
    执行完整登录流程，获取 fighter-auth-token

    流程:
        1. 访问 CAS 登录页，获取 OAuth state
        2. 跳转 IDM 登录页，解析 codeRandom
        3. DES 加密用户名和密码
        4. OCR 识别验证码
        5. 提交登录表单
        6. 处理身份选择（研究生/本科生）
        7. 从回调 URL 提取 ticket，转换编码
        8. 用 ticket 换取 token

    返回:
        成功返回 token；失败保持历史兼容并返回空字符串
    """
    try:
        return authenticate_token(username, password, timeout)
    except AuthError:
        return ""


def authenticate_token(username: str, password: str, timeout: int = 10) -> str:
    """Authenticate with classified failures for internal service orchestration."""

    return _get_token(username, password, timeout)


def _get_token(username: str, password: str, timeout: int, max_login_attempts: int = 3) -> str:
    """
    内部登录实现；完整认证重试由 CheckinService 负责。

    Args:
        username: 用户名
        password: 密码
        timeout: 超时时间
        max_login_attempts: 服务端明确拒绝验证码后的最大提交次数

    Returns:
        成功返回 token

    Raises:
        AuthError: 当前完整认证失败后的分类结果
    """
    try:
        session = requests.Session()

        # 步骤 1: 从可信 SWU HTTPS 响应发现 OAuth state、回调与登录 form
        flow = discover_login_flow(session, timeout)
        debug_print("已从可信响应发现登录流程")

        # 步骤 2: DES 加密凭证
        encrypted_username, encrypted_password = des(username, password, flow.code_random)

        if max_login_attempts < 1:
            raise AuthError(AuthFailureReason.CAPTCHA_FAILED)
        for captcha_submit_attempt in range(1, max_login_attempts + 1):
            # 步骤 3: OCR 识别验证码（图片获取与 OCR 自身带有限重试）
            captcha = recognize_captcha(session, flow.captcha_url, timeout, max_attempts=3)
            debug_print("验证码已识别")

            # 步骤 4: 提交服务端提供的登录表单，并逐跳验证 Redirect
            form_data = build_login_form_data(flow, encrypted_username, encrypted_password, captcha)
            response = session.post(
                flow.form_action,
                data=form_data,
                timeout=timeout,
                allow_redirects=False,
            )
            response = follow_trusted_auth_redirects(session, response, timeout=timeout)
            debug_print(f"登录提交响应: {describe_auth_response(response)}")
            validate_idm_login_response(response)

            try:
                validate_login_result_text(response.text)
            except AuthError as error:
                if error.reason is not AuthFailureReason.CAPTCHA_FAILED or captcha_submit_attempt >= max_login_attempts:
                    raise
                safe_print(f"验证码被服务器拒绝 (尝试 {captcha_submit_attempt}/{max_login_attempts})，重新获取")
                time.sleep(1)
                continue
            break

        # 步骤 5: 处理身份选择
        response = submit_identity_selection_if_needed(
            session,
            response,
            login_url=flow.form_action,
            goto_value=flow.goto_value,
            timeout=timeout,
            allow_redirects=False,
        )
        response = follow_trusted_auth_redirects(session, response, timeout=timeout)
        debug_print(f"身份选择响应: {describe_auth_response(response)}")
        validate_idm_login_response(response)

        debug_print("身份选择流程已完成")

        # 步骤 6: 提取并转换 ticket
        ticket_st = extract_ticket_from_url(response.url)
        if not ticket_st:
            raise AuthError(AuthFailureReason.TICKET_FAILED)

        ticket_cd = transform_ticket(ticket_st)

        # 步骤 7a: 使用服务端发现的 callback 与 state 访问回调
        callback_url = build_cas_callback_url(flow, ticket_cd)
        response = session.get(callback_url, timeout=timeout, allow_redirects=False)
        response = follow_trusted_auth_redirects(session, response, timeout=timeout)
        debug_print(f"CAS callback 响应: {describe_auth_response(response)}")
        validate_cas_callback_response(response)

        # 步骤 7b: 从最终回调 URL 获取 token ticket
        token_st = extract_ticket_from_url(response.url)
        if not token_st:
            raise AuthError(AuthFailureReason.TICKET_FAILED)

        # 步骤 7c: 用 token ticket 换取最终 token
        response = session.get(
            TOKEN_EXCHANGE_URL,
            params={"token": token_st, "remember": "true"},
            timeout=timeout,
        )
        response.raise_for_status()
        try:
            token_response = response.json()
        except (ValueError, TypeError):
            raise AuthError(AuthFailureReason.TOKEN_EXCHANGE_FAILED) from None

        if not isinstance(token_response, dict) or "data" not in token_response:
            raise AuthError(AuthFailureReason.TOKEN_EXCHANGE_FAILED)

        token = token_response["data"]
        if not isinstance(token, str) or not token:
            raise AuthError(AuthFailureReason.TOKEN_EXCHANGE_FAILED)
        debug_print("登录成功，认证结果已确认")
        return token
    except requests.exceptions.RequestException as error:
        safe_print(f"登录过程异常: {type(error).__name__}")
        raise AuthError(AuthFailureReason.NETWORK_ERROR) from None
    except OAuthDiscoveryError as error:
        safe_print(f"登录过程异常: {type(error).__name__}")
        raise AuthError(error.reason) from None
    except AuthError as error:
        safe_print(f"登录过程异常: {type(error).__name__}")
        raise
    except (KeyError, ValueError, TypeError) as error:
        safe_print(f"登录过程异常: {type(error).__name__}")
        raise AuthError(AuthFailureReason.UNKNOWN) from None


def get_student_id(token: str, timeout: int = 10) -> str:
    """Compatibility wrapper for obtaining the student identifier."""
    return SwuClient(token, timeout).get_student_id()


def get_dormitory(token: str, timeout: int = 10) -> dict:
    """Compatibility wrapper for obtaining dormitory data."""
    return SwuClient(token, timeout).get_dormitory()


def get_transition_today(token: str, timeout: int = 10) -> dict | None:
    """Compatibility wrapper for obtaining today's check-in task."""
    return SwuClient(token, timeout).get_transition_today()
