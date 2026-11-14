from unittest.mock import Mock

import pytest

from swu_checkin import email_notify, notify


@pytest.fixture
def smtp_env(monkeypatch):
    for key in list(email_notify.os.environ):
        if key.startswith("SWUDK_"):
            monkeypatch.delenv(key)
    for key, value in {
        "SWUDK_SMTP_HOST": "smtp.example.invalid",
        "SWUDK_SMTP_FROM": "sender@example.invalid",
        "SWUDK_NOTIFY_TARGET": "recipient@example.invalid",
        "SWUDK_EMAIL_BODY": "synthetic-private-body",
        "SWUDK_SMTP_USERNAME": "synthetic-user",
        "SWUDK_SMTP_PASSWORD": "synthetic-password",
    }.items():
        monkeypatch.setenv(key, value)
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.send_message.return_value = {}
    plain = Mock(return_value=client)
    encrypted = Mock(return_value=client)
    monkeypatch.setattr(email_notify.smtplib, "SMTP", plain)
    monkeypatch.setattr(email_notify.smtplib, "SMTP_SSL", encrypted)
    return client, plain, encrypted


def test_starttls_before_login_and_send(smtp_env):
    client, plain, encrypted = smtp_env
    assert email_notify.main() == 0
    plain.assert_called_once()
    encrypted.assert_not_called()
    assert [c[0] for c in client.method_calls] == ["ehlo", "starttls", "ehlo", "login", "send_message"]
    message = client.send_message.call_args.args[0]
    assert "synthetic-private-body" in message.get_content()


def test_implicit_tls(smtp_env, monkeypatch):
    client, plain, encrypted = smtp_env
    monkeypatch.setenv("SWUDK_SMTP_SECURITY", "ssl")
    assert email_notify.main() == 0
    plain.assert_not_called()
    encrypted.assert_called_once()
    client.starttls.assert_not_called()


@pytest.mark.parametrize(
    "key,value",
    [
        ("SWUDK_SMTP_SECURITY", "none"),
        ("SWUDK_SMTP_PORT", "0"),
        ("SWUDK_SMTP_TIMEOUT", "61"),
        ("SWUDK_SMTP_FROM", "a@example.invalid\r\nBcc: x"),
        ("SWUDK_NOTIFY_TARGET", "not-an-address"),
        ("SWUDK_SMTP_PASSWORD", ""),
    ],
)
def test_invalid_configuration_never_connects(smtp_env, monkeypatch, capsys, key, value):
    _, plain, encrypted = smtp_env
    monkeypatch.setenv(key, value)
    assert email_notify.main() == 2
    plain.assert_not_called()
    encrypted.assert_not_called()
    assert "synthetic-password" not in capsys.readouterr().err


def test_dry_run_never_connects(smtp_env, monkeypatch):
    _, plain, encrypted = smtp_env
    monkeypatch.setenv("SWUDK_NOTIFY_DRY_RUN", "1")
    assert email_notify.main() == 0
    plain.assert_not_called()
    encrypted.assert_not_called()


def test_failure_redacts_exception_no_retry(smtp_env, capsys):
    client, plain, _ = smtp_env
    client.send_message.side_effect = email_notify.smtplib.SMTPException("synthetic-password")
    assert email_notify.main() == 1
    assert "synthetic-password" not in capsys.readouterr().err
    assert plain.call_count == 1


def test_email_wrapper_isolated_marker_and_private_body(smtp_env, monkeypatch, tmp_path):
    monkeypatch.setenv("SWUDK_NOTIFY_CHANNEL", "email")
    monkeypatch.setenv("SWUDK_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(notify, "today_shanghai", lambda: "2026-11-14")
    (tmp_path / "notified-2026-11-14").write_text("sent")
    child = Mock(wait=Mock(return_value=0))
    launch = Mock(return_value=child)
    monkeypatch.setattr(notify.subprocess, "Popen", launch)
    assert notify.main() == 0
    args, kwargs = launch.call_args
    assert args[0][-1] == "swu_checkin.email_notify"
    assert "SWUDK_EMAIL_BODY" in kwargs["env"]
    assert (tmp_path / "notified-2026-11-14-email").exists()
    assert notify.main() == 0
    assert launch.call_count == 1


def test_starttls_failure_never_authenticates(smtp_env):
    client, _, _ = smtp_env
    client.starttls.side_effect = email_notify.smtplib.SMTPNotSupportedError("private-detail")
    assert email_notify.main() == 1
    client.login.assert_not_called()
    client.send_message.assert_not_called()


def test_refused_recipient_is_failure(smtp_env):
    client, _, _ = smtp_env
    client.send_message.return_value = {"recipient@example.invalid": (550, b"rejected")}
    assert email_notify.main() == 1


def test_email_wrapper_dry_run_writes_no_markers(smtp_env, monkeypatch, tmp_path):
    monkeypatch.setenv("SWUDK_NOTIFY_CHANNEL", "email")
    monkeypatch.setenv("SWUDK_NOTIFY_DRY_RUN", "1")
    monkeypatch.setenv("SWUDK_STATE_DIR", str(tmp_path))
    child = Mock(wait=Mock(return_value=0))
    monkeypatch.setattr(notify.subprocess, "Popen", Mock(return_value=child))
    assert notify.main() == 0
    assert list(tmp_path.iterdir()) == []
