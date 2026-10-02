"""Android manual operations: image-only captcha, memory tokens, explicit submit."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import cast

from swu_checkin.auth import AuthError
from swu_checkin.client import SwuClient
from swu_checkin.get_info import authenticate_token
from swu_checkin.runtime_lock import RuntimeLock, RuntimeLockBusy
from swu_checkin.service import CheckinService
from swu_checkin.token_store import CachedToken


class MemoryTokens:
    """Never use the desktop plaintext token cache on Android."""

    def __init__(self) -> None:
        self.values: dict[str, CachedToken] = {}

    def get(self, username: str) -> CachedToken | None:
        return self.values.get(username)

    def save(self, username: str, token: str, student_id: str) -> None:
        self.values[username] = CachedToken(token=token, student_id=student_id)

    def delete(self, username: str) -> None:
        self.values.pop(username, None)


class OperationCancelled(Exception):
    """A fixed internal signal; never carries input or server response data."""


class AndroidClient:
    def __init__(
        self,
        broker: object,
        lock_path: str,
        *,
        captcha_provider: Callable[[bytes], str | None] | None = None,
        token_provider: Callable[[str, str, int], str] | None = None,
        client_factory: Callable[[str, int], SwuClient] | None = None,
    ) -> None:
        self.broker = broker
        self.lock_path = Path(lock_path)
        if not self.lock_path.is_absolute():
            raise ValueError("absolute lock path required")
        self.tokens = MemoryTokens()
        self._provider = captcha_provider or self._manual_captcha
        self._token_provider = token_provider or self._authenticate
        self._client_factory = client_factory or (lambda token, timeout: SwuClient(token, timeout))
        self._salt = os.urandom(32)
        self._fingerprint: bytes | None = None

    def _cancelled(self) -> bool:
        return bool(self.broker.isCancelled())

    def _manual_captcha(self, image: bytes) -> str | None:
        # Lazy import keeps host tests independent of Chaquopy. Explicit signed
        # byte conversion preserves the original image, including bytes > 127.
        from java import jarray, jbyte

        if self._cancelled():
            return None
        answer = self.broker.request(jarray(jbyte)(image))
        return None if answer is None else str(answer)

    def _authenticate(self, username: str, password: str, timeout: int) -> str:
        if self._cancelled():
            raise OperationCancelled
        return authenticate_token(username, password, timeout, captcha_provider=self._provider)

    def clear(self) -> None:
        self.tokens.values.clear()
        self._fingerprint = None

    def run(self, operation: str, username: str, password: str, confirmed: bool = False) -> str:
        if operation not in {"probe", "diagnose", "checkin"}:
            return self._error("invalid_operation")
        if not username or not password or len(username) > 128 or len(password) > 1024:
            return self._error("invalid_credentials")
        if operation == "checkin" and confirmed is not True:
            return self._error("confirmation_required")
        if self._cancelled():
            return self._error("cancelled")
        try:
            with RuntimeLock(self.lock_path):
                fingerprint = hashlib.sha256(self._salt + json.dumps([username, password]).encode()).digest()
                if fingerprint != self._fingerprint:
                    self.clear()
                    self._fingerprint = fingerprint
                allowed_submit = operation == "checkin" and confirmed

                def guarded_client(token: str, timeout: int) -> SwuClient:
                    client = self._client_factory(token, timeout)
                    owner = self

                    class GuardedClient:
                        def __getattr__(self, name: str) -> object:
                            return getattr(client, name)

                        def submit_checkin_form(self, *, form_id: str | int, payload: dict[str, object]) -> object:
                            if not allowed_submit or owner._cancelled():
                                raise OperationCancelled
                            return client.submit_checkin_form(form_id=form_id, payload=payload)

                    return cast(SwuClient, GuardedClient())

                service = CheckinService(
                    token_provider=self._token_provider,
                    client_factory=guarded_client,
                    token_store=self.tokens,
                    diagnostic=lambda _message: None,
                )
                if operation == "diagnose":
                    report = service.diagnose(username, password, read_token_cache=True, write_token_cache=True)
                    result = json.dumps({"schema_version": 1, "mode": "diagnose", "checks": asdict(report)})
                elif operation == "probe":
                    result = service.run_probe(username, password).to_json()
                else:
                    # One user confirmation authorizes one attempt. The shared
                    # core re-reads task/leave/identity and confirms server state.
                    result = service.run_checkin(username, password, max_attempts=1).to_json()
                return result if not self._cancelled() else self._error("cancelled")
        except RuntimeLockBusy:
            return self._error("busy")
        except OperationCancelled:
            return self._error("cancelled")
        except AuthError as error:
            return self._error(error.reason.value)
        except Exception:
            # Python exception text/tracebacks can contain credentials or URLs.
            return self._error("operation_failed")

    @staticmethod
    def _error(code: str) -> str:
        return json.dumps({"schema_version": 1, "error": code})
