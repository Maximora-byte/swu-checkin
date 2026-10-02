"""Opt-in macOS credential storage using Security.framework, never a shell.

The unsigned desktop preview uses the default file-based Keychain and its
calling-application ACL. Data-protection Keychain access requires provisioned
signing entitlements; there is deliberately no fallback between implementations.
Both username and password are in the encrypted item value, not its attributes.
Importing this module or constructing MacOSKeychain does not access Keychain.

Apple references:
https://developer.apple.com/documentation/technotes/tn3137-on-mac-keychains
https://developer.apple.com/documentation/security/updating-and-deleting-keychain-items
"""

from __future__ import annotations

import ctypes
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from typing import Protocol

SERVICE = "io.github.maximora-byte.swu-checkin.desktop-preview"
ACCOUNT = "desktop-credentials-v1"
_MAX_VALUE_BYTES = 65536
_SUCCESS = 0
_DUPLICATE_ITEM = -25299
_ITEM_NOT_FOUND = -25300


class KeychainErrorCode(StrEnum):
    MACOS_REQUIRED = "macos_required"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"
    LOCKED = "locked"
    ACCESS_DENIED = "access_denied"
    INVALID_DATA = "invalid_data"
    OPERATION_FAILED = "operation_failed"


class KeychainError(Exception):
    """Only fixed codes cross the native boundary; no native messages or values."""

    def __init__(self, code: KeychainErrorCode) -> None:
        self.code = code if isinstance(code, KeychainErrorCode) else KeychainErrorCode.OPERATION_FAILED
        super().__init__(self.code.value)


def _check_status(status: int) -> None:
    if type(status) is int and status == _SUCCESS:
        return
    mapping = {
        -128: KeychainErrorCode.CANCELLED,  # errSecUserCanceled
        -25291: KeychainErrorCode.UNAVAILABLE,  # errSecNotAvailable
        -25294: KeychainErrorCode.UNAVAILABLE,  # errSecNoSuchKeychain
        -25295: KeychainErrorCode.UNAVAILABLE,  # errSecInvalidKeychain
        -25307: KeychainErrorCode.UNAVAILABLE,  # errSecNoDefaultKeychain
        -25308: KeychainErrorCode.LOCKED,  # errSecInteractionNotAllowed
        -25315: KeychainErrorCode.LOCKED,  # errSecInteractionRequired
        -25292: KeychainErrorCode.ACCESS_DENIED,  # errSecReadOnly
        -25293: KeychainErrorCode.ACCESS_DENIED,  # errSecAuthFailed
        -34018: KeychainErrorCode.ACCESS_DENIED,  # errSecMissingEntitlement
        -26275: KeychainErrorCode.INVALID_DATA,  # errSecDecode
    }
    code = mapping.get(status, KeychainErrorCode.OPERATION_FAILED) if type(status) is int else None
    raise KeychainError(code or KeychainErrorCode.OPERATION_FAILED)


class KeychainBinding(Protocol):
    """Narrow injectable boundary for offline tests and isolated native CI smoke."""

    def add(self, service: str, account: str, data: bytes) -> int: ...

    def update(self, service: str, account: str, data: bytes) -> int: ...

    def copy(self, service: str, account: str) -> tuple[int, bytes | None]: ...

    def delete(self, service: str, account: str) -> int: ...


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


class MacOSKeychain:
    """One app-owned credential; call load only for an explicit user action.

    No credentials are cached on this object. Python/native temporary buffers
    cannot offer guaranteed zeroization; callers should keep their lifetime short.
    """

    def __init__(self, binding: KeychainBinding | None = None) -> None:
        self._binding = binding

    def _backend(self) -> KeychainBinding:
        if self._binding is None:
            if sys.platform != "darwin":
                raise KeychainError(KeychainErrorCode.MACOS_REQUIRED)
            try:
                self._binding = _SecurityFrameworkBinding()
            except KeychainError:
                raise
            except Exception:
                raise KeychainError(KeychainErrorCode.UNAVAILABLE) from None
        return self._binding

    def save(self, username: str, password: str) -> None:
        if type(username) is not str or not username.strip() or type(password) is not str or not password:
            raise KeychainError(KeychainErrorCode.INVALID_DATA)
        try:
            data = json.dumps(
                {"schema_version": 1, "username": username.strip(), "password": password},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(data) > _MAX_VALUE_BYTES:
                raise ValueError
        except Exception:
            raise KeychainError(KeychainErrorCode.INVALID_DATA) from None
        try:
            binding = self._backend()
            status = binding.add(SERVICE, ACCOUNT, data)
            if type(status) is int and status == _DUPLICATE_ITEM:
                # Never delete and re-add: retain the existing ACL and old value
                # if an update is denied, cancelled, or otherwise fails.
                status = binding.update(SERVICE, ACCOUNT, data)
            _check_status(status)
        except KeychainError:
            raise
        except Exception:
            raise KeychainError(KeychainErrorCode.OPERATION_FAILED) from None

    def load(self) -> tuple[str, str] | None:
        try:
            status, data = self._backend().copy(SERVICE, ACCOUNT)
            if type(status) is int and status == _ITEM_NOT_FOUND:
                return None
            _check_status(status)
        except KeychainError:
            raise
        except Exception:
            raise KeychainError(KeychainErrorCode.OPERATION_FAILED) from None
        try:
            if type(data) is not bytes or not data or len(data) > _MAX_VALUE_BYTES:
                raise ValueError
            payload = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_json_object)
            if type(payload) is not dict or set(payload) != {"schema_version", "username", "password"}:
                raise ValueError
            if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
                raise ValueError
            username, password = payload["username"], payload["password"]
            if (
                type(username) is not str
                or not username
                or username != username.strip()
                or type(password) is not str
                or not password
            ):
                raise ValueError
            # Reject unpaired escaped surrogates as well as invalid UTF-8 bytes.
            username.encode("utf-8")
            password.encode("utf-8")
            return username, password
        except Exception:
            raise KeychainError(KeychainErrorCode.INVALID_DATA) from None

    def delete(self) -> None:
        try:
            status = self._backend().delete(SERVICE, ACCOUNT)
            if type(status) is int and status == _ITEM_NOT_FOUND:
                return
            _check_status(status)
        except KeychainError:
            raise
        except Exception:
            raise KeychainError(KeychainErrorCode.OPERATION_FAILED) from None


class _CFCallbacks(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_long),
        ("retain", ctypes.c_void_p),
        ("release", ctypes.c_void_p),
        ("copy_description", ctypes.c_void_p),
        ("equal", ctypes.c_void_p),
    ]


class _CFKeyCallbacks(ctypes.Structure):
    _fields_ = [*_CFCallbacks._fields_, ("hash", ctypes.c_void_p)]


class _CFObjects:
    """Own all temporary CF references until the native operation finishes."""

    def __init__(self, native: _SecurityFrameworkBinding) -> None:
        self.native = native
        self.owned: list[int] = []

    def own(self, reference: int | None) -> int:
        if not reference:
            raise KeychainError(KeychainErrorCode.UNAVAILABLE)
        self.owned.append(reference)
        return reference

    def string(self, value: str) -> int:
        return self.own(self.native._core.CFStringCreateWithCString(None, value.encode("utf-8"), 0x08000100))

    def data(self, value: bytes) -> int:
        return self.own(self.native._core.CFDataCreate(None, value, len(value)))

    def array(self, reference: int) -> int:
        values = (ctypes.c_void_p * 1)(reference)
        return self.own(self.native._core.CFArrayCreate(None, values, 1, ctypes.byref(self.native._array_callbacks)))

    def dictionary(self, entries: dict[str, int]) -> int:
        reference = self.own(
            self.native._core.CFDictionaryCreateMutable(
                None, 0, ctypes.byref(self.native._key_callbacks), ctypes.byref(self.native._value_callbacks)
            )
        )
        for key, value in entries.items():
            self.native._core.CFDictionarySetValue(reference, self.native._constants[key], value)
        return reference

    def release(self) -> None:
        for reference in reversed(self.owned):
            self.native._core.CFRelease(reference)
        self.owned.clear()


class _SecurityFrameworkBinding:
    """ctypes bridge to Apple's generic-password API, with no command execution.

    Each operation restricts itself to the default Keychain, never the full
    search list. No ACL/synchronization changes or automatic unlocks are made.
    """

    _security: ctypes.CDLL
    _core: ctypes.CDLL
    _key_callbacks: _CFKeyCallbacks
    _value_callbacks: _CFCallbacks
    _array_callbacks: _CFCallbacks
    _true: int

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise KeychainError(KeychainErrorCode.MACOS_REQUIRED)
        # Fixed OS framework paths: do not resolve libraries using PATH or a shell.
        self._security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        self._core = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        pointer = ctypes.c_void_p
        for name, args, result in (
            ("SecKeychainCopyDefault", [ctypes.POINTER(pointer)], ctypes.c_int32),
            ("SecItemAdd", [pointer, ctypes.POINTER(pointer)], ctypes.c_int32),
            ("SecItemUpdate", [pointer, pointer], ctypes.c_int32),
            ("SecItemCopyMatching", [pointer, ctypes.POINTER(pointer)], ctypes.c_int32),
            ("SecItemDelete", [pointer], ctypes.c_int32),
        ):
            function = getattr(self._security, name)
            function.argtypes = args
            function.restype = result
        for core_name, core_args, core_result in (
            ("CFStringCreateWithCString", [pointer, ctypes.c_char_p, ctypes.c_uint32], pointer),
            ("CFDataCreate", [pointer, ctypes.c_char_p, ctypes.c_long], pointer),
            ("CFArrayCreate", [pointer, ctypes.POINTER(pointer), ctypes.c_long, pointer], pointer),
            ("CFDictionaryCreateMutable", [pointer, ctypes.c_long, pointer, pointer], pointer),
            ("CFDictionarySetValue", [pointer, pointer, pointer], None),
            ("CFGetTypeID", [pointer], ctypes.c_ulong),
            ("CFDataGetTypeID", [], ctypes.c_ulong),
            ("CFDataGetLength", [pointer], ctypes.c_long),
            ("CFDataGetBytePtr", [pointer], pointer),
            ("CFRelease", [pointer], None),
        ):
            core_function = getattr(self._core, core_name)
            core_function.argtypes = core_args
            core_function.restype = core_result
        self._key_callbacks = _CFKeyCallbacks.in_dll(self._core, "kCFTypeDictionaryKeyCallBacks")
        self._value_callbacks = _CFCallbacks.in_dll(self._core, "kCFTypeDictionaryValueCallBacks")
        self._array_callbacks = _CFCallbacks.in_dll(self._core, "kCFTypeArrayCallBacks")
        self._constants: dict[str, int] = {}
        for name in (
            "kSecClass",
            "kSecClassGenericPassword",
            "kSecAttrService",
            "kSecAttrAccount",
            "kSecValueData",
            "kSecReturnData",
            "kSecMatchLimit",
            "kSecMatchLimitOne",
            "kSecUseKeychain",
            "kSecMatchSearchList",
        ):
            value = pointer.in_dll(self._security, name).value
            if value is None:
                raise KeychainError(KeychainErrorCode.UNAVAILABLE)
            self._constants[name] = value
        true = pointer.in_dll(self._core, "kCFBooleanTrue").value
        if true is None:
            raise KeychainError(KeychainErrorCode.UNAVAILABLE)
        self._true = true

    @contextmanager
    def _query(
        self, service: str, account: str, *, adding: bool = False
    ) -> Iterator[tuple[_CFObjects, dict[str, int]]]:
        objects = _CFObjects(self)
        try:
            reference = ctypes.c_void_p()
            status = self._security.SecKeychainCopyDefault(ctypes.byref(reference))
            if reference.value:
                objects.own(reference.value)
            _check_status(status)
            if reference.value is None:
                raise KeychainError(KeychainErrorCode.UNAVAILABLE)
            entries = {
                "kSecClass": self._constants["kSecClassGenericPassword"],
                "kSecAttrService": objects.string(service),
                "kSecAttrAccount": objects.string(account),
            }
            if adding:
                entries["kSecUseKeychain"] = reference.value
            else:
                entries["kSecMatchSearchList"] = objects.array(reference.value)
            yield objects, entries
        finally:
            objects.release()

    def add(self, service: str, account: str, data: bytes) -> int:
        with self._query(service, account, adding=True) as (objects, entries):
            entries["kSecValueData"] = objects.data(data)
            return int(self._security.SecItemAdd(objects.dictionary(entries), None))

    def update(self, service: str, account: str, data: bytes) -> int:
        with self._query(service, account) as (objects, entries):
            attributes = objects.dictionary({"kSecValueData": objects.data(data)})
            return int(self._security.SecItemUpdate(objects.dictionary(entries), attributes))

    def copy(self, service: str, account: str) -> tuple[int, bytes | None]:
        with self._query(service, account) as (objects, entries):
            entries["kSecReturnData"] = self._true
            entries["kSecMatchLimit"] = self._constants["kSecMatchLimitOne"]
            result = ctypes.c_void_p()
            status = int(self._security.SecItemCopyMatching(objects.dictionary(entries), ctypes.byref(result)))
            if result.value:
                objects.own(result.value)
            if status != _SUCCESS:
                return status, None
            if not result.value or self._core.CFGetTypeID(result.value) != self._core.CFDataGetTypeID():
                raise KeychainError(KeychainErrorCode.INVALID_DATA)
            length = self._core.CFDataGetLength(result.value)
            if not 0 < length <= _MAX_VALUE_BYTES:
                raise KeychainError(KeychainErrorCode.INVALID_DATA)
            buffer = self._core.CFDataGetBytePtr(result.value)
            if not buffer:
                raise KeychainError(KeychainErrorCode.INVALID_DATA)
            return status, ctypes.string_at(buffer, length)

    def delete(self, service: str, account: str) -> int:
        with self._query(service, account) as (objects, entries):
            return int(self._security.SecItemDelete(objects.dictionary(entries)))
