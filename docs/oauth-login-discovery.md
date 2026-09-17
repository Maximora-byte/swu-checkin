# Follow-up: dynamically discover the SWU OAuth login flow

## Problem

The current login implementation hard-codes `OAUTH_GOTO_BASE64`, `client_id`, `redirect_uri`, and the URL assembled by `build_idm_login_url()`. A legitimate SWU authentication change can therefore break login or leave stale redirect metadata in the client.

Repository Issues are currently disabled, so this document is the issue-ready tracking record. Create a GitHub issue from it if Issues are enabled later.

## Goal

Start from a trusted SWU HTTPS login entry point and derive the current redirect targets and form values from server responses. Parse redirects and hidden form inputs supplied by SWU instead of guessing or synthesizing replacement URLs.

## Security requirements

- Require HTTPS and normal certificate verification for every discovery request.
- Allow redirects only to explicitly trusted SWU hosts; reject scheme downgrades, unrelated hosts, missing state, and malformed forms.
- Treat missing or ambiguous discovery data as a login failure. Do not fall back to guessed URLs or stale constants.
- Never log credentials, captcha values, OAuth state, tickets, tokens, callback URLs, or hidden form values.
- Preserve request timeouts and bounded retry behavior.

## Acceptance criteria

- `OAUTH_GOTO_BASE64` and the manually assembled `client_id`/`redirect_uri` chain are no longer runtime sources of truth.
- Unit tests cover valid discovery, unexpected hosts, HTTP failures, missing hidden inputs, malformed redirects, and sensitive-log filtering.
- A read-only login probe succeeds against the live SWU flow before deployment.
- Existing check-in, leave detection, status-code, and notifier behavior remains unchanged.

## Out of scope for the current PR

- No OAuth flow refactor.
- No guessed endpoint migration.
- No bypass, anti-detection, or location behavior changes.
