# SWU OAuth login discovery

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

The CAS page currently advertises federation through a small `_goLogin` script which appends `federalEnable=true`. The client requires that exact instruction once; a missing or ambiguous instruction is an error.

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
- HTTP 412 is accepted only for the exact HTTPS UAAAP callback with one non-empty `ticket`.
- HTTP 404 is accepted only for the exact HTTPS OF ticket landing shape. Other HTTP failures keep their normal error behavior.
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
   - This is the registered IDM attribute contract and is not published separately by the upstream CAS redirects.
5. `TOKEN_EXCHANGE_URL`
   - This is an application API endpoint after authentication, not OAuth redirect metadata.

`OAUTH_GOTO_BASE64`, the fixed state and the hand-built nested login URL no longer exist. The server-provided hidden `goto` remains because IDM requires it, but it is validated against the discovered flow before use.

## Troubleshooting a future SWU change

1. Run the read-only probe (`swu-checkin-probe.service`); never use a real submission to diagnose login.
2. Keep `SWUDK_DEBUG_CREDENTIALS=1` limited to safe stage diagnostics. It still does not reveal secret values.
3. Identify the first rejected stage from its status/allowlisted host/path and parameter names.
4. Capture only structural metadata: status code, host, path, parameter names, form/input names. Do not capture values or complete URLs.
5. Update the narrow stage validator and add offline valid/invalid fixtures before changing production behavior.
6. Never add a fallback to the old Base64 value, an unvalidated redirect or a guessed callback.

## Verification expectations

- Offline tests cover the valid discovery chain, form/hidden parsing, state and ticket callbacks.
- Attack tests cover HTTP downgrade, untrusted/lookalike hosts, userinfo, abnormal ports, missing Location/state/form/hidden inputs, malformed URLs/forms, duplicate critical parameters and invalid 412/404 responses.
- Log tests assert that credentials and all OAuth/CAS secret values are absent.
- A protected read-only live probe should succeed before deployment. It must not write the check-in status file or call the submission endpoint.
