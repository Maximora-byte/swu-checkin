"""A wrong ABI/page-size device must never satisfy the requested Android gate."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def device_acceptance(monkeypatch):
    directory = Path(__file__).resolve().parents[1] / "scripts/android"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("android_device_acceptance", directory / "verify_device.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def check_device(device_acceptance):
    return device_acceptance.check_device


@pytest.mark.parametrize("value", ["4096\n", "16384\r\n"])
def test_page_size_from_getconf(device_acceptance, value):
    assert device_acceptance.read_page_size(value) == int(value)


@pytest.mark.parametrize("kb", [4, 16, 64])
def test_android7_page_size_from_actual_kernel_mapping(device_acceptance, kb):
    smaps = f"Size: 128 kB\nKernelPageSize: {kb} kB\nMMUPageSize: {kb} kB\n"
    assert device_acceptance.read_page_size("", smaps) == kb * 1024


@pytest.mark.parametrize("smaps", ["", "Size: 4 kB", "KernelPageSize: 0 kB", "KernelPageSize: unknown kB"])
def test_unknown_page_size_is_never_assumed_to_be_4kb(device_acceptance, smaps):
    with pytest.raises(ValueError, match="valid kernel page size"):
        device_acceptance.read_page_size("", smaps)


def test_expected_16kb_device_is_accepted(check_device):
    check_device({"api": 35, "abi": "x86_64", "page_size": 16384}, api=35, abi="x86_64", page_size=16384)


@pytest.mark.parametrize(
    "metadata",
    [
        {"api": 35, "abi": "x86_64", "page_size": 4096},
        {"api": 35, "abi": "x86_64", "page_size": 16384},
        {"api": 34, "abi": "arm64-v8a", "page_size": 16384},
        {},
    ],
)
def test_wrong_device_is_rejected(metadata, check_device):
    with pytest.raises(ValueError, match="expected"):
        check_device(metadata, api=35, abi="arm64-v8a", page_size=16384)
