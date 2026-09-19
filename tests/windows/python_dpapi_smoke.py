"""Real Windows DPAPI smoke for the Python TokenStore backend."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from swu_checkin.token_store import CachedToken, TokenStore, WindowsDpapiProtector


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="swu-checkin-dpapi-"))
    cache_path = root / "auth-token-cache"
    username = "synthetic-student-2026"
    token = "synthetic-bearer-token-for-dpapi-smoke"
    student_id = username
    try:
        store = TokenStore(cache_path)
        if not isinstance(store._protector, WindowsDpapiProtector):
            raise RuntimeError("TokenStore did not select the Windows DPAPI backend")

        store.save(username, token, student_id)
        raw = cache_path.read_bytes()
        if token.encode("utf-8") in raw or username.encode("utf-8") in raw:
            raise RuntimeError("DPAPI cache contains plaintext identity or token")
        if store.get(username) != CachedToken(token, student_id):
            raise RuntimeError("DPAPI token cache round-trip failed")

        store.delete(username)
        if cache_path.exists():
            raise RuntimeError("DPAPI token cache delete failed")
        print("Python DPAPI TokenStore smoke passed.")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
