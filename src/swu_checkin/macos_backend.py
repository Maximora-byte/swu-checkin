"""macOS manual desktop adapter; Keychain is accessed only by explicit buttons."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Protocol

from .desktop_errors import DesktopError, DesktopErrorCode
from .desktop_operations import DesktopOperations
from .macos_keychain import KeychainError, KeychainErrorCode, MacOSKeychain
from .token_store import CachedToken


class CredentialStore(Protocol):
    def save(self, username: str, password: str) -> None: ...

    def load(self) -> tuple[str, str] | None: ...

    def delete(self) -> None: ...


class MemoryTokenStore:
    """Never fall through to TokenStore's POSIX plaintext-file cache."""

    def __init__(self) -> None:
        self._tokens: dict[str, CachedToken] = {}

    def get(self, username: str) -> CachedToken | None:
        return self._tokens.get(username)

    def save(self, username: str, token: str, student_id: str) -> None:
        self._tokens[username] = CachedToken(token, student_id)

    def delete(self, username: str) -> None:
        self._tokens.pop(username, None)

    def clear(self) -> None:
        self._tokens.clear()


def app_root() -> Path:
    home = Path.home()
    if sys.platform != "darwin" or not home.is_absolute():
        raise DesktopError(DesktopErrorCode.MACOS_REQUIRED)
    return home / "Library" / "Application Support" / "SWUCheckin"


KEYCHAIN_ERRORS = {
    KeychainErrorCode.MACOS_REQUIRED: DesktopErrorCode.MACOS_REQUIRED,
    KeychainErrorCode.UNAVAILABLE: DesktopErrorCode.KEYCHAIN_UNAVAILABLE,
    KeychainErrorCode.CANCELLED: DesktopErrorCode.KEYCHAIN_CANCELLED,
    KeychainErrorCode.LOCKED: DesktopErrorCode.KEYCHAIN_LOCKED,
    KeychainErrorCode.ACCESS_DENIED: DesktopErrorCode.KEYCHAIN_ACCESS_DENIED,
    KeychainErrorCode.INVALID_DATA: DesktopErrorCode.KEYCHAIN_INVALID_DATA,
    KeychainErrorCode.OPERATION_FAILED: DesktopErrorCode.KEYCHAIN_OPERATION_FAILED,
}


class MacOSBackend(DesktopOperations):
    def __init__(self, root: Path | None = None, *, keychain: CredentialStore | None = None) -> None:
        super().__init__(root if root is not None else app_root())
        self.keychain = keychain if keychain is not None else MacOSKeychain()
        self.tokens = MemoryTokenStore()

    def _options(self) -> dict:
        return {"token_store": self.tokens}

    def save_credentials(self, username: str, password: str) -> None:
        if not username.strip() or not password:
            raise DesktopError(DesktopErrorCode.CREDENTIALS_EMPTY)
        try:
            self.keychain.save(username, password)
        except KeychainError as error:
            raise DesktopError(KEYCHAIN_ERRORS[error.code]) from None
        except Exception:
            raise DesktopError(DesktopErrorCode.KEYCHAIN_OPERATION_FAILED) from None
        self.tokens.clear()

    def load_credentials(self) -> tuple[str, str] | None:
        try:
            return self.keychain.load()
        except KeychainError as error:
            raise DesktopError(KEYCHAIN_ERRORS[error.code]) from None
        except Exception:
            raise DesktopError(DesktopErrorCode.KEYCHAIN_OPERATION_FAILED) from None

    def delete_credentials(self) -> None:
        try:
            self.keychain.delete()
        except KeychainError as error:
            raise DesktopError(KEYCHAIN_ERRORS[error.code]) from None
        except Exception:
            raise DesktopError(DesktopErrorCode.KEYCHAIN_OPERATION_FAILED) from None
        self.tokens.clear()

    def run_scheduled(self) -> int:
        # The public desktop parser refuses --scheduled on macOS too.
        return 1

    def self_test(self) -> int:
        """Offline frozen dependencies and actual Tk window, without Keychain access."""
        import ssl
        import tempfile
        import tkinter as tk

        import certifi
        import ddddocr
        from PIL import Image

        from .desktop import MACOS_PRESENTATION, DesktopApp
        from .runtime_lock import RuntimeLock
        from .time_utils import today_shanghai

        ssl.create_default_context(cafile=certifi.where())
        today_shanghai()
        image = Image.new("RGB", (100, 40), "white")
        ddddocr.DdddOcr(show_ad=False, use_gpu=False).classification(image)
        with tempfile.TemporaryDirectory(prefix="swu-macos-offline-") as directory:
            with RuntimeLock(Path(directory) / "test.lock"):
                pass
        window = tk.Tk()
        try:
            app = DesktopApp(window, self, MACOS_PRESENTATION)
            window.update()
            assert not app.controller.busy
            assert app.username.get() == app.password.get() == ""
            assert not app.presentation.scheduling
        finally:
            window.destroy()
        return 0
