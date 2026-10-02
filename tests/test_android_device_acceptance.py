"""A wrong ABI/page-size device must never satisfy the requested Android gate."""

import pytest

from scripts.android.verify_device import check_device


def test_expected_16kb_device_is_accepted():
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
def test_wrong_device_is_rejected(metadata):
    with pytest.raises(ValueError, match="expected"):
        check_device(metadata, api=35, abi="arm64-v8a", page_size=16384)
