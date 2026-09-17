import base64
import urllib.parse
from collections.abc import Iterator
from unittest.mock import Mock

import pytest
import requests

from swu_checkin import oauth_flow

STATE = "0123456789abcdef0123456789abcdef"
CALLBACK_URL = "https://of.swu.edu.cn/cas/oauth/callback/SWU_CAS2_FEDERAL"


def _response(status: int, url: str, *, location: str | None = None, text: str = "") -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = url
    response._content = text.encode()
    if location is not None:
        response.headers["Location"] = location
    return response


def _authorize_url(*, state: str = STATE, extra: list[tuple[str, str]] | None = None) -> str:
    params = [
        ("response_type", "code"),
        ("client_id", "cas6"),
        ("redirect_uri", CALLBACK_URL),
        ("state", state),
        ("scope", "simple"),
    ]
    params.extend(extra or [])
    return f"https://uaaap.swu.edu.cn/cas/oauth2.0/authorize?{urllib.parse.urlencode(params)}"


def _cas_login_url(authorize_url: str) -> str:
    return "https://uaaap.swu.edu.cn/cas/login?" + urllib.parse.urlencode(
        {
            "service": "https://uaaap.swu.edu.cn/cas/oauth2.0/callbackAuthorize",
            "originalRequestUrl": authorize_url,
        }
    )


def _legacy_authorize_url(idm_authorize_url: str) -> str:
    parsed = urllib.parse.urlsplit(idm_authorize_url)
    return urllib.parse.urlunsplit(("http", parsed.netloc, parsed.path, parsed.query, ""))


def _login_url(idm_authorize_url: str, *, scheme: str = "http") -> str:
    legacy_goto = _legacy_authorize_url(idm_authorize_url)
    return f"{scheme}://idm.swu.edu.cn/am/UI/Login?" + urllib.parse.urlencode(
        {"realm": "/", "service": "initService", "goto": legacy_goto}
    )


def _login_html(idm_authorize_url: str, *, action: str = "/am/UI/Login", omit: str | None = None) -> str:
    hidden = {
        "IDToken1": "",
        "IDToken2": "",
        "IDToken3": "",
        "goto": base64.b64encode(_legacy_authorize_url(idm_authorize_url).encode()).decode(),
        "gotoOnFail": "",
        "SunQueryParamsString": "cmVhbG09LyZzZXJ2aWNlPWluaXRTZXJ2aWNlJg==",
        "encoded": "true",
        "validateCode": "",
        "gx_charset": "UTF-8",
        "serverNonce": "nonce-value",
    }
    if omit:
        hidden.pop(omit)
    inputs = "".join(f'<input type="hidden" name="{name}" value="{value}">' for name, value in hidden.items())
    return (
        f'<form name="Login" method="post" action="{action}">{inputs}</form>'
        '<input id="codeRandom" value="random-value">'
        '<img id="kaptchaImage" src="/am/validate.code">'
    )


class FakeSession:
    def __init__(self, responses: list[requests.Response]):
        self._responses: Iterator[requests.Response] = iter(responses)
        self.get_calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> requests.Response:
        self.get_calls.append((url, kwargs))
        return next(self._responses)


def _valid_discovery_session() -> tuple[FakeSession, str, str, str]:
    authorize_url = _authorize_url()
    cas_login_url = _cas_login_url(authorize_url)
    federated_cas_login_url = f"{cas_login_url}&federalEnable=true"
    idm_authorize_url = oauth_flow._build_idm_authorize_url(federated_cas_login_url)
    login_url = _login_url(idm_authorize_url)
    secure_login_url = login_url.replace("http://", "https://", 1)
    session = FakeSession(
        [
            _response(302, oauth_flow.CAS_LOGIN_ENTRY_URL, location=authorize_url),
            _response(302, authorize_url, location=cas_login_url),
            _response(
                200,
                cas_login_url,
                text="<script>window.location.href = url + 'federalEnable=true';</script>",
            ),
            _response(302, idm_authorize_url, location=login_url),
            _response(200, secure_login_url, text=_login_html(idm_authorize_url)),
        ]
    )
    return session, idm_authorize_url, secure_login_url, federated_cas_login_url


def test_discovers_valid_flow_from_server_redirects_and_form():
    session, idm_authorize_url, secure_login_url, cas_login_url = _valid_discovery_session()

    flow = oauth_flow.discover_login_flow(session, timeout=7)

    assert flow.state == STATE
    assert flow.login_page_url == secure_login_url
    assert flow.form_action == "https://idm.swu.edu.cn/am/UI/Login"
    assert flow.captcha_url == "https://idm.swu.edu.cn/am/validate.code"
    assert flow.cas_callback_url == CALLBACK_URL
    assert flow.hidden_fields["serverNonce"] == "nonce-value"
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(idm_authorize_url).query)["redirect_uri"] == [cas_login_url]
    assert all(kwargs["allow_redirects"] is False for _, kwargs in session.get_calls)


def test_login_payload_preserves_server_fields_and_overlays_secrets():
    session, _, _, _ = _valid_discovery_session()
    flow = oauth_flow.discover_login_flow(session)

    payload = oauth_flow.build_login_form_data(flow, "encrypted-user", "encrypted-password", "captcha")

    assert payload["serverNonce"] == "nonce-value"
    assert payload["IDToken1"] == "encrypted-user"
    assert payload["IDToken2"] == "encrypted-password"
    assert payload["validateCode"] == "captcha"


@pytest.mark.parametrize(
    "url",
    [
        "http://idm.swu.edu.cn/am/UI/Login",
        "https://evil.example/am/UI/Login",
        "https://swu.edu.cn.evil.example/am/UI/Login",
        "https://user:pass@idm.swu.edu.cn/am/UI/Login",
        "https://idm.swu.edu.cn:444/am/UI/Login",
        "https://idm.swu.edu.cn/%zz",
        "not-a-url",
    ],
)
def test_untrusted_or_malformed_urls_fail_closed(url: str):
    with pytest.raises(oauth_flow.OAuthDiscoveryError):
        oauth_flow.validate_trusted_swu_url(url)


def test_valid_swu_https_url_and_default_443_are_accepted():
    assert oauth_flow.validate_trusted_swu_url("https://idm.swu.edu.cn/am/UI/Login").hostname == "idm.swu.edu.cn"
    assert oauth_flow.validate_trusted_swu_url("https://idm.swu.edu.cn:443/am/UI/Login").hostname == "idm.swu.edu.cn"


def test_redirect_without_location_fails_closed():
    response = _response(302, oauth_flow.CAS_LOGIN_ENTRY_URL)

    with pytest.raises(oauth_flow.OAuthDiscoveryError, match="Location"):
        oauth_flow.resolve_trusted_redirect(response)


@pytest.mark.parametrize(
    "authorize_url",
    [
        _authorize_url(state=""),
        _authorize_url(extra=[("state", "another-state-value")]),
        _authorize_url(extra=[("client_id", "second-client")]),
        _authorize_url().replace("/cas/oauth2.0/authorize", "/cas/unexpected"),
        _authorize_url().replace("https://uaaap.swu.edu.cn", "https://evil.example"),
    ],
)
def test_missing_duplicated_or_untrusted_oauth_state_flow_fails_closed(authorize_url: str):
    with pytest.raises(oauth_flow.OAuthDiscoveryError):
        oauth_flow._validate_oauth_authorize_url(authorize_url)


def test_cas_login_requires_matching_original_request():
    authorize_url = _authorize_url()
    wrong = _cas_login_url(_authorize_url(state="fedcba9876543210fedcba9876543210"))

    with pytest.raises(oauth_flow.OAuthDiscoveryError, match="originalRequestUrl"):
        oauth_flow._validate_cas_login_url(wrong, authorize_url)


def test_missing_or_ambiguous_federation_instruction_fails_closed():
    cas_login_url = _cas_login_url(_authorize_url())

    with pytest.raises(oauth_flow.OAuthDiscoveryError):
        oauth_flow._discover_federated_cas_login_url(cas_login_url, "<html>missing marker</html>")
    duplicate = "window.location.href = url + 'federalEnable=true';" * 2
    with pytest.raises(oauth_flow.OAuthDiscoveryError):
        oauth_flow._discover_federated_cas_login_url(cas_login_url, duplicate)


@pytest.mark.parametrize(
    "html",
    [
        "<html><body>no form</body></html>",
        '<form name="Login" method="get"></form>',
        '<form name="Login" method="post"></form><form name="Login" method="post"></form>',
    ],
)
def test_missing_or_malformed_login_form_fails_closed(html: str):
    cas_login_url = _cas_login_url(_authorize_url())
    idm_authorize_url = oauth_flow._build_idm_authorize_url(cas_login_url)

    with pytest.raises(oauth_flow.OAuthDiscoveryError):
        oauth_flow.parse_login_form(
            html,
            page_url="https://idm.swu.edu.cn/am/UI/Login",
            state=STATE,
            cas_callback_url=CALLBACK_URL,
            expected_authorize_url=idm_authorize_url,
        )


def test_missing_required_hidden_input_fails_closed():
    cas_login_url = _cas_login_url(_authorize_url())
    idm_authorize_url = oauth_flow._build_idm_authorize_url(cas_login_url)

    with pytest.raises(oauth_flow.OAuthDiscoveryError, match="hidden input"):
        oauth_flow.parse_login_form(
            _login_html(idm_authorize_url, omit="goto"),
            page_url="https://idm.swu.edu.cn/am/UI/Login",
            state=STATE,
            cas_callback_url=CALLBACK_URL,
            expected_authorize_url=idm_authorize_url,
        )


@pytest.mark.parametrize("missing_id", ["codeRandom", "kaptchaImage"])
def test_missing_random_or_captcha_metadata_fails_closed(missing_id: str):
    cas_login_url = _cas_login_url(_authorize_url())
    idm_authorize_url = oauth_flow._build_idm_authorize_url(cas_login_url)
    html = _login_html(idm_authorize_url).replace(f'id="{missing_id}"', 'id="removed"')

    with pytest.raises(oauth_flow.OAuthDiscoveryError):
        oauth_flow.parse_login_form(
            html,
            page_url="https://idm.swu.edu.cn/am/UI/Login",
            state=STATE,
            cas_callback_url=CALLBACK_URL,
            expected_authorize_url=idm_authorize_url,
        )


@pytest.mark.parametrize(
    "action",
    [
        "http://idm.swu.edu.cn/am/UI/Login",
        "https://evil.example/am/UI/Login",
        "https://idm.swu.edu.cn:444/am/UI/Login",
        "https://idm.swu.edu.cn/am/unexpected",
    ],
)
def test_untrusted_login_form_action_fails_closed(action: str):
    cas_login_url = _cas_login_url(_authorize_url())
    idm_authorize_url = oauth_flow._build_idm_authorize_url(cas_login_url)

    with pytest.raises(oauth_flow.OAuthDiscoveryError):
        oauth_flow.parse_login_form(
            _login_html(idm_authorize_url, action=action),
            page_url="https://idm.swu.edu.cn/am/UI/Login",
            state=STATE,
            cas_callback_url=CALLBACK_URL,
            expected_authorize_url=idm_authorize_url,
        )


def test_unknown_redirect_host_is_rejected_before_next_request():
    response = _response(302, "https://idm.swu.edu.cn/am/UI/Login", location="https://evil.example/callback")
    session = Mock()

    with pytest.raises(oauth_flow.OAuthDiscoveryError):
        oauth_flow.follow_trusted_auth_redirects(session, response, timeout=10)

    session.get.assert_not_called()


def test_legacy_idm_http_redirect_is_upgraded_but_other_http_is_rejected():
    valid = _response(
        302,
        oauth_flow.IDM_AUTHORIZE_URL,
        location="http://idm.swu.edu.cn/am/UI/Login?realm=/&service=initService&goto=value",
    )
    assert oauth_flow._resolve_legacy_idm_login_redirect(valid).startswith("https://idm.swu.edu.cn/")

    invalid = _response(302, oauth_flow.IDM_AUTHORIZE_URL, location="http://evil.example/am/UI/Login")
    with pytest.raises(oauth_flow.OAuthDiscoveryError):
        oauth_flow._resolve_legacy_idm_login_redirect(invalid)


@pytest.mark.parametrize(
    ("scheme", "port"),
    [
        ("http", None),
        ("http", 80),
        ("https", None),
        ("https", 443),
    ],
)
def test_legacy_authorize_url_accepts_only_matching_default_ports(scheme: str, port: int | None):
    cas_login_url = _cas_login_url(_authorize_url())
    expected = oauth_flow._build_idm_authorize_url(cas_login_url)
    parsed = urllib.parse.urlsplit(expected)
    netloc = parsed.hostname if port is None else f"{parsed.hostname}:{port}"
    legacy = urllib.parse.urlunsplit((scheme, netloc, parsed.path, parsed.query, ""))

    oauth_flow._validate_legacy_authorize_url(legacy, expected)


@pytest.mark.parametrize(
    "url",
    [
        "http://idm.swu.edu.cn:443/am/oauth2/authorize",
        "https://idm.swu.edu.cn:80/am/oauth2/authorize",
    ],
)
def test_legacy_authorize_url_rejects_mismatched_scheme_and_port(url: str):
    cas_login_url = _cas_login_url(_authorize_url())
    expected = oauth_flow._build_idm_authorize_url(cas_login_url)
    query = urllib.parse.urlsplit(expected).query

    with pytest.raises(oauth_flow.OAuthDiscoveryError):
        oauth_flow._validate_legacy_authorize_url(f"{url}?{query}", expected)


def test_callback_builder_uses_discovered_callback_and_state():
    session, _, _, _ = _valid_discovery_session()
    flow = oauth_flow.discover_login_flow(session)

    callback = oauth_flow.build_cas_callback_url(flow, "ticket-value")
    parsed = urllib.parse.urlsplit(callback)
    query = urllib.parse.parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.hostname}{parsed.path}" == CALLBACK_URL
    assert query == {"code": ["ticket-value@@hxbeat"], "state": [STATE]}


def test_ticket_extraction_rejects_duplicate_ticket_parameter():
    assert (
        oauth_flow.extract_ticket_from_url(
            "https://uaaap.swu.edu.cn/cas/oauth2.0/callbackAuthorize?ticket=one&ticket=two"
        )
        is None
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://uaaap.swu.edu.cn/cas/oauth2.0/callbackAuthorize?ticket=ST-test", "ST-test"),
        ("https://of.swu.edu.cn/&ticket=ST-test", "ST-test"),
        (
            "https://of.swu.edu.cn/gateway/fighter-middle/api/integrate/uaap/cas/resolve-cas-return"
            "?next=https%3A%2F%2Fof.swu.edu.cn%2F&ticket=ST-test",
            "ST-test",
        ),
        (
            "https://of.swu.edu.cn/gateway/fighter-middle/api/integrate/uaap/cas/resolve-cas-return"
            "?next=https%3A%2F%2Fof.swu.edu.cn%2F#/casLogin?from=/appCenter&ticket=ST-test",
            "ST-test",
        ),
        ("https://evil.example/callback?ticket=ST-test", None),
        ("https://of.swu.edu.cn/unexpected?ticket=ST-test", None),
    ],
)
def test_ticket_extraction_is_limited_to_exact_callback_shapes(url: str, expected: str | None):
    assert oauth_flow.extract_ticket_from_url(url) == expected


def test_manual_redirect_follow_preserves_strict_404_landing():
    first = _response(
        302,
        CALLBACK_URL,
        location="https://of.swu.edu.cn/&ticket=ST-test",
    )
    final = _response(404, "https://of.swu.edu.cn/&ticket=ST-test")
    session = FakeSession([final])

    response = oauth_flow.follow_trusted_auth_redirects(session, first, timeout=5)

    assert response is final
    oauth_flow.validate_cas_callback_response(response)
    assert oauth_flow.extract_ticket_from_url(response.url) == "ST-test"
    assert session.get_calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize(
    "url",
    [
        "https://of.swu.edu.cn/gateway/fighter-middle/api/integrate/uaap/cas/resolve-cas-return"
        "?next=https%3A%2F%2Fevil.example%2F&ticket=ST-test",
        "https://of.swu.edu.cn/gateway/fighter-middle/api/integrate/uaap/cas/resolve-cas-return"
        "?next=https%3A%2F%2Fof.swu.edu.cn%2F&ticket=one&ticket=two",
        "https://of.swu.edu.cn/gateway/fighter-middle/api/integrate/uaap/cas/resolve-cas-return"
        "?next=https%3A%2F%2Fof.swu.edu.cn%2F#/unexpected?from=/appCenter&ticket=ST-test",
    ],
)
def test_service_return_ticket_shape_fails_closed_when_ambiguous(url: str):
    assert oauth_flow.extract_ticket_from_url(url) is None
