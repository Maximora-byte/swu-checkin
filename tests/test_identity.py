import base64
import urllib.parse
from unittest.mock import Mock

import pytest
import requests

from swu_checkin import oauth_flow
from swu_checkin.identity import identity_selection_data, submit_identity_selection_if_needed

STATE = "0123456789abcdef0123456789abcdef"
CALLBACK_URL = "https://of.swu.edu.cn/cas/oauth/callback/SWU_CAS2_FEDERAL"
LOGIN_URL = "https://idm.swu.edu.cn/am/UI/Login"


def _response(status: int, url: str, *, location: str | None = None, text: str = "") -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = url
    response._content = text.encode()
    if location is not None:
        response.headers["Location"] = location
    return response


def _validated_flow() -> oauth_flow.OAuthFlow:
    authorize_url = "https://uaaap.swu.edu.cn/cas/oauth2.0/authorize?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": "cas6",
            "redirect_uri": CALLBACK_URL,
            "state": STATE,
            "scope": "simple",
        }
    )
    cas_login_url = "https://uaaap.swu.edu.cn/cas/login?" + urllib.parse.urlencode(
        {
            "service": "https://uaaap.swu.edu.cn/cas/oauth2.0/callbackAuthorize",
            "originalRequestUrl": authorize_url,
            "federalEnable": "true",
        }
    )
    idm_authorize_url = oauth_flow._build_idm_authorize_url(cas_login_url)
    parsed = urllib.parse.urlsplit(idm_authorize_url)
    legacy_authorize_url = urllib.parse.urlunsplit(("http", parsed.netloc, parsed.path, parsed.query, ""))
    goto_value = base64.b64encode(legacy_authorize_url.encode()).decode()
    login_html = (
        '<form name="Login" method="post" action="/am/UI/Login">'
        '<input type="hidden" name="IDToken1" value="">'
        '<input type="hidden" name="IDToken2" value="">'
        '<input type="hidden" name="IDToken3" value="">'
        f'<input type="hidden" name="goto" value="{goto_value}">'
        '<input type="hidden" name="gotoOnFail" value="">'
        '<input type="hidden" name="SunQueryParamsString" value="server-query">'
        '<input type="hidden" name="encoded" value="true">'
        '<input type="hidden" name="validateCode" value="">'
        '<input type="hidden" name="gx_charset" value="UTF-8">'
        "</form>"
        '<input id="codeRandom" value="random-value">'
        '<img id="kaptchaImage" src="/am/validate.code">'
    )
    return oauth_flow.parse_login_form(
        login_html,
        page_url=LOGIN_URL,
        state=STATE,
        cas_callback_url=CALLBACK_URL,
        expected_authorize_url=idm_authorize_url,
    )


def _identity_html(*, goto_value: str = "attacker-controlled-goto", duplicate: str = "") -> str:
    return (
        '<input name="identityDefault">'
        '<script>var defaultCodes = "undergraduate:本科生;postgraduate:研究生";</script>'
        '<form name="Login" method="post" action="/am/UI/Login">'
        '<input type="hidden" name="IDToken1" value="attacker-identity">'
        '<input type="hidden" name="IDToken2" value="attacker-password">'
        '<input type="hidden" name="IDToken3" value="attacker-third-token">'
        f'<input type="hidden" name="goto" value="{goto_value}">'
        f"{duplicate}"
        '<input type="hidden" name="serverNonce" value="server-nonce">'
        "</form>"
    )


def test_identity_selection_keeps_program_owned_fields():
    flow = _validated_flow()

    data = identity_selection_data(
        _identity_html(),
        "postgraduate",
        goto_value=flow.goto_value,
    )

    assert data["IDToken1"] == "postgraduate"
    assert data["IDToken2"] == ""
    assert data["IDToken3"] == ""
    assert data["goto"] == flow.goto_value
    assert data["serverNonce"] == "server-nonce"


@pytest.mark.parametrize(
    "duplicate",
    [
        '<input type="hidden" name="goto" value="second-goto">',
        '<input type="hidden" name="serverNonce" value="second-nonce">',
    ],
)
def test_identity_selection_rejects_duplicate_fields(duplicate: str):
    flow = _validated_flow()

    with pytest.raises(oauth_flow.OAuthDiscoveryError, match="重复"):
        identity_selection_data(
            _identity_html(duplicate=duplicate),
            "postgraduate",
            goto_value=flow.goto_value,
        )


def test_identity_selection_rejects_malformed_hidden_field_name():
    flow = _validated_flow()
    malformed = '<input type="hidden" name="bad field" value="value">'

    with pytest.raises(oauth_flow.OAuthDiscoveryError, match="无效"):
        identity_selection_data(
            _identity_html(duplicate=malformed),
            "postgraduate",
            goto_value=flow.goto_value,
        )


def test_identity_selection_flow_uses_trusted_endpoint_and_validated_redirects():
    flow = _validated_flow()
    initial = _response(
        200,
        "https://idm.swu.edu.cn/am/UI/Login?notice=ticket-selection-required",
        text=_identity_html(),
    )
    post_response = _response(
        302,
        flow.form_action,
        location="https://uaaap.swu.edu.cn/cas/oauth2.0/callbackAuthorize?ticket=ST-identity",
    )
    callback = _response(
        412,
        "https://uaaap.swu.edu.cn/cas/oauth2.0/callbackAuthorize?ticket=ST-identity",
    )
    session = Mock()
    session.post.return_value = post_response
    session.get.return_value = callback

    selected = submit_identity_selection_if_needed(
        session,
        initial,
        login_url=flow.form_action,
        goto_value=flow.goto_value,
        timeout=5,
        allow_redirects=False,
    )
    submitted_url = session.post.call_args.args[0]
    submitted_data = session.post.call_args.kwargs["data"]

    assert submitted_url == LOGIN_URL
    assert submitted_data["goto"] == flow.goto_value
    assert submitted_data["IDToken1"] == "postgraduate"
    assert submitted_data["IDToken2"] == ""
    assert submitted_data["IDToken3"] == ""
    assert session.post.call_args.kwargs["allow_redirects"] is False

    final = oauth_flow.follow_trusted_auth_redirects(session, selected, timeout=5)
    oauth_flow.validate_idm_login_response(final)
    assert oauth_flow.extract_ticket_from_url(final.url) == "ST-identity"
    session.get.assert_called_once_with(
        "https://uaaap.swu.edu.cn/cas/oauth2.0/callbackAuthorize?ticket=ST-identity",
        timeout=5,
        allow_redirects=False,
    )


def test_valid_ticket_callback_skips_identity_selection():
    flow = _validated_flow()
    response = _response(
        412,
        "https://uaaap.swu.edu.cn/cas/oauth2.0/callbackAuthorize?ticket=ST-valid",
        text=_identity_html(),
    )
    session = Mock()

    result = submit_identity_selection_if_needed(
        session,
        response,
        login_url=flow.form_action,
        goto_value=flow.goto_value,
    )

    assert result is response
    session.post.assert_not_called()


def test_identity_selection_rejects_untrusted_post_endpoint():
    flow = _validated_flow()
    response = _response(200, LOGIN_URL, text=_identity_html())
    session = Mock()

    with pytest.raises(oauth_flow.OAuthDiscoveryError):
        submit_identity_selection_if_needed(
            session,
            response,
            login_url="https://evil.example/am/UI/Login",
            goto_value=flow.goto_value,
        )

    session.post.assert_not_called()
