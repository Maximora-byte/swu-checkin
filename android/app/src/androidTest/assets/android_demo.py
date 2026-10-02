"""Instrumentation-only synthetic transport. Never packaged in the client APK."""

from __future__ import annotations

import struct
import zlib
from unittest.mock import patch

import requests
from android_client import AndroidClient

from swu_checkin import get_info
from swu_checkin.api_models import DormitoryInfo, LeaveRecords, StudentProfile, Transition
from swu_checkin.oauth_flow import OAuthFlow


# Valid tiny PNG exercises the Java byte[] boundary and bounded image decoder.
def png_chunk(kind, data):
    return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))


IMAGE = (
    b"\x89PNG\r\n\x1a\n"
    + png_chunk(b"IHDR", struct.pack("!IIBBBBB", 2, 2, 8, 6, 0, 0, 0))
    + png_chunk(b"IDAT", zlib.compress((b"\x00" + b"\xff" * 8) * 2))
    + png_chunk(b"IEND", b"")
)
USER = "synthetic-user"
SECRET = "synthetic-password"


def response(url, content=b"", status=200):
    result = requests.Response()
    result.url, result._content, result.status_code = url, content, status
    return result


class DemoClient:
    def __init__(self):
        self.submissions = 0
        self.checked = False
        self.student = USER
        self.state = "pending"

    def get_student_id(self):
        return self.student

    def get_student_profile(self):
        return StudentProfile(student_id=self.student)

    def get_leave_record_set(self):
        return LeaveRecords.from_items([])

    def get_dormitory_info(self):
        return DormitoryInfo(29.8, 106.4, "synthetic-building", "synthetic-room")

    def get_transition(self):
        if self.state == "no_task":
            return None
        return Transition("synthetic-record", "synthetic-form", "已签到" if self.checked else "未签到")

    def submit_checkin_form(self, *, form_id, payload):
        self.submissions += 1
        self.checked = True
        return {"code": "200", "success": True}


class DemoSession:
    def __init__(self, flow):
        self.flow = flow
        self.cookies = requests.cookies.RequestsCookieJar()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def close(self):
        pass

    def get(self, url, **kwargs):
        assert kwargs["allow_redirects"] is False
        if url == self.flow.captcha_url:
            return response(url, IMAGE)
        if url.startswith(self.flow.cas_callback_url + "?"):
            return response("https://of.swu.edu.cn/&ticket=synthetic-token-ticket", status=404)
        assert url == get_info.TOKEN_EXCHANGE_URL
        return response(url, b'{"data":"synthetic-token"}')

    def post(self, url, **kwargs):
        assert url == self.flow.form_action
        assert kwargs["data"]["validateCode"] == "Ab12"
        return response("https://uaaap.swu.edu.cn/cas/oauth2.0/callbackAuthorize?ticket=synthetic-identity", status=412)


def make_android_demo(broker, lock_path, *, provider=None):
    backend = DemoClient()
    flow = OAuthFlow(
        login_page_url="https://idm.swu.edu.cn/am/UI/Login",
        form_action="https://idm.swu.edu.cn/am/UI/Login",
        hidden_fields={"goto": "synthetic-goto", "serverNonce": "synthetic-nonce"},
        state="synthetic-state-0123456789",
        code_random="synthetic-random",
        captcha_url="https://idm.swu.edu.cn/am/validate.code",
        cas_callback_url="https://of.swu.edu.cn/cas/oauth/callback/SWU_CAS2_FEDERAL",
    )
    adapter = AndroidClient(
        broker, lock_path, captcha_provider=provider, client_factory=lambda _token, _timeout: backend
    )
    adapter.demo_backend = backend

    def token(username, password, timeout):
        assert username == USER and password == SECRET
        with (
            patch.object(get_info.requests, "Session", lambda: DemoSession(flow)),
            patch.object(get_info, "discover_login_flow", lambda _session, _timeout: flow),
            patch.object(get_info, "recognize_captcha", side_effect=AssertionError("OCR must not run")),
        ):
            return get_info.authenticate_token(username, password, timeout, captcha_provider=adapter._provider)

    adapter._token_provider = token
    return adapter
