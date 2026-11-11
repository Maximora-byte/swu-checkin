"""Golden vectors captured from the original 635-line des.js port before it was trimmed."""

import pytest

from swu_checkin.des import des


@pytest.mark.parametrize(
    ("username", "password", "key", "expected"),
    [
        (
            "20260000000",
            "Passw0rd!",
            "OqxQ1Iea4njSROH/N06Tuw==",
            (
                "B096697F3B11EB16EB4042502EDE2CCFDB0D170BEE7D6BFA",
                "DFAD8965AD39CF75635E5C8DC9F46B47842A654209AD4444",
            ),
        ),
        ("ab", "", "k", ("D0F829120AB59836", "")),
        (
            "测试用户",
            "pässwörd-長い",
            "a1b2c3d4e5",
            ("CB8B40AEAEFA7599", "8875EEE0A1B7312F0931A70C1D6E5B7A84A0DE98DCCA936D"),
        ),
        ("abcd", "abcde", "", ("0061006200630064", "00610062006300640065000000000000")),
    ],
)
def test_des_matches_original_login_page_encoding(username, password, key, expected):
    assert des(username, password, key) == expected
