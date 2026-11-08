# SWU Dormitory Check-in (MatchAll-maintained edition)

[简体中文](README.md) | English

[![CI](https://github.com/Maximora-byte/swu-checkin/actions/workflows/ci.yml/badge.svg)](https://github.com/Maximora-byte/swu-checkin/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Maximora-byte/swu-checkin)](https://github.com/Maximora-byte/swu-checkin/releases/latest)
[![License](https://img.shields.io/github/license/Maximora-byte/swu-checkin)](LICENSE)

A DingTalk dormitory check-in tool for Southwest University, offering a Python CLI, Windows desktop app / macOS desktop preview, manual Android client, Windows scheduled scripts, GitHub Actions, and restricted systemd timer deployment. All entry points share the authentication and check-in core.

> [!IMPORTANT]
> This is an unofficial community project independently maintained by [MatchAll](https://github.com/Maximora-byte), derived from [Sorynthia/swu-checkin](https://github.com/Sorynthia/swu-checkin). Original attribution and the MIT license are retained, but this repository independently manages its roadmap, releases, and support. It does not represent Southwest University, DingTalk, or the original upstream author.

## Why maintain this edition?

- **Reliable outcomes**: reads the school API after submission; HTTP 200 alone does not mean check-in success.
- **Secure authentication**: dynamically discovers and strictly validates the SWU OAuth/CAS login chain, failing closed on unexpected hosts, protocols, or parameters.
- **Conservative execution**: stops submitting if leave status, dormitory, task, or response structure cannot be safely confirmed; never guesses data.
- **Read-only diagnostics**: `setup`, `doctor`, `status`, and `probe` do not submit check-ins. `probe` does not write run state or automatically recover a cache invalidated during the business stage.
- **Redacted logs**: submission exceptions log only fixed categories. Unknown school business codes, response bodies, and messages are not logged.
- **Concurrency protection**: production CLI and desktop check-ins share a nonblocking cross-process lock. Scheduled and manual runs in the same lock domain cannot submit concurrently. The lock does not coordinate different machines or lock paths.
- **Cross-platform deployment**: GitHub Actions, Windows Task Scheduler, and systemd timers.
- **Traceable delivery**: Python 3.13, `uv.lock`, Linux/Windows CI, wheel/sdist installation verification, and dependency auditing.

## Versions and downloads

The current release series is **v2.1.1**, developed and published by **MatchAll**. Downloads and checksums are on the [v2.1.1 release page](https://github.com/Maximora-byte/swu-checkin/releases/tag/v2.1.1). The Windows x64 installer and portable ZIP bundle Python, OCR, and all runtime resources. Android **1.0.0 / versionCode=5** installs directly without a development environment. Unnotarized preview attachments remain available for both macOS 15 architectures. The older v2.1.0 pre-release and historical assets remain unchanged.

Installation: download `SWUCheckin-1.0.0-android.apk` for Android; download `SWUCheckin-2.1.1-win-x64-Setup.exe` for Windows, or fully extract `SWUCheckin-2.1.1-win-x64-Portable.zip`. On first launch, enter your own campus account and perform a read-only query first. No check-in occurs and no background task is enabled by default. See [v2.1.1 notes](docs/releases/v2.1.1.md) for version scope, upgrades, and verification.

## Windows desktop app

Desktop functionality was merged into `main` through [PR #33](https://github.com/Maximora-byte/swu-checkin/pull/33): a Chinese-language window, current-user DPAPI storage, read-only checks, confirmed manual check-in, and optional scheduled tasks disabled by default. The Windows x64 package bundles Python and required resources; users need not install Python, uv, or OCR models separately.

The Windows app is not Authenticode-signed, so the system may display download or installation warnings. Native Windows workflows perform frozen-build self-tests, installation/GUI/uninstallation checks, and portable-package verification. Coverage on clean physical Windows 10/11 machines remains limited; see the release report for evidence. See the [desktop guide](docs/windows-desktop.md) for usage.

This tool uses dormitory coordinates recorded by the school; it does not measure actual GPS. A technically successful submission does not prove physical presence. Only perform a real check-in when you are actually in your dormitory and comply with school rules. Automatic mode needs separate authorization and must be disabled in advance when these conditions are not met.

### Windows portable ZIP

Download the current `*-win-x64-Portable.zip`, extract everything, and run `SWUCheckin/SWUCheckin.exe`. The ZIP includes Chinese instructions, provenance, and a checksum manifest. Python, uv, and administrator privileges are not required. Account data stays in the current user's directory; portable distribution does not mean accounts migrate between computers. Close the window before upgrading and keep the directory referenced by scheduled tasks unchanged. See the [portable guide](docs/windows-portable.md).

## macOS desktop preview

The macOS 15 manual desktop preview does not access the network or read accounts at startup. Users can explicitly save/read/clear accounts with the system Keychain; tokens remain in memory. Separate Apple Silicon and Intel `.app` builds have no background tasks. These previews are ad-hoc signed, not Developer ID-signed or notarized. Availability depends on successful CI artifacts for each architecture; clean-user acceptance on a real Mac has not been completed. See the [macOS guide and build boundaries](docs/macos-desktop.md).

## Choose how to run

Android **1.0.0** supports campus-account login, manually entered CAPTCHAs, optional encrypted storage, read-only queries and diagnostics, and a single manual check-in after explicit confirmation. The developer is shown as MatchAll; it uses an original icon and light/dark card UI. Android 7.0 or later is required; only arm64-v8a / x86_64 are supported. The production package uses a persistent signing identity and the existing package name, allowing direct upgrades from 0.1.2-preview. See the [Android guide](docs/android-client.md) for installation and acceptance scope.

| Scenario | Recommended method | Notes |
| --- | --- | --- |
| Check account and API availability first | [Local CLI](docs/quickstart.md) | Fastest; use `setup` / `probe` before deciding on real execution |
| Always-online Linux host | [systemd deployment](DEPLOYMENT.md) | Stable timing, privilege isolation, two timer runs, optional Telegram summaries |
| Windows Chinese-language window | [Desktop app](docs/windows-desktop.md) | Standalone EXE; no network or tasks by default; unsigned; download Releases assets |
| macOS Chinese-language window | [Manual macOS preview](docs/macos-desktop.md) | Native architecture-specific .app; optional Keychain, in-memory tokens; no background tasks; unnotarized |
| Manual use on Android | [Manual Android client](docs/android-client.md) | Manual CAPTCHA, optional Keystore-encrypted storage, query before confirmed submission; no background tasks |
| Existing Windows Python-script deployment | [Windows script guide](docs/windows.md) | Requires uv/Python; successful installation diagnostics enable real scheduled tasks |
| No server of your own | [GitHub Actions](GITHUB_ACTIONS.md) | Simple configuration, but cron may queue and cannot guarantee exact timing |

## Local verification of the current source

Requirements: Git, [uv](https://docs.astral.sh/uv/getting-started/installation/), and network access to the school's authentication/business APIs.

```bash
git clone https://github.com/Maximora-byte/swu-checkin.git
cd swu-checkin
uv sync --locked --no-dev --python 3.13
```

Start with read-only verification:

```bash
uv run --locked --no-dev swu-checkin setup
uv run --locked --no-dev swu-checkin probe
```

Only after verifying the results, perform a real check-in:

```bash
uv run --locked --no-dev swu-checkin run
```

`run` / `probe` / `doctor` prompt interactively when environment credentials are missing; `setup` always requests interactive input. Password input is hidden, and `setup` does not save credentials. Unattended execution must use GitHub Secrets, Windows DPAPI, or permission-restricted systemd environment files.

> [!TIP]
> The example checks out the current default branch. To use this release, select `v2.1.1` and use that tag's code, documentation, and `uv.lock` together; downloads are in [Releases](https://github.com/Maximora-byte/swu-checkin/releases). The older [v1.1.5](https://github.com/Maximora-byte/swu-checkin/releases/tag/v1.1.5) contains only wheel/sdist packages, without desktop features. Verify the commit, `BUILD-INFO.json`, signatures, and checksums for desktop and Android packages.

## Common commands

```bash
swu-checkin setup          # Interactive read-only configuration check; does not save passwords
swu-checkin doctor         # 7 read-only diagnostics; does not read/write token cache
swu-checkin probe          # Log in and inspect business state; no submission
swu-checkin run            # Real check-in; transient-failure retries and execution lock
swu-checkin status         # Read local state only; no network requests
swu-checkin run --json     # Emit schema v1 JSON when business execution completes
swu-checkin probe --json   # Schema v1 JSON for probe; no check-in submission
```

See the [CLI and status reference](docs/cli-reference.md) for all arguments, environment variables, JSON fields, and exit semantics.

## Status codes

| Code | Meaning | Normal terminal outcome for real check-in? |
| ---: | --- | :---: |
| 0 | No check-in record today | No |
| 1 | Check-in successful | Yes |
| 2 | Already checked in today | Yes |
| 3 | Account or password authentication failed | No |
| 4 | Network error or abnormal server data | No |
| 5 | On leave; check-in skipped | Yes |
| 6 | Probe found a pending check-in task; not submitted | Normal for probe only |

Status `4` is an aggregate fail-closed status: when network, JSON, schema, or school-service problems cannot be safely distinguished, execution does not guess or continue submitting. See [troubleshooting](docs/troubleshooting.md).

Common diagnostic categories include `请求超时` (request timeout), `连接异常` (connection error), `HTTP 503`, `业务码已返回` (business code returned), and `响应结构异常` (unexpected response structure). `业务码已返回` only means the classified response contains a `code/status` field. The original value is intentionally not logged and cannot identify a specific account or school-side cause. JSON mode sends diagnostics to stderr; exits before business execution, such as a busy lock, may produce no JSON. See the CLI reference for the complete contract.

## Security boundaries

- Passwords are provided through interactive input or controlled environment variables, GitHub Secrets, Windows DPAPI, macOS Keychain, AndroidKeyStore-encrypted storage, or root-only environment files. Legacy Windows scripts store accounts in local configuration JSON. Never put credentials in repositories, Issues, screenshots, or logs.
- Logs do not expose account values, passwords, CAPTCHAs, tokens, tickets, OAuth state/code, full callback URLs, dormitory addresses, or coordinates.
- The project uses dormitory coordinates returned by school APIs and retains existing submission fields. It does not measure actual GPS or prove presence; technical submission success is not proof of physical location. No new anti-detection or authentication-bypass features are provided.
- `probe`, `doctor`, `setup`, and `status` do not call the check-in submission endpoint. CLI `run`, the backward-compatible no-subcommand entry point, confirmed desktop manual check-ins, and authorized automatic check-ins can enter the real workflow. `probe` reuses valid caches; when a cache is explicitly invalidated during identity validation, it may perform fresh authentication and replace the local cache.
- If a check-in submission POST has an ambiguous outcome, such as timeout, connection loss, or 5xx, it is not followed by a second submission POST after logging in again.
- A valid cache must first pass account identity validation. The real workflow clears it and performs fresh authentication once only for explicit 401/403 responses during pre-submission business reads. Arbitrary network errors are not treated as expired sessions.

See the [security model](docs/security.md) and [OAuth login discovery](docs/oauth-login-discovery.md).

## Documentation

- [Quick start](docs/quickstart.md): installation, first read-only checks, real execution, and upgrades
- [CLI and status reference](docs/cli-reference.md): commands, environment variables, JSON schema v1, and exit codes
- [Windows desktop](docs/windows-desktop.md): EXE, DPAPI, explicit authorization, builds, and acceptance
- [Windows portable](docs/windows-portable.md): ZIP execution, data boundaries, moving, and upgrading
- [macOS desktop preview](docs/macos-desktop.md): manual UI, system Keychain, dual architectures, and notarization limits
- [Manual Android client](docs/android-client.md): manual CAPTCHA, encrypted accounts, query before confirmed submission
- [Android environment acceptance](docs/android-feasibility.md): build, emulator, physical device, and historical evidence
- [Windows script guide](docs/windows.md): legacy Python deployment, scheduled tasks, and migration
- [Server deployment](DEPLOYMENT.md): systemd, permissions, timers, logs, upgrades, and rollback
- [GitHub Actions guide](GITHUB_ACTIONS.md): Secrets, multiple accounts, notifications, and queueing delays
- [Troubleshooting](docs/troubleshooting.md): statuses 3/4, cached sessions, locks, Actions, and safe reporting
- [Security model](docs/security.md): authentication, TokenStore, submission safety, logs, and support boundaries
- [v2.0.0 release notes](docs/releases/v2.0.0.md): published assets, changes from v1.1.5, and limitations
- [v2.1.0 pre-release notes](docs/releases/v2.1.0.md): changes, delivery assets, and platform limits
- [v2.1.1 stable release notes](docs/releases/v2.1.1.md): current downloads, Android 1.0.0, upgrades, and support scope
- [Historical v2.1.0 release assessment](docs/releases/release-readiness.md): candidate origins, evidence, and tasks at that time
- [Development, CI, and releases](docs/development.md): module ownership, offline verification, and release boundaries
- [Contributing](CONTRIBUTING.md) / [Maintenance and attribution](MAINTAINERS.md)

Linked guides may still be in Chinese. This README translation does not change the language of the applications or their output.

## Development and quality gates

```bash
uv sync --locked --all-groups --python 3.13
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src/swu_checkin
uv lock --check
```

For ordinary changes, `quality` aggregates Linux, Windows, and Python-package gates, including PowerShell/DPAPI, cross-process locks, Actions syntax, systemd units, Unix state permissions, wheel/sdist installation, and locked production dependency auditing. Only trusted ImgBot in-place edits to designated preview PNGs use a separate image gate; Markdown changes still run all three groups. Native builds support manual execution. For PRs, Release preflight path rules select builds centrally and invoke them at exactly the same SHA. PR/manual preflight generates review material only and does not publish. See [development, CI, and releases](docs/development.md).

## Support, attribution, and license

- Authoritative repository: [Maximora-byte/swu-checkin](https://github.com/Maximora-byte/swu-checkin)
- Releases: [GitHub Releases](https://github.com/Maximora-byte/swu-checkin/releases)
- Issue reports: [GitHub Issues](https://github.com/Maximora-byte/swu-checkin/issues)
- Original project: [Sorynthia/swu-checkin](https://github.com/Sorynthia/swu-checkin)

Read [troubleshooting](docs/troubleshooting.md) before reporting an issue and include only redacted structural information. This fork uses the MIT License; copies and modifications must retain the license text and original authors' attribution.
