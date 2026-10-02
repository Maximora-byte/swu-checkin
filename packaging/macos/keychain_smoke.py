"""Disposable GitHub-hosted macOS runner only; no school account or network.

Creates and removes one uniquely named synthetic Keychain item. Does not read
the app's credential item, unlock a Keychain, or change any item ACL.
"""

from __future__ import annotations

import ctypes
import os
import secrets
import sys
from uuid import uuid4

from swu_checkin.macos_keychain import (
    KeychainError,
    MacOSKeychain,
    _check_status,
    _SecurityFrameworkBinding,
)


class _SmokeBinding:
    def __init__(self, native: _SecurityFrameworkBinding) -> None:
        self.native = native
        self.service = f"io.github.maximora-byte.swu-checkin.ci.{uuid4().hex}"
        self.account = "synthetic-smoke-only"

    def add(self, service: str, account: str, data: bytes) -> int:
        return self.native.add(self.service, self.account, data)

    def update(self, service: str, account: str, data: bytes) -> int:
        return self.native.update(self.service, self.account, data)

    def copy(self, service: str, account: str) -> tuple[int, bytes | None]:
        return self.native.copy(self.service, self.account)

    def delete(self, service: str, account: str) -> int:
        return self.native.delete(self.service, self.account)


def run_smoke() -> None:
    native = _SecurityFrameworkBinding()
    # File-based Keychain may otherwise open an authorization dialog that hangs
    # a headless runner. This flag is process-local, never a Keychain setting;
    # restore its previous value even if the test or cleanup fails.
    get_ui = native._security.SecKeychainGetUserInteractionAllowed
    get_ui.argtypes = [ctypes.POINTER(ctypes.c_ubyte)]
    get_ui.restype = ctypes.c_int32
    set_ui = native._security.SecKeychainSetUserInteractionAllowed
    set_ui.argtypes = [ctypes.c_ubyte]
    set_ui.restype = ctypes.c_int32
    previous = ctypes.c_ubyte()
    _check_status(get_ui(ctypes.byref(previous)))
    _check_status(set_ui(False))
    try:
        store = MacOSKeychain(binding=_SmokeBinding(native))
        try:
            if store.load() is not None:
                raise RuntimeError
            first = ("synthetic-user-1", secrets.token_urlsafe(24))
            store.save(*first)
            if store.load() != first:
                raise RuntimeError
            second = ("synthetic-user-2", secrets.token_urlsafe(24))
            store.save(*second)
            if store.load() != second:
                raise RuntimeError
            store.delete()
            if store.load() is not None:
                raise RuntimeError
            store.delete()
        finally:
            store.delete()
    finally:
        _check_status(set_ui(previous.value))


def main() -> int:
    if sys.platform != "darwin" or os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("RUNNER_OS") != "macOS":
        print("Keychain smoke requires a disposable macOS GitHub Actions runner.")
        return 2
    try:
        run_smoke()
    except KeychainError as exc:
        print(f"Keychain smoke failed: {exc.code.value}")
        return 1
    except Exception:
        print("Keychain smoke failed: operation_failed")
        return 1
    print("Keychain synthetic roundtrip, update, delete, and missing-item checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
