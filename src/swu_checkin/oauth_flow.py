"""Discover and validate SWU's CAS/OAuth login flow without guessed redirects."""

import base64
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import requests
from bs4 import BeautifulSoup

from .auth import AuthFailureReason

TRUSTED_SWU_HOSTS = frozenset({"of.swu.edu.cn", "uaaap.swu.edu.cn", "idm.swu.edu.cn"})

CAS_LOGIN_URL = "https://of.swu.edu.cn/cas/oauth/login/SWU_CAS2_FEDERAL"
CAS_SERVICE_URL = (
    "https://of.swu.edu.cn/gateway/fighter-middle/api/integrate/uaap/cas/resolve-cas-return?next=https://of.swu.edu.cn/"
)
CAS_LOGIN_ENTRY_URL = f"{CAS_LOGIN_URL}?{urllib.parse.urlencode({'service': CAS_SERVICE_URL})}"

# IDM does not publish these application-registration values in the upstream CAS
# redirects. They remain the minimum fixed bootstrap contract; every redirect,
# callback and form value around them is discovered from trusted HTTPS responses.
IDM_AUTHORIZE_URL = "https://idm.swu.edu.cn/am/oauth2/authorize"
IDM_OAUTH_CLIENT_ID = "7c1zokoljl9bbiho6yuo"
IDM_OAUTH_SCOPE = "uid cn userIdCode"

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_STATE_RE = re.compile(r"[A-Za-z0-9._~-]{16,512}")
_TICKET_LANDING_RE = re.compile(r"/&ticket=([^/?#]+)")
_INPUT_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")
_FEDERAL_ENABLE_RE = re.compile(r"window\.location\.href\s*=\s*url\s*\+\s*['\"]federalEnable=true['\"]\s*;")
_REQUIRED_LOGIN_FIELDS = frozenset(
    {
        "IDToken1",
        "IDToken2",
        "IDToken3",
        "goto",
        "gotoOnFail",
        "SunQueryParamsString",
        "encoded",
        "validateCode",
        "gx_charset",
    }
)
_ALLOWED_AUTH_PATHS = {
    "idm.swu.edu.cn": frozenset({"/am/oauth2/authorize", "/am/UI/Login"}),
    "uaaap.swu.edu.cn": frozenset({"/cas/login", "/cas/oauth2.0/authorize", "/cas/oauth2.0/callbackAuthorize"}),
    "of.swu.edu.cn": frozenset(
        {
            "/cas/login",
            "/cas/oauth/callback/SWU_CAS2_FEDERAL",
            "/gateway/fighter-middle/api/integrate/uaap/cas/resolve-cas-return",
        }
    ),
}


class OAuthDiscoveryError(ValueError):
    """The server response cannot be proven to be the expected SWU flow."""

    def __init__(
        self,
        message: str,
        *,
        reason: AuthFailureReason = AuthFailureReason.OAUTH_FLOW_CHANGED,
    ) -> None:
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True, repr=False)
class OAuthFlow:
    """Server-discovered values needed to submit one IDM login attempt."""

    login_page_url: str
    form_action: str
    hidden_fields: dict[str, str] = field(repr=False)
    state: str = field(repr=False)
    code_random: str = field(repr=False)
    captcha_url: str
    cas_callback_url: str

    @property
    def goto_value(self) -> str:
        return self.hidden_fields["goto"]


def validate_trusted_swu_url(
    url: str,
    *,
    expected_host: str | None = None,
    expected_path: str | None = None,
) -> urllib.parse.SplitResult:
    """Validate a request/redirect URL without ever including it in an error."""

    if (
        not isinstance(url, str)
        or not url
        or url != url.strip()
        or "\\" in url
        or any(ord(character) < 32 for character in url)
        or re.search(r"%(?![0-9A-Fa-f]{2})", url)
    ):
        raise OAuthDiscoveryError("认证 URL 格式无效")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as error:
        raise OAuthDiscoveryError("认证 URL 格式无效") from error
    hostname = parsed.hostname
    if (
        parsed.scheme != "https"
        or hostname not in TRUSTED_SWU_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or not parsed.path.startswith("/")
        or parsed.fragment
    ):
        raise OAuthDiscoveryError("认证 URL 不在可信 SWU HTTPS 边界内")
    if expected_host is not None and hostname != expected_host:
        raise OAuthDiscoveryError("认证 URL 主机与当前阶段不匹配")
    if expected_path is not None and parsed.path != expected_path:
        raise OAuthDiscoveryError("认证 URL 路径与当前阶段不匹配")
    return parsed


def _unique_query(
    url: str,
    *,
    required: frozenset[str] = frozenset(),
    allowed: frozenset[str] | None = None,
) -> dict[str, str]:
    try:
        parsed = urllib.parse.urlsplit(url)
        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except (TypeError, ValueError) as error:
        raise OAuthDiscoveryError("认证参数格式无效") from error
    values: dict[str, str] = {}
    for key, value in pairs:
        if not key or key in values:
            raise OAuthDiscoveryError("认证参数缺失或重复")
        values[key] = value
    if not required.issubset(values):
        raise OAuthDiscoveryError("认证参数缺失或重复")
    if allowed is not None and not values.keys() <= allowed:
        raise OAuthDiscoveryError("认证响应包含未知参数")
    return values


def resolve_trusted_redirect(
    response: requests.Response,
    *,
    expected_host: str | None = None,
    expected_path: str | None = None,
) -> str:
    """Resolve exactly one Location header and validate the resulting URL."""

    if response.status_code not in _REDIRECT_STATUSES:
        response.raise_for_status()
        raise OAuthDiscoveryError("认证服务未返回预期跳转")
    location = response.headers.get("Location")
    if not location:
        raise OAuthDiscoveryError("认证跳转缺少 Location")
    target = urllib.parse.urljoin(response.url, location)
    validate_trusted_swu_url(target, expected_host=expected_host, expected_path=expected_path)
    return target


def _resolve_legacy_idm_login_redirect(response: requests.Response) -> str:
    """Upgrade IDM's exact legacy HTTP Login Location without requesting HTTP."""

    if response.status_code not in _REDIRECT_STATUSES:
        response.raise_for_status()
        raise OAuthDiscoveryError("认证服务未返回预期跳转")
    location = response.headers.get("Location")
    if not location:
        raise OAuthDiscoveryError("认证跳转缺少 Location")
    raw_target = urllib.parse.urljoin(response.url, location)
    try:
        parsed = urllib.parse.urlsplit(raw_target)
        port = parsed.port
    except (TypeError, ValueError) as error:
        raise OAuthDiscoveryError("IDM login 跳转格式无效") from error
    if parsed.scheme == "http":
        if (
            parsed.hostname != "idm.swu.edu.cn"
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 80)
            or parsed.path != "/am/UI/Login"
            or parsed.fragment
        ):
            raise OAuthDiscoveryError("IDM legacy 跳转不在精确白名单内")
        raw_target = urllib.parse.urlunsplit(("https", "idm.swu.edu.cn", parsed.path, parsed.query, ""))
    validate_trusted_swu_url(
        raw_target,
        expected_host="idm.swu.edu.cn",
        expected_path="/am/UI/Login",
    )
    return raw_target


def _validate_oauth_authorize_url(url: str) -> tuple[str, str]:
    validate_trusted_swu_url(
        url,
        expected_host="uaaap.swu.edu.cn",
        expected_path="/cas/oauth2.0/authorize",
    )
    expected = frozenset({"response_type", "client_id", "redirect_uri", "state", "scope"})
    query = _unique_query(url, required=expected, allowed=expected)
    if query["response_type"] != "code" or not query["client_id"] or not query["scope"]:
        raise OAuthDiscoveryError("OAuth authorize 参数无效")
    state = query["state"]
    if not _STATE_RE.fullmatch(state):
        raise OAuthDiscoveryError("OAuth state 缺失或无效")
    callback_url = query["redirect_uri"]
    parsed_callback = validate_trusted_swu_url(
        callback_url,
        expected_host="of.swu.edu.cn",
        expected_path="/cas/oauth/callback/SWU_CAS2_FEDERAL",
    )
    if parsed_callback.query:
        raise OAuthDiscoveryError("CAS callback 包含意外参数")
    return state, callback_url


def _canonical_authorize_values(url: str) -> dict[str, str]:
    expected = frozenset({"service", "response_type", "client_id", "scope", "redirect_uri", "decision"})
    return _unique_query(url, required=expected, allowed=expected)


def _validate_legacy_authorize_url(value: str, expected_authorize_url: str) -> None:
    """Validate IDM's legacy authorize URL as data; the client never requests it."""

    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise OAuthDiscoveryError("登录表单 goto 无效") from error
    valid_port = (parsed.scheme == "http" and port in (None, 80)) or (parsed.scheme == "https" and port in (None, 443))
    if (
        not valid_port
        or parsed.hostname != "idm.swu.edu.cn"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/am/oauth2/authorize"
        or parsed.fragment
    ):
        raise OAuthDiscoveryError("登录表单 goto 超出预期范围")
    if _canonical_authorize_values(value) != _canonical_authorize_values(expected_authorize_url):
        raise OAuthDiscoveryError("登录表单 goto 与已发现流程不一致")


def _validate_hidden_goto(goto_value: str, expected_authorize_url: str) -> None:
    try:
        decoded = base64.b64decode(goto_value, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise OAuthDiscoveryError("登录表单 goto 无效") from error
    _validate_legacy_authorize_url(decoded, expected_authorize_url)


def _build_idm_authorize_url(cas_login_url: str) -> str:
    query = urllib.parse.urlencode(
        {
            "service": "initService",
            "response_type": "code",
            "client_id": IDM_OAUTH_CLIENT_ID,
            "scope": IDM_OAUTH_SCOPE,
            "redirect_uri": cas_login_url,
            "decision": "Allow",
        }
    )
    return f"{IDM_AUTHORIZE_URL}?{query}"


def _validate_cas_login_url(url: str, authorize_url: str) -> None:
    validate_trusted_swu_url(url, expected_host="uaaap.swu.edu.cn", expected_path="/cas/login")
    expected = frozenset({"service", "originalRequestUrl"})
    query = _unique_query(url, required=expected, allowed=expected)
    service = query["service"]
    service_parsed = validate_trusted_swu_url(
        service,
        expected_host="uaaap.swu.edu.cn",
        expected_path="/cas/oauth2.0/callbackAuthorize",
    )
    if service_parsed.query:
        raise OAuthDiscoveryError("CAS service callback 包含意外参数")
    if query["originalRequestUrl"] != authorize_url:
        raise OAuthDiscoveryError("CAS originalRequestUrl 与已发现流程不一致")


def _discover_federated_cas_login_url(cas_login_url: str, html: str) -> str:
    """Apply the exact federation flag advertised by the trusted CAS page."""

    if len(_FEDERAL_ENABLE_RE.findall(html)) != 1:
        raise OAuthDiscoveryError("CAS 登录页未唯一声明 federated 登录入口")
    parsed = validate_trusted_swu_url(
        cas_login_url,
        expected_host="uaaap.swu.edu.cn",
        expected_path="/cas/login",
    )
    query = _unique_query(cas_login_url)
    if "federalEnable" in query:
        raise OAuthDiscoveryError("CAS federated 参数重复")
    query["federalEnable"] = "true"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), ""))


def _validate_idm_login_url(url: str, expected_authorize_url: str) -> None:
    validate_trusted_swu_url(url, expected_host="idm.swu.edu.cn", expected_path="/am/UI/Login")
    expected = frozenset({"realm", "service", "goto"})
    query = _unique_query(url, required=expected, allowed=expected)
    if query["realm"] != "/" or query["service"] != "initService":
        raise OAuthDiscoveryError("IDM login 参数无效")
    _validate_legacy_authorize_url(query["goto"], expected_authorize_url)


def parse_login_form(
    html: str,
    *,
    page_url: str,
    state: str,
    cas_callback_url: str,
    expected_authorize_url: str,
) -> OAuthFlow:
    """Parse exactly one server-provided IDM password form."""

    validate_trusted_swu_url(page_url, expected_host="idm.swu.edu.cn", expected_path="/am/UI/Login")
    soup = BeautifulSoup(html, "html.parser")
    forms = soup.find_all("form", attrs={"name": "Login"})
    if len(forms) != 1:
        raise OAuthDiscoveryError(
            "登录页缺少唯一 Login form",
            reason=AuthFailureReason.LOGIN_PAGE_CHANGED,
        )
    form = forms[0]
    if str(form.get("method") or "get").lower() != "post":
        raise OAuthDiscoveryError("登录 form method 无效", reason=AuthFailureReason.LOGIN_PAGE_CHANGED)
    action = urllib.parse.urljoin(page_url, str(form.get("action") or ""))
    parsed_action = validate_trusted_swu_url(
        action,
        expected_host="idm.swu.edu.cn",
        expected_path="/am/UI/Login",
    )
    if parsed_action.query:
        raise OAuthDiscoveryError("登录 form action 包含意外参数", reason=AuthFailureReason.LOGIN_PAGE_CHANGED)

    hidden_fields: dict[str, str] = {}
    for input_field in form.find_all("input"):
        name = input_field.get("name")
        if not name:
            continue
        name = str(name)
        if not _INPUT_NAME_RE.fullmatch(name) or name in hidden_fields:
            raise OAuthDiscoveryError("登录 form 字段无效或重复", reason=AuthFailureReason.LOGIN_PAGE_CHANGED)
        if str(input_field.get("type") or "text").lower() != "hidden":
            raise OAuthDiscoveryError("登录 form 出现意外的可见字段", reason=AuthFailureReason.LOGIN_PAGE_CHANGED)
        hidden_fields[name] = str(input_field.get("value") or "")
    if not _REQUIRED_LOGIN_FIELDS.issubset(hidden_fields):
        raise OAuthDiscoveryError("登录 form 缺少必要 hidden input", reason=AuthFailureReason.LOGIN_PAGE_CHANGED)
    if hidden_fields["encoded"] != "true" or not hidden_fields["SunQueryParamsString"]:
        raise OAuthDiscoveryError("登录 form hidden input 无效", reason=AuthFailureReason.LOGIN_PAGE_CHANGED)
    _validate_hidden_goto(hidden_fields["goto"], expected_authorize_url)

    code_random_fields = soup.find_all("input", attrs={"id": "codeRandom"})
    if len(code_random_fields) != 1 or not code_random_fields[0].get("value"):
        raise OAuthDiscoveryError("登录页缺少唯一随机参数", reason=AuthFailureReason.LOGIN_PAGE_CHANGED)
    code_random = str(code_random_fields[0].get("value"))

    captcha_images = soup.find_all("img", attrs={"id": "kaptchaImage"})
    if len(captcha_images) != 1 or not captcha_images[0].get("src"):
        raise OAuthDiscoveryError("登录页缺少唯一验证码地址", reason=AuthFailureReason.LOGIN_PAGE_CHANGED)
    captcha_url = urllib.parse.urljoin(page_url, str(captcha_images[0].get("src")))
    parsed_captcha = validate_trusted_swu_url(
        captcha_url,
        expected_host="idm.swu.edu.cn",
        expected_path="/am/validate.code",
    )
    if parsed_captcha.query:
        raise OAuthDiscoveryError("验证码地址包含意外参数", reason=AuthFailureReason.LOGIN_PAGE_CHANGED)

    return OAuthFlow(
        login_page_url=page_url,
        form_action=action,
        hidden_fields=hidden_fields,
        state=state,
        code_random=code_random,
        captcha_url=captcha_url,
        cas_callback_url=cas_callback_url,
    )


def discover_login_flow(session: Any, timeout: int = 10) -> OAuthFlow:
    """Discover the current SWU login chain from trusted server responses."""

    validate_trusted_swu_url(
        CAS_LOGIN_ENTRY_URL,
        expected_host="of.swu.edu.cn",
        expected_path="/cas/oauth/login/SWU_CAS2_FEDERAL",
    )
    response = session.get(CAS_LOGIN_ENTRY_URL, timeout=timeout, allow_redirects=False)
    authorize_url = resolve_trusted_redirect(
        response,
        expected_host="uaaap.swu.edu.cn",
        expected_path="/cas/oauth2.0/authorize",
    )
    state, cas_callback_url = _validate_oauth_authorize_url(authorize_url)

    response = session.get(authorize_url, timeout=timeout, allow_redirects=False)
    cas_login_url = resolve_trusted_redirect(
        response,
        expected_host="uaaap.swu.edu.cn",
        expected_path="/cas/login",
    )
    _validate_cas_login_url(cas_login_url, authorize_url)

    response = session.get(cas_login_url, timeout=timeout, allow_redirects=False)
    if response.status_code != 200:
        response.raise_for_status()
        raise OAuthDiscoveryError("CAS 登录页未返回成功响应")
    federated_cas_login_url = _discover_federated_cas_login_url(cas_login_url, response.text)

    idm_authorize_url = _build_idm_authorize_url(federated_cas_login_url)
    validate_trusted_swu_url(
        idm_authorize_url,
        expected_host="idm.swu.edu.cn",
        expected_path="/am/oauth2/authorize",
    )
    response = session.get(idm_authorize_url, timeout=timeout, allow_redirects=False)
    login_url = _resolve_legacy_idm_login_redirect(response)
    _validate_idm_login_url(login_url, idm_authorize_url)

    for _ in range(3):
        response = session.get(login_url, timeout=timeout, allow_redirects=False)
        if response.status_code not in _REDIRECT_STATUSES:
            response.raise_for_status()
            return parse_login_form(
                response.text,
                page_url=response.url,
                state=state,
                cas_callback_url=cas_callback_url,
                expected_authorize_url=idm_authorize_url,
            )
        login_url = _resolve_legacy_idm_login_redirect(response)
        _validate_idm_login_url(login_url, idm_authorize_url)
    raise OAuthDiscoveryError("IDM 登录页跳转次数超限")


def build_login_form_data(
    flow: OAuthFlow,
    encrypted_username: str,
    encrypted_password: str,
    captcha: str,
) -> dict[str, str]:
    """Overlay credentials onto the server-provided hidden login fields."""

    data = dict(flow.hidden_fields)
    data.update(
        {
            "IDToken1": encrypted_username,
            "IDToken2": encrypted_password,
            "IDToken3": "",
            "validateCode": captcha,
        }
    )
    return data


def _validate_auth_chain_target(url: str) -> None:
    parsed = validate_trusted_swu_url(url)
    if parsed.hostname == "of.swu.edu.cn" and _TICKET_LANDING_RE.fullmatch(parsed.path):
        if parsed.query:
            raise OAuthDiscoveryError("ticket landing 包含意外参数")
        return
    if parsed.path not in _ALLOWED_AUTH_PATHS.get(parsed.hostname or "", frozenset()):
        raise OAuthDiscoveryError(
            f"认证跳转路径不在阶段白名单内 (host={parsed.hostname or 'missing'}, path={parsed.path})"
        )
    query = _unique_query(url)
    if parsed.hostname == "of.swu.edu.cn" and parsed.path.endswith("/resolve-cas-return"):
        if set(query) not in ({"next"}, {"next", "ticket"}) or ("ticket" in query and not query["ticket"]):
            raise OAuthDiscoveryError(f"CAS service return 参数无效 (keys={sorted(query)})")
        next_url = validate_trusted_swu_url(query["next"], expected_host="of.swu.edu.cn", expected_path="/")
        if next_url.query:
            raise OAuthDiscoveryError("CAS service next 参数无效")


def _service_return_fragment_ticket(url: str) -> str | None:
    """Return a ticket only from the exact SWU client-side service-return shape."""

    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "of.swu.edu.cn"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.path != "/gateway/fighter-middle/api/integrate/uaap/cas/resolve-cas-return"
    ):
        return None
    try:
        outer_query = _unique_query(url, required=frozenset({"next"}), allowed=frozenset({"next"}))
        next_url = validate_trusted_swu_url(
            outer_query["next"],
            expected_host="of.swu.edu.cn",
            expected_path="/",
        )
        if next_url.query:
            return None
        fragment_url = f"https://fragment.invalid/{parsed.fragment.lstrip('/')}"
        fragment = urllib.parse.urlsplit(fragment_url)
        fragment_query = _unique_query(
            fragment_url,
            required=frozenset({"from", "ticket"}),
            allowed=frozenset({"from", "ticket"}),
        )
    except OAuthDiscoveryError:
        return None
    if fragment.path != "/casLogin" or fragment_query["from"] != "/appCenter":
        return None
    return fragment_query["ticket"] or None


def describe_auth_response(response: requests.Response) -> str:
    """Return a non-sensitive stage label suitable for debug logs."""

    parsed = urllib.parse.urlsplit(response.url)
    if _TICKET_LANDING_RE.fullmatch(parsed.path):
        path = "/<ticket-landing>"
    elif parsed.path in _ALLOWED_AUTH_PATHS.get(parsed.hostname or "", frozenset()):
        path = parsed.path
    else:
        path = "/<unexpected-path>"
    return f"status={response.status_code} host={parsed.hostname or 'missing'} path={path}"


def follow_trusted_auth_redirects(
    session: Any,
    response: requests.Response,
    *,
    timeout: int,
    max_redirects: int = 8,
) -> requests.Response:
    """Follow a bounded authentication redirect chain one validated hop at a time."""

    for _ in range(max_redirects):
        if response.status_code not in _REDIRECT_STATUSES:
            return response
        location = response.headers.get("Location") or ""
        raw_target = urllib.parse.urljoin(response.url, location)
        fragment_ticket = _service_return_fragment_ticket(raw_target)
        if fragment_ticket:
            parsed_target = urllib.parse.urlsplit(raw_target)
            request_target = urllib.parse.urlunsplit(
                (parsed_target.scheme, parsed_target.netloc, parsed_target.path, parsed_target.query, "")
            )
            response = session.get(request_target, timeout=timeout, allow_redirects=False)
            if response.status_code not in _REDIRECT_STATUSES:
                response.url = raw_target
            continue
        try:
            target = resolve_trusted_redirect(response)
        except OAuthDiscoveryError as error:
            parsed = urllib.parse.urlsplit(raw_target)
            parsed_port: int | str | None
            try:
                parsed_port = parsed.port
            except ValueError:
                parsed_port = "invalid"
            if (
                parsed.scheme == "http"
                and parsed.hostname == "idm.swu.edu.cn"
                and parsed.username is None
                and parsed.password is None
                and parsed_port in (None, 80)
                and parsed.path in _ALLOWED_AUTH_PATHS["idm.swu.edu.cn"]
                and not parsed.fragment
            ):
                target = urllib.parse.urlunsplit(("https", "idm.swu.edu.cn", parsed.path, parsed.query, ""))
                validate_trusted_swu_url(target)
            elif (
                parsed.scheme == "https"
                and parsed.hostname == "of.swu.edu.cn"
                and parsed.username is None
                and parsed.password is None
                and parsed_port in (None, 443)
                and parsed.path == "/gateway/fighter-middle/api/integrate/uaap/cas/resolve-cas-return"
                and parsed.fragment == "/casLogin?from=/appCenter"
            ):
                target = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
                validate_trusted_swu_url(target)
            else:
                path = "/<ticket-landing>" if _TICKET_LANDING_RE.fullmatch(parsed.path) else parsed.path
                fragment = urllib.parse.urlsplit(f"https://fragment.invalid/{parsed.fragment.lstrip('/')}")
                fragment_keys = sorted(_unique_query(urllib.parse.urlunsplit(fragment))) if parsed.fragment else []
                raise OAuthDiscoveryError(
                    f"认证跳转不可信 (scheme={parsed.scheme or 'missing'}, "
                    f"host={parsed.hostname or 'missing'}, path={path or 'missing'}, "
                    f"port={parsed_port or 'default'}, fragment_path={fragment.path if parsed.fragment else 'none'}, "
                    f"fragment_keys={fragment_keys})"
                ) from error
        _validate_auth_chain_target(target)
        response = session.get(target, timeout=timeout, allow_redirects=False)
    raise OAuthDiscoveryError("认证跳转次数超限")


def build_cas_callback_url(flow: OAuthFlow, transformed_ticket: str) -> str:
    """Build the callback from the server-discovered callback URL and state."""

    validate_trusted_swu_url(
        flow.cas_callback_url,
        expected_host="of.swu.edu.cn",
        expected_path="/cas/oauth/callback/SWU_CAS2_FEDERAL",
    )
    query = urllib.parse.urlencode({"code": f"{transformed_ticket}@@hxbeat", "state": flow.state})
    return f"{flow.cas_callback_url}?{query}"


def extract_ticket_from_url(url: str) -> str | None:
    """Extract one unambiguous ticket from a validated callback/landing URL."""

    service_ticket = _service_return_fragment_ticket(url)
    if service_ticket:
        return service_ticket
    try:
        parsed = validate_trusted_swu_url(url)
        query = _unique_query(url)
    except OAuthDiscoveryError:
        return None
    if (
        parsed.hostname == "uaaap.swu.edu.cn"
        and parsed.path == "/cas/oauth2.0/callbackAuthorize"
        and set(query) == {"ticket"}
    ):
        return query["ticket"] or None
    if (
        parsed.hostname == "of.swu.edu.cn"
        and parsed.path == "/gateway/fighter-middle/api/integrate/uaap/cas/resolve-cas-return"
        and set(query) == {"next", "ticket"}
    ):
        try:
            next_url = validate_trusted_swu_url(
                query["next"],
                expected_host="of.swu.edu.cn",
                expected_path="/",
            )
        except OAuthDiscoveryError:
            return None
        return query["ticket"] if query["ticket"] and not next_url.query else None
    match = _TICKET_LANDING_RE.fullmatch(parsed.path)
    if parsed.hostname != "of.swu.edu.cn" or query or not match:
        return None
    ticket = urllib.parse.unquote(match.group(1))
    return ticket or None


def validate_idm_login_response(response: requests.Response) -> None:
    """Accept only SWU's strictly validated ticket-bearing 412 callback."""

    if response.status_code == 412:
        try:
            validate_trusted_swu_url(
                response.url,
                expected_host="uaaap.swu.edu.cn",
                expected_path="/cas/oauth2.0/callbackAuthorize",
            )
            query = _unique_query(
                response.url,
                required=frozenset({"ticket"}),
                allowed=frozenset({"ticket"}),
            )
            if query["ticket"]:
                return
        except OAuthDiscoveryError:
            pass
    response.raise_for_status()


def validate_cas_callback_response(response: requests.Response) -> None:
    """Accept only SWU's strictly validated ticket-bearing 404 landing page."""

    if response.status_code == 404:
        try:
            parsed = validate_trusted_swu_url(response.url, expected_host="of.swu.edu.cn")
            if not parsed.query and _TICKET_LANDING_RE.fullmatch(parsed.path) and extract_ticket_from_url(response.url):
                return
        except OAuthDiscoveryError:
            pass
    response.raise_for_status()
