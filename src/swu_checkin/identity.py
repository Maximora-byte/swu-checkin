"""Helpers for SWU's optional student identity selection page."""

import re
from typing import Any

from bs4 import BeautifulSoup

from .oauth_flow import OAuthDiscoveryError, extract_ticket_from_url, validate_trusted_swu_url

_IDENTITY_CODES_RE = re.compile(r"(?:var|let|const)\s+defaultCodes\s*=\s*['\"]([^'\"]*)['\"]")
_IDENTITY_FIELD_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")
_PROGRAM_OWNED_FIELDS = frozenset({"IDToken1", "IDToken2", "IDToken3", "goto"})
_SERVER_FIELD_DEFAULTS = {
    "gotoOnFail": "",
    "SunQueryParamsString": "",
    "encoded": "true",
    "gx_charset": "UTF-8",
}


def choose_identity_code(html: str) -> str | None:
    """Choose postgraduate identity when SWU offers multiple identities."""

    if not re.search(r"(?:name|id)\s*=\s*['\"]identityDefault['\"]", html):
        return None
    match = _IDENTITY_CODES_RE.search(html)
    if not match:
        return None

    identities: list[tuple[str, str]] = []
    for item in match.group(1).split(";"):
        code, separator, label = item.partition(":")
        code = code.strip()
        if separator and code:
            identities.append((code, label.strip()))
    if not identities:
        return None

    for code, label in identities:
        normalized = f"{code} {label}".lower()
        if any(marker in normalized for marker in ("yanjiusheng", "研究生", "硕士", "博士")):
            return code
    return identities[0][0]


def identity_selection_data(html: str, identity_code: str, *, goto_value: str) -> dict[str, str]:
    """Build the IDM form payload for a selected identity."""

    soup = BeautifulSoup(html, "html.parser")
    forms = soup.find_all("form", attrs={"name": "Login"})
    if len(forms) != 1:
        raise OAuthDiscoveryError("身份选择页缺少唯一 Login form")

    form = forms[0]
    # The page owns only non-reserved hidden metadata. Authentication-critical
    # fields are supplied by the client below and can never be imported here.
    server_fields = dict(_SERVER_FIELD_DEFAULTS)
    seen_fields: set[str] = set()
    for field in form.find_all("input"):
        name = field.get("name")
        if not name:
            continue
        name = str(name)
        if not _IDENTITY_FIELD_NAME_RE.fullmatch(name) or name in seen_fields:
            raise OAuthDiscoveryError("身份选择 form 字段无效或重复")
        seen_fields.add(name)
        if name in _PROGRAM_OWNED_FIELDS:
            continue
        if str(field.get("type") or "text").lower() != "hidden":
            continue
        server_fields[name] = str(field.get("value") or "")

    return {
        **server_fields,
        "IDToken1": identity_code,
        "IDToken2": "",
        "IDToken3": "",
        "goto": goto_value,
    }


def submit_identity_selection_if_needed(
    session: Any,
    response: Any,
    *,
    login_url: str,
    goto_value: str,
    **request_kwargs: Any,
) -> Any:
    """Submit the preferred identity when the initial login response asks for it."""

    if extract_ticket_from_url(str(response.url)):
        return response
    identity_code = choose_identity_code(response.text)
    if not identity_code:
        return response
    parsed_login_url = validate_trusted_swu_url(
        login_url,
        expected_host="idm.swu.edu.cn",
        expected_path="/am/UI/Login",
    )
    if parsed_login_url.query:
        raise OAuthDiscoveryError("身份选择提交地址包含意外参数")
    data = identity_selection_data(response.text, identity_code, goto_value=goto_value)
    return session.post(login_url, data=data, **request_kwargs)
