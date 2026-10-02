# SWU OAuth login discovery

This document follows the current 2.1.0 pre-release candidate source. No new tag or Release has been created; the latest public release remains v2.0.0. The release preflight uses synthetic authentication and does not establish live school-account compatibility. See [candidate notes](releases/v2.1.0.md) and [release readiness](releases/release-readiness.md) for package provenance, signatures and pending acceptance.

> This document describes the authentication implementation independently maintained in [Maximora-byte/swu-checkin](https://github.com/Maximora-byte/swu-checkin). It is not an SWU protocol specification and is not maintained by the original upstream project. Report regressions to the [current repository issue tracker](https://github.com/Maximora-byte/swu-checkin/issues) with structural, redacted evidence only.

## Why this was changed

The former implementation treated one large `OAUTH_GOTO_BASE64` value and a hand-built `build_idm_login_url()` as the runtime source of truth. Decoding that value showed a complete, stale-prone chain containing an OAuth client ID, nested redirect URIs, one fixed state value, a legacy HTTP IDM URL and CAS-specific parameters. A change at any SWU hop could therefore invalidate the whole client.

The current implementation starts from one fixed SWU application entry and discovers the current chain from trusted server responses. It does not fall back to the removed Base64 constant or synthesize a guessed replacement when discovery fails.

## Runtime source of truth

`src/swu_checkin/oauth_flow.py` performs these bounded steps:

```text
trusted SWU application entry
        ↓  validated Location (manual, no automatic redirects)
UAAAP OAuth authorize URL + current state + CAS callback
        ↓  validated Location
UAAAP CAS login URL + originalRequestUrl
        ↓  trusted HTTPS page advertises federalEnable=true
minimal IDM authorize bootstrap
        ↓  exact IDM Location, upgraded to HTTPS if SWU emits its legacy HTTP form
server-provided IDM login form
        ↓  form action + hidden inputs + codeRandom + captcha URL
credentials + captcha POST
        ↓  optional validated student-identity selection
        ↓  bounded, individually validated SWU redirects
strict UAAAP ticket callback (including the observed 412 behavior)
        ↓
server-discovered CAS callback + current state
        ↓  bounded, individually validated SWU redirects
strict OF landing/service-return ticket (including the observed 404 behavior)
        ↓
token exchange
```

The current OAuth `state`, UAAAP `client_id`, UAAAP callback, CAS `service`, `originalRequestUrl`, IDM login Location, form action, hidden fields, `goto`, `codeRandom` and captcha URL all come from the current SWU response chain.

This discovery is shared by the CLI, Windows/macOS desktop and Android manual client. Android supplies a bounded, image-only manual captcha callback to the same authentication implementation; it does not maintain a second OAuth chain or relax any URL, state, ticket or identity check. The default CLI/desktop path still uses OCR when no callback is supplied.

The CAS page currently advertises federation through a small `_goLogin` script which appends `federalEnable=true`. The client requires that exact instruction once; a missing or ambiguous instruction is an error.

If IDM offers the supported student-identity selection page, `identity.py` prefers a postgraduate identity (研究生/硕士/博士), otherwise the first offered identity. The selection uses the already validated IDM login destination and discovered `goto`; it does not trust a new arbitrary form destination. Duplicate/invalid input names or a missing unique Login form fail closed. Program-owned `IDToken1`, `IDToken2`, `IDToken3` and `goto` cannot be overwritten by server-provided hidden inputs. This is a compatibility policy for the observed page, not a claim to support arbitrary future identity screens.

## Security boundary

- Actual requests are HTTPS-only and certificate verification remains enabled.
- Trusted hosts are exactly:
  - `of.swu.edu.cn`
  - `uaaap.swu.edu.cn`
  - `idm.swu.edu.cn`
- URLs with userinfo, non-default ports, fragments outside the one exact SWU service-return shape, malformed escaping, duplicate parameters, unknown hosts or unexpected paths are rejected.
- Redirects are requested with `allow_redirects=False`, resolved one hop at a time and limited to a bounded count.
- The client never requests an HTTP URL. IDM currently emits legacy `http://idm.swu.edu.cn/...` Locations and a legacy HTTP URL inside its Base64 `goto`. Only exact IDM host/path/default-port values are accepted; request targets are upgraded to HTTPS. The hidden `goto` is validated against the discovered authorize parameters and posted back as opaque server data, never fetched by the client.
- Missing `state`, `Location`, login form, required hidden input, captcha URL or ticket fails closed. There is no guessed-URL fallback.
- HTTP 412 is accepted only for the exact HTTPS `uaaap.swu.edu.cn/cas/oauth2.0/callbackAuthorize` callback with exactly one non-empty `ticket` parameter and no other query parameters. A discovered URL does not expand this exception to an arbitrary callback path or host.
- HTTP 404 is accepted only for the exact HTTPS OF `/<ticket-landing>` path shape. A recognized service-return query/fragment is not a blanket exception for 404. Other HTTP failures keep their normal error behavior.
- Business API calls and the token-exchange request also use `allow_redirects=False`; any 3xx is rejected rather than forwarding a token or form to another target.
- Credentials, captcha text, OAuth state/code, tickets, tokens, callback URLs and hidden values are never printed. Debug output contains only fixed stage names, status codes, allowlisted hosts/paths and parameter names.

## Remaining fixed values

These values cannot currently be derived before starting the flow and remain deliberately small:

1. `CAS_LOGIN_URL` / `CAS_SERVICE_URL`
   - Identify the SWU application and its server-side CAS return endpoint.
   - They are the trusted bootstrap entry, not a precomputed OAuth chain.
2. `IDM_AUTHORIZE_URL`
   - IDM does not advertise this endpoint from the UAAAP CAS page; it is the minimum trusted IDM bootstrap endpoint.
3. `IDM_OAUTH_CLIENT_ID`
   - This is the registered IDM client for the UAAAP integration. UAAAP redirects expose their own different client ID, not this registration value.
4. `IDM_OAUTH_SCOPE`
   - This is the registered IDM attribute contract and is not published separately by the SWU CAS redirects.
5. `TOKEN_EXCHANGE_URL`
   - This is an application API endpoint after authentication, not OAuth redirect metadata.

`OAUTH_GOTO_BASE64`, the fixed state and the hand-built nested login URL no longer exist. The server-provided hidden `goto` remains because IDM requires it, but it is validated against the discovered flow before use.

## Troubleshooting a future SWU change

1. Run `swu-checkin doctor` for fresh authentication without token-cache reads/writes. Then use `swu-checkin probe` with the same runtime user and cache-path environment as the formal CLI to compare its cache-backed path. The shipped `swu-checkin-probe.service` does not set the formal service’s `SWUDK_STATUS_FILE`; it checks connectivity and credentials, not necessarily the formal service’s cache. Neither submits a check-in; never use a real submission to diagnose login.
2. Keep `SWUDK_DEBUG_CREDENTIALS=1` limited to safe stage diagnostics. It still does not reveal secret values.
3. Identify the first available safe failure boundary: `stage=auth` or `stage=token_validation`, the fixed authentication classification, and any already emitted status/allowlisted host/path metadata. Not every rejected hop is exposed individually; do not add raw exception or response logging to obtain it.
4. Capture only structural metadata: status code, host, path, parameter names, form/input names. Do not capture values or complete URLs.
5. Update the narrow stage validator and add offline valid/invalid fixtures before changing production behavior.
6. Never add a fallback to the old Base64 value, an unvalidated redirect or a guessed callback.

## Authentication, cache and retry boundaries

`get_info.py` exchanges the final ticket for a token; `service.py` then validates the returned student identity against the requested username before using or caching it. A cache hit is revalidated against the identity endpoint and does not recheck the current password. Invalid token rejection or identity mismatch at this initial boundary can delete/replace a cache entry in both formal and probe modes.

After initial validation, formal execution permits one fresh-auth recovery only when a cache-backed session is explicitly rejected during the pre-submit business reads. HTTP 401/403 or top-level business `code` 401/403 is the recognized signal; schema, JSON, timeout and unknown business responses are not. Probe does not perform that later recovery. `doctor` and `setup` use fresh authentication and do not read or write TokenStore.

Authentication has bounded captcha acquisition/OCR retries and can refetch/repost a captcha when the server explicitly rejects it. With an injected manual provider, only the current session's image bytes reach the callback; cancellation, invalid answers or provider failure end authentication without falling back to OCR. The synchronous provider must run off the UI thread and bound its own wait; the HTTP timeout does not interrupt user input. Complete authentication retries are owned by the service's outer policy: authentication network classifications can retry, while rejected credentials, final captcha failure and structural authentication failures stop. These authentication POSTs are separate from the at-most-one check-in submission POST per formal business call. No submit/readback error triggers reauthentication followed by a second check-in submission in that call. Android explicitly limits each confirmed manual operation to one outer attempt.

See [CLI reference](cli-reference.md) for outer attempts, result codes and output exceptions, and [security model](security.md) for storage, lock and readback boundaries.

## Verification expectations

- Offline tests cover the valid discovery chain, form/hidden parsing, optional identity selection, state and ticket callbacks.
- Attack tests cover HTTP downgrade, untrusted/lookalike hosts, userinfo, abnormal ports, missing Location/state/form/hidden inputs, malformed URLs/forms, duplicate critical parameters and invalid 412/404 responses.
- Log tests assert that credentials and all OAuth/CAS secret values are absent.
- A protected read-only live probe should succeed before deployment. It must not write the formal check-in status file or call the submission endpoint. It may update the token cache at the initial authentication boundary; it is not a zero-local-write test. Offline tests and build smoke checks do not establish that the current school endpoints are available.
- Android instrumentation uses synthetic school responses and validates the real shared parser/guard path; it does not establish live SWU authentication. Physical-phone HTTPS checks use a public test site, not school credentials. Current distribution evidence and remaining live/platform checks are recorded in [release readiness](releases/release-readiness.md).
