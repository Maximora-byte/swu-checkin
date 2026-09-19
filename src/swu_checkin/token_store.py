"""Secure per-user authentication token cache."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

_CACHE_VERSION = 1


class TokenStoreError(RuntimeError):
    """The token cache is unavailable, malformed, or insecure."""


@dataclass(frozen=True)
class CachedToken:
    """A token bound to the student identity validated before caching."""

    token: str
    student_id: str


class TokenStoreProtocol(Protocol):
    def get(self, username: str) -> CachedToken | None: ...

    def save(self, username: str, token: str, student_id: str) -> None: ...

    def delete(self, username: str) -> None: ...


class _Protector(Protocol):
    def protect(self, data: bytes) -> bytes: ...

    def unprotect(self, data: bytes) -> bytes: ...


class _Crypt32(Protocol):
    def CryptProtectData(self, *args: object) -> int: ...

    def CryptUnprotectData(self, *args: object) -> int: ...


class _Kernel32(Protocol):
    def LocalFree(self, memory: object) -> object: ...


class _WindowsLibraries(Protocol):
    crypt32: _Crypt32
    kernel32: _Kernel32


class _WindowsCtypes(Protocol):
    windll: _WindowsLibraries


class _PlainProtector:
    def protect(self, data: bytes) -> bytes:
        return data

    def unprotect(self, data: bytes) -> bytes:
        return data


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class WindowsDpapiProtector:
    """Protect cache bytes for the current Windows user and machine via DPAPI."""

    @staticmethod
    def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(data)
        blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        return blob, buffer

    @staticmethod
    def _crypt32() -> _Crypt32:
        if sys.platform != "win32":
            raise TokenStoreError("Windows DPAPI is unavailable")
        return cast("_WindowsCtypes", ctypes).windll.crypt32

    @staticmethod
    def _local_free(memory: object) -> None:
        cast("_WindowsCtypes", ctypes).windll.kernel32.LocalFree(memory)

    def protect(self, data: bytes) -> bytes:
        source, source_buffer = self._blob(data)
        output = _DataBlob()
        crypt32 = self._crypt32()
        success = crypt32.CryptProtectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            0x1,
            ctypes.byref(output),
        )
        _ = source_buffer
        if not success:
            raise TokenStoreError("Windows DPAPI protection failed")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._local_free(output.pbData)

    def unprotect(self, data: bytes) -> bytes:
        source, source_buffer = self._blob(data)
        output = _DataBlob()
        crypt32 = self._crypt32()
        success = crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            0x1,
            ctypes.byref(output),
        )
        _ = source_buffer
        if not success:
            raise TokenStoreError("Windows DPAPI decryption failed")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._local_free(output.pbData)


def _default_cache_path() -> Path:
    status_file = os.getenv("SWUDK_STATUS_FILE")
    if status_file:
        return Path(status_file).expanduser().parent / "auth-token-cache"
    if sys.platform == "win32":
        local_app_data = os.getenv("LOCALAPPDATA")
        if not local_app_data:
            raise TokenStoreError("LOCALAPPDATA is unavailable")
        return Path(local_app_data) / "SWUCheckin" / "auth-token-cache"
    cache_home = os.getenv("XDG_CACHE_HOME")
    root = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
    return root / "swu-checkin" / "auth-token-cache"


def _username_key(username: str) -> str:
    if not isinstance(username, str) or not username:
        raise TokenStoreError("username is required")
    return hashlib.sha256(username.encode("utf-8")).hexdigest()


class TokenStore:
    """Atomic cache with POSIX 0600 permissions or Windows DPAPI protection."""

    def __init__(self, path: Path | None = None, *, protector: _Protector | None = None) -> None:
        self.path = path or _default_cache_path()
        self._protector = protector or (WindowsDpapiProtector() if sys.platform == "win32" else _PlainProtector())

    def _read_record(self) -> tuple[str, CachedToken] | None:
        if not self.path.exists():
            return None
        if self.path.is_symlink():
            raise TokenStoreError("token cache must not be a symbolic link")
        if sys.platform != "win32" and self.path.stat().st_mode & 0o077:
            raise TokenStoreError("token cache permissions are too broad")
        try:
            raw = self._protector.unprotect(self.path.read_bytes())
            payload: object = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            raise TokenStoreError("token cache is unreadable") from error
        if not isinstance(payload, dict) or payload.get("version") != _CACHE_VERSION:
            raise TokenStoreError("token cache schema is invalid")
        if set(payload) != {"version", "username_key", "token", "student_id"}:
            raise TokenStoreError("token cache fields are invalid")
        username_key = payload["username_key"]
        token = payload["token"]
        student_id = payload["student_id"]
        if (
            not isinstance(username_key, str)
            or not username_key
            or not isinstance(token, str)
            or not token
            or not isinstance(student_id, str)
            or not student_id
        ):
            raise TokenStoreError("token cache entry is invalid")
        return username_key, CachedToken(token, student_id)

    def _write_record(self, username_key: str, record: CachedToken) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "version": _CACHE_VERSION,
                "username_key": username_key,
                "token": record.token,
                "student_id": record.student_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        protected = self._protector.protect(payload)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        temporary_path = Path(temporary_name)
        try:
            if sys.platform != "win32":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(protected)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, self.path)
            if sys.platform != "win32":
                os.chmod(self.path, 0o600)
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            temporary_path.unlink(missing_ok=True)
            raise

    def get(self, username: str) -> CachedToken | None:
        record = self._read_record()
        if record is None:
            return None
        username_key, cached = record
        return cached if username_key == _username_key(username) else None

    def save(self, username: str, token: str, student_id: str) -> None:
        if not isinstance(token, str) or not token or not isinstance(student_id, str) or not student_id:
            raise TokenStoreError("validated token and student identity are required")
        self._write_record(_username_key(username), CachedToken(token, student_id))

    def delete(self, username: str) -> None:
        record = self._read_record()
        if record is not None and record[0] == _username_key(username):
            self.path.unlink(missing_ok=True)
