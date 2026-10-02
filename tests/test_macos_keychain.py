from __future__ import annotations

import ctypes
import json
import runpy
import subprocess
import traceback
from pathlib import Path

import pytest

from swu_checkin import macos_keychain as keychain
from swu_checkin.macos_keychain import ACCOUNT, SERVICE, KeychainError, KeychainErrorCode, MacOSKeychain


class FakeBinding:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.value: bytes | None = None
        self.statuses: dict[str, int] = {}
        self.error: Exception | None = None

    def _call(self, method: str, service: str, account: str, *data: bytes) -> None:
        self.calls.append((method, service, account, *data))
        if self.error:
            raise self.error

    def add(self, service: str, account: str, data: bytes) -> int:
        self._call("add", service, account, data)
        status = self.statuses.get("add", -25299 if self.value is not None else 0)
        if status == 0:
            self.value = data
        return status

    def update(self, service: str, account: str, data: bytes) -> int:
        self._call("update", service, account, data)
        status = self.statuses.get("update", 0)
        if status == 0:
            self.value = data
        return status

    def copy(self, service: str, account: str) -> tuple[int, bytes | None]:
        self._call("copy", service, account)
        return self.statuses.get("copy", -25300 if self.value is None else 0), self.value

    def delete(self, service: str, account: str) -> int:
        self._call("delete", service, account)
        status = self.statuses.get("delete", -25300 if self.value is None else 0)
        if status == 0:
            self.value = None
        return status


def test_import_and_construction_do_not_load_frameworks_or_read_keychain(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected native access")

    monkeypatch.setattr(ctypes, "CDLL", forbidden)
    runpy.run_path(keychain.__file__)
    monkeypatch.setattr(keychain, "_SecurityFrameworkBinding", forbidden)
    MacOSKeychain()
    binding = FakeBinding()
    MacOSKeychain(binding=binding)
    assert binding.calls == []


@pytest.mark.parametrize("operation", ["save", "load", "delete"])
def test_platform_gating_happens_only_when_used(monkeypatch, operation):
    monkeypatch.setattr(keychain.sys, "platform", "linux")
    store = MacOSKeychain()
    with pytest.raises(KeychainError) as exc:
        getattr(store, operation)(*(["user", "password"] if operation == "save" else []))
    assert exc.value.code is KeychainErrorCode.MACOS_REQUIRED


def test_framework_init_failure_is_fixed_and_lazy(monkeypatch):
    monkeypatch.setattr(keychain.sys, "platform", "darwin")

    def unavailable():
        raise OSError("secret-native-detail")

    monkeypatch.setattr(keychain, "_SecurityFrameworkBinding", unavailable)
    store = MacOSKeychain()
    with pytest.raises(KeychainError) as exc:
        store.load()
    assert exc.value.code is KeychainErrorCode.UNAVAILABLE
    assert "secret-native-detail" not in "".join(traceback.format_exception(exc.value))


def test_success_roundtrip_update_delete_uses_only_fixed_app_item(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("must not spawn a command or write a credential file")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    binding = FakeBinding()
    store = MacOSKeychain(binding)
    assert store.load() is None
    store.save(" 用户 ", " pass\x00word 密码 ")
    assert store.load() == ("用户", " pass\x00word 密码 ")
    assert json.loads(binding.value) == {"schema_version": 1, "username": "用户", "password": " pass\x00word 密码 "}
    store.save("second", "new-password")
    assert store.load() == ("second", "new-password")
    store.delete()
    assert store.load() is None
    store.delete()
    assert [call[0] for call in binding.calls] == [
        "copy",
        "add",
        "copy",
        "add",
        "update",
        "copy",
        "delete",
        "copy",
        "delete",
    ]
    assert all(call[1:3] == (SERVICE, ACCOUNT) for call in binding.calls)
    assert vars(store) == {"_binding": binding}


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (-128, KeychainErrorCode.CANCELLED),
        (-25291, KeychainErrorCode.UNAVAILABLE),
        (-25294, KeychainErrorCode.UNAVAILABLE),
        (-25295, KeychainErrorCode.UNAVAILABLE),
        (-25307, KeychainErrorCode.UNAVAILABLE),
        (-25308, KeychainErrorCode.LOCKED),
        (-25315, KeychainErrorCode.LOCKED),
        (-25292, KeychainErrorCode.ACCESS_DENIED),
        (-25293, KeychainErrorCode.ACCESS_DENIED),
        (-34018, KeychainErrorCode.ACCESS_DENIED),
        (-26275, KeychainErrorCode.INVALID_DATA),
        (-50, KeychainErrorCode.OPERATION_FAILED),
        (123456, KeychainErrorCode.OPERATION_FAILED),
        (False, KeychainErrorCode.OPERATION_FAILED),
        (None, KeychainErrorCode.OPERATION_FAILED),
    ],
)
@pytest.mark.parametrize("method", ["add", "update", "copy", "delete"])
def test_all_error_statuses_fail_closed(status, expected, method):
    binding = FakeBinding()
    binding.value = b"original-synthetic-value"
    binding.statuses[method] = status
    if method == "update":
        binding.statuses["add"] = -25299
    store = MacOSKeychain(binding)
    with pytest.raises(KeychainError) as exc:
        if method in ("add", "update"):
            store.save("synthetic-user", "synthetic-password")
        elif method == "copy":
            store.load()
        else:
            store.delete()
    assert exc.value.code is expected
    assert str(exc.value) == expected.value
    assert len(binding.calls) == (2 if method == "update" else 1)
    assert not any(call[0] == "delete" for call in binding.calls if method in ("add", "update"))


def test_failed_duplicate_update_preserves_previous_value():
    binding = FakeBinding()
    store = MacOSKeychain(binding)
    store.save("original-user", "original-password")
    binding.statuses["update"] = -128
    with pytest.raises(KeychainError, match="^cancelled$"):
        store.save("new-user", "new-password")
    assert store.load() == ("original-user", "original-password")
    assert all(call[0] != "delete" for call in binding.calls)


@pytest.mark.parametrize("method", ["add", "update"])
def test_item_missing_is_not_success_during_save(method):
    binding = FakeBinding()
    binding.statuses[method] = -25300
    if method == "update":
        binding.statuses["add"] = -25299
    with pytest.raises(KeychainError, match="^operation_failed$"):
        MacOSKeychain(binding).save("user", "password")
    assert len(binding.calls) == (2 if method == "update" else 1)


@pytest.mark.parametrize("operation", ["save", "load", "delete"])
def test_unexpected_native_exception_does_not_leak_message(operation):
    binding = FakeBinding()
    binding.error = RuntimeError("synthetic-username synthetic-password raw-native-detail")
    with pytest.raises(KeychainError) as exc:
        getattr(MacOSKeychain(binding), operation)(*(["user", "password"] if operation == "save" else []))
    assert exc.value.code is KeychainErrorCode.OPERATION_FAILED
    assert "raw-native-detail" not in "".join(traceback.format_exception(exc.value))
    assert len(binding.calls) == 1


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("", "p"),
        (" \n ", "p"),
        (None, "p"),
        (123, "p"),
        ("u", ""),
        ("u", None),
        ("u", True),
        ("\ud800", "p"),
        ("u", "\ud800"),
        ("u", "x" * 65536),
    ],
)
def test_invalid_save_never_accesses_keychain(username, password):
    binding = FakeBinding()
    with pytest.raises(KeychainError, match="^invalid_data$"):
        MacOSKeychain(binding).save(username, password)
    assert binding.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        None,
        b"",
        b"not-json",
        b"\xff",
        b"[]",
        b"null",
        b"false",
        b"{}",
        b"x" * 65537,
        b'{"schema_version":1,"username":"u","password":"p","extra":true}',
        b'{"schema_version":1,"username":"u","password":"p","password":"other"}',
        b'{"schema_version":true,"username":"u","password":"p"}',
        b'{"schema_version":1.0,"username":"u","password":"p"}',
        b'{"schema_version":2,"username":"u","password":"p"}',
        b'{"schema_version":1,"username":"u"}',
        b'{"schema_version":1,"username":"","password":"p"}',
        b'{"schema_version":1,"username":" ","password":"p"}',
        b'{"schema_version":1,"username":" u ","password":"p"}',
        b'{"schema_version":1,"username":123,"password":"p"}',
        b'{"schema_version":1,"username":"u","password":""}',
        b'{"schema_version":1,"username":"u","password":123}',
        b'{"schema_version":1,"username":"u","password":"\\ud800"}',
        b'{"schema_version":1,"username":"u","password":NaN}',
        b"[" * 1200 + b"]" * 1200,
        "not-bytes",
    ],
)
def test_load_rejects_malformed_exact_schema(payload):
    binding = FakeBinding()
    binding.statuses["copy"] = 0
    binding.value = payload
    with pytest.raises(KeychainError) as exc:
        MacOSKeychain(binding).load()
    assert exc.value.code is KeychainErrorCode.INVALID_DATA
    assert str(exc.value) == "invalid_data"
    assert len(binding.calls) == 1


def test_error_constructor_cannot_surface_arbitrary_text():
    assert str(KeychainError("secret-value")) == "operation_failed"


def test_native_bridge_rejects_non_macos_before_loading_framework(monkeypatch):
    monkeypatch.setattr(keychain.sys, "platform", "linux")
    with pytest.raises(KeychainError, match="^macos_required$"):
        keychain._SecurityFrameworkBinding()


def test_ci_smoke_refuses_non_ci_without_loading_native_code(monkeypatch, capsys):
    namespace = runpy.run_path(Path(__file__).resolve().parents[1] / "packaging/macos/keychain_smoke.py")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert namespace["main"]() == 2
    assert "disposable macOS" in capsys.readouterr().out


def test_ci_smoke_never_targets_production_namespace():
    namespace = runpy.run_path(Path(__file__).resolve().parents[1] / "packaging/macos/keychain_smoke.py")
    native = FakeBinding()
    isolated = namespace["_SmokeBinding"](native)
    store = MacOSKeychain(binding=isolated)
    assert store.load() is None
    store.save("ci-user", "ci-password")
    store.save("ci-user-2", "ci-password-2")
    assert store.load() == ("ci-user-2", "ci-password-2")
    store.delete()
    assert all(call[1] != SERVICE and call[2] != ACCOUNT for call in native.calls)
    assert all(call[1:3] == (isolated.service, isolated.account) for call in native.calls)


class FakeCoreFoundation:
    """Pointer-level fake: exercise the actual query and ownership bridge."""

    def __init__(self):
        self.objects = {50: "default-keychain"}
        self.released = []
        self.buffers = []
        self.length_override = None
        self.null_buffer = False
        self.fail_data_create = False

    def allocate(self, value):
        reference = 1000 + len(self.objects)
        self.objects[reference] = value
        return reference

    def CFStringCreateWithCString(self, allocator, value, encoding):
        assert allocator is None and encoding == 0x08000100
        return self.allocate(value.decode("utf-8"))

    def CFDataCreate(self, allocator, value, length):
        assert allocator is None and length == len(value)
        return 0 if self.fail_data_create else self.allocate(value)

    def CFArrayCreate(self, allocator, values, count, callbacks):
        assert allocator is None and count == 1 and callbacks
        return self.allocate([values[0]])

    def CFDictionaryCreateMutable(self, allocator, capacity, keys, values):
        assert allocator is None and capacity == 0 and keys and values
        return self.allocate({})

    def CFDictionarySetValue(self, dictionary, key, value):
        self.objects[dictionary][key] = value

    def CFGetTypeID(self, reference):
        return 10 if isinstance(self.objects[reference], bytes) else 11

    def CFDataGetTypeID(self):
        return 10

    def CFDataGetLength(self, reference):
        return len(self.objects[reference]) if self.length_override is None else self.length_override

    def CFDataGetBytePtr(self, reference):
        if self.null_buffer:
            return None
        buffer = ctypes.create_string_buffer(self.objects[reference])
        self.buffers.append(buffer)
        return ctypes.addressof(buffer)

    def CFRelease(self, reference):
        assert reference not in self.released
        self.released.append(reference)


class FakeSecurity:
    def __init__(self, core):
        self.core = core
        self.calls = []
        self.default_status = 0
        self.default_reference = 50
        self.result_status = 0
        self.result_data = b"test-value\x00with-nul"
        self.null_result = False

    def SecKeychainCopyDefault(self, output):
        output._obj.value = self.default_reference
        return self.default_status

    def SecItemAdd(self, query, output):
        assert output is None
        self.calls.append(("add", query))
        return self.result_status

    def SecItemUpdate(self, query, attributes):
        self.calls.append(("update", query, attributes))
        return self.result_status

    def SecItemCopyMatching(self, query, output):
        self.calls.append(("copy", query))
        output._obj.value = None if self.null_result else self.core.allocate(self.result_data)
        return self.result_status

    def SecItemDelete(self, query):
        self.calls.append(("delete", query))
        return self.result_status


@pytest.fixture
def native_binding():
    native = keychain._SecurityFrameworkBinding.__new__(keychain._SecurityFrameworkBinding)
    native._core = FakeCoreFoundation()
    native._security = FakeSecurity(native._core)
    native._key_callbacks = keychain._CFKeyCallbacks()
    native._value_callbacks = keychain._CFCallbacks()
    native._array_callbacks = keychain._CFCallbacks()
    native._true = 99
    native._constants = {
        name: number
        for number, name in enumerate(
            [
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
            ],
            start=1,
        )
    }
    return native


@pytest.mark.parametrize("operation", ["add", "update", "copy", "delete"])
def test_native_query_is_scoped_and_references_released(native_binding, operation):
    native = native_binding
    data = b"synthetic-data\x00not-attributes"
    args = [SERVICE, ACCOUNT, data] if operation in ("add", "update") else [SERVICE, ACCOUNT]
    result = getattr(native, operation)(*args)
    assert result == ((0, native._security.result_data) if operation == "copy" else 0)
    call = native._security.calls[0]
    constants = native._constants
    core = native._core
    entries = core.objects[call[1]]
    assert entries[constants["kSecClass"]] == constants["kSecClassGenericPassword"]
    assert core.objects[entries[constants["kSecAttrService"]]] == SERVICE
    assert core.objects[entries[constants["kSecAttrAccount"]]] == ACCOUNT
    if operation == "add":
        assert entries[constants["kSecUseKeychain"]] == 50
        assert constants["kSecMatchSearchList"] not in entries
        assert core.objects[entries[constants["kSecValueData"]]] == data
    else:
        assert core.objects[entries[constants["kSecMatchSearchList"]]] == [50]
        assert constants["kSecUseKeychain"] not in entries
        assert constants["kSecValueData"] not in entries
    if operation == "update":
        assert core.objects[call[2]] == {
            constants["kSecValueData"]: next(k for k, v in core.objects.items() if v == data)
        }
    if operation == "copy":
        assert entries[constants["kSecReturnData"]] == native._true
        assert entries[constants["kSecMatchLimit"]] == constants["kSecMatchLimitOne"]
    else:
        assert constants["kSecReturnData"] not in entries
        assert constants["kSecMatchLimit"] not in entries
    assert set(core.released) == set(core.objects)
    assert core.released[-1] == 50


@pytest.mark.parametrize("status", [-128, -25293, -25300, -25308, -50])
@pytest.mark.parametrize("operation", ["add", "update", "copy", "delete"])
def test_native_status_and_cleanup_on_failure(native_binding, status, operation):
    native = native_binding
    native._security.result_status = status
    args = [SERVICE, ACCOUNT, b"test"] if operation in ("add", "update") else [SERVICE, ACCOUNT]
    result = getattr(native, operation)(*args)
    assert result == ((status, None) if operation == "copy" else status)
    assert set(native._core.released) == set(native._core.objects)


@pytest.mark.parametrize("status", [-128, -25308, -25293, -25307])
def test_default_keychain_failure_never_calls_item_api(native_binding, status):
    native_binding._security.default_status = status
    with pytest.raises(KeychainError):
        native_binding.delete(SERVICE, ACCOUNT)
    assert native_binding._security.calls == []
    assert native_binding._core.released == [50]


def test_missing_default_keychain_reference_is_failure(native_binding):
    native_binding._security.default_reference = None
    with pytest.raises(KeychainError, match="^unavailable$"):
        native_binding.delete(SERVICE, ACCOUNT)
    assert native_binding._security.calls == []
    assert native_binding._core.released == []


@pytest.mark.parametrize("case", ["null_result", "wrong_type", "empty", "oversized", "negative_length", "null_buffer"])
def test_native_copy_rejects_invalid_cfdata_and_releases_refs(native_binding, case):
    native = native_binding
    if case == "null_result":
        native._security.null_result = True
    elif case == "wrong_type":
        native._security.result_data = "not-data"
    elif case == "empty":
        native._security.result_data = b""
    elif case == "oversized":
        native._core.length_override = 65537
    elif case == "negative_length":
        native._core.length_override = -1
    else:
        native._core.null_buffer = True
    with pytest.raises(KeychainError, match="^invalid_data$"):
        native.copy(SERVICE, ACCOUNT)
    assert set(native._core.released) == set(native._core.objects)


def test_allocation_failure_releases_earlier_references(native_binding):
    native_binding._core.fail_data_create = True
    with pytest.raises(KeychainError, match="^unavailable$"):
        native_binding.add(SERVICE, ACCOUNT, b"value")
    assert native_binding._security.calls == []
    assert set(native_binding._core.released) == set(native_binding._core.objects)
