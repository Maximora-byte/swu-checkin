"""A wrong ABI/page-size device must never satisfy the requested Android gate."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def check_device(monkeypatch):
    directory = Path(__file__).resolve().parents[1] / "scripts/android"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("android_device_acceptance", directory / "verify_device.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_device


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
