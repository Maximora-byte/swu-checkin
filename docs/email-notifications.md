# Optional email notifications

The `swu-checkin-notify` entry point can use SMTP instead of the default OpenClaw/Telegram transport. Email is **opt-in** and does not require an OpenClaw CLI installation. It sends the same non-sensitive daily summary, not credentials or a complete response dump.

Configure the environment using `deploy/notify.env.example`:

- `SWUDK_NOTIFY_CHANNEL=email`
- `SWUDK_NOTIFY_TARGET`: one recipient email address (no display name or list).
- `SWUDK_SMTP_HOST`, `SWUDK_SMTP_FROM`: required.
- `SWUDK_SMTP_SECURITY=starttls` (default, port 587) or `ssl` (port 465).
- `SWUDK_SMTP_USERNAME` and `SWUDK_SMTP_PASSWORD`: optional pair. Obtain an SMTP-specific credential from your provider and inject it through your secret manager or a root-owned mode-0600 environment file. Do not commit it or paste it in issues/logs.
- `SWUDK_SMTP_TIMEOUT`: per-network-operation limit, integer 1–60 seconds (default 30).
- `SWUDK_NOTIFY_SEND_TIMEOUT`: total child-process limit, integer 30–180 seconds (default 120). Keep the service outer deadline above this plus cleanup/startup margin; repository unit default is 210 seconds.

Only authenticated certificate-verified TLS is supported; STARTTLS failure stops before authentication. There is no plaintext downgrade or automatic resend. SMTP server acceptance is **not** inbox delivery proof. All SMTP exceptions are redacted. The parent enforces the total child deadline and process-group cleanup.

Set `SWUDK_NOTIFY_DRY_RUN=1` for configuration validation only: email dry-run opens **no SMTP connection**, sends nothing, and neither reads nor writes daily notification guards. Thus it cannot prove SMTP credentials, network connectivity or delivery. A real test requires an explicitly approved recipient and send action.

Email uses `notify-attempt-DATE-email` and `notified-DATE-email`, separate from Telegram's existing markers. Select one transport per invocation. To operate both, configure separate invocations with the same state directory and their own channel/target environments; do not run competing invocations for the same transport. After an uncertain real send, preserve the attempt marker and reconcile delivery before any manual retry.

This change does not enable email on an existing deployment, edit installed units, change check-in schedules, or send a verification email. APK license inventory hashes were refreshed from the hash-verified PyPI Soup Sieve 4.1 wheel; an actual rebuilt Android APK still requires artifact verification.
