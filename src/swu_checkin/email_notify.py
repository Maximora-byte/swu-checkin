"""Optional SMTP transport. Invoked in a bounded notifier child, never at import."""

from __future__ import annotations

import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import parseaddr


def _address(value: str) -> str:
    if "\r" in value or "\n" in value or parseaddr(value)[1] != value or "@" not in value:
        raise ValueError
    return value


def main() -> int:
    try:
        host = os.environ["SWUDK_SMTP_HOST"].strip()
        if not host or any(c.isspace() for c in host):
            raise ValueError
        mode = os.getenv("SWUDK_SMTP_SECURITY", "starttls")
        if mode not in {"starttls", "ssl"}:
            raise ValueError
        port = int(os.getenv("SWUDK_SMTP_PORT", "465" if mode == "ssl" else "587"))
        timeout = int(os.getenv("SWUDK_SMTP_TIMEOUT", "30"))
        if not 1 <= port <= 65535 or not 1 <= timeout <= 60:
            raise ValueError
        sender = _address(os.environ["SWUDK_SMTP_FROM"])
        recipient = _address(os.environ["SWUDK_NOTIFY_TARGET"])
        username = os.getenv("SWUDK_SMTP_USERNAME", "")
        password = os.getenv("SWUDK_SMTP_PASSWORD", "")
        if bool(username) != bool(password):
            raise ValueError
        body = os.environ["SWUDK_EMAIL_BODY"]
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = "SWU 宿舍签到通知"
        message.set_content(body)
    except (KeyError, ValueError, TypeError):
        print("email stage=config reason=invalid_config outcome=not_sent", file=sys.stderr)
        return 2

    if os.getenv("SWUDK_NOTIFY_DRY_RUN") == "1":
        print("email stage=dry_run outcome=not_sent")
        return 0
    try:
        context = ssl.create_default_context()
        client: smtplib.SMTP
        if mode == "ssl":
            client = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
        else:
            client = smtplib.SMTP(host, port, timeout=timeout)
        with client:
            client.ehlo()
            if mode == "starttls":
                client.starttls(context=context)
                client.ehlo()
            if username:
                client.login(username, password)
            refused = client.send_message(message)
            if refused:
                raise smtplib.SMTPException
    except (OSError, smtplib.SMTPException, ValueError):
        # A connection error may happen after acceptance. Never print exceptions
        # or retry automatically: recipient, body and credentials are private.
        print("email stage=send reason=smtp_error outcome=unknown_after_send", file=sys.stderr)
        return 1
    print("email stage=send outcome=accepted_by_smtp_delivery_unverified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
