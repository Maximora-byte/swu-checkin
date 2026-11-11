"""DES-style credential encoding used by the SWU IDM login page.

A port of the site's ``des.js`` ``strEnc(data, key, "", "")``: the text is split
into 4-character blocks (16 bits per UTF-16 code unit, zero padded), each block
is DES-encrypted once per 4-character slice of the key, and the result is
upper-case hex. Only the single-key encrypt path the login form uses is kept.
"""

from __future__ import annotations


def strEnc(data: str, key: str) -> str:
    """Encrypt ``data`` with the login page's per-session ``key`` (empty key: no encryption)."""

    key_blocks = getKeyBytes(key) if key else []
    encrypted = []
    for start in range(0, len(data), 4):
        block = strToBt(data[start : start + 4])
        for key_block in key_blocks:
            block = enc(block, key_block)
        encrypted.append(bt64ToHex(block))
    return "".join(encrypted)


def getKeyBytes(key: str) -> list[list[int]]:
    keyBytes: list[list[int]] = []
    leng = len(key)
    iterator = leng // 4
    remainder = leng % 4
    for i in range(iterator):
        keyBytes.append(strToBt(key[i * 4 : (i + 1) * 4]))
    if remainder > 0:
        keyBytes.append(strToBt(key[iterator * 4 : leng]))
    return keyBytes


def strToBt(s: str) -> list[int]:
    """Pack up to 4 characters as big-endian 16-bit values into 64 bits, zero padded."""

    bt = [0] * 64
    for i, char in enumerate(s[:4]):
        code = ord(char)
        for j in range(16):
            bt[16 * i + j] = (code >> (15 - j)) & 1
    return bt


def bt4ToHex(binary: str) -> str:
    mapping = {
        "0000": "0",
        "0001": "1",
        "0010": "2",
        "0011": "3",
        "0100": "4",
        "0101": "5",
        "0110": "6",
        "0111": "7",
        "1000": "8",
        "1001": "9",
        "1010": "A",
        "1011": "B",
        "1100": "C",
        "1101": "D",
        "1110": "E",
        "1111": "F",
    }
    return mapping[binary]


def bt64ToHex(byteData):
    hexs = []
    for i in range(16):
        bt = "".join(str(bit) for bit in byteData[i * 4 : i * 4 + 4])
        hexs.append(bt4ToHex(bt))
    return "".join(hexs)


def enc(dataByte, keyByte):
    keys = generateKeys(keyByte)
    ipByte = initPermute(dataByte)
    ipLeft = ipByte[:32]
    ipRight = ipByte[32:]

    for i in range(16):
        tempLeft = ipLeft[:]
        ipLeft = ipRight[:]
        key = keys[i][:]
        tempRight = xor_(pPermute(sBoxPermute(xor_(expandPermute(ipRight), key))), tempLeft)
        ipRight = tempRight[:]

    finalData = [0] * 64
    for i in range(32):
        finalData[i] = ipRight[i]
        finalData[32 + i] = ipLeft[i]
    return finallyPermute(finalData)


def initPermute(originalData):
    ipByte = [0] * 64
    i = m = n = 0
    for i in range(4):
        m = i * 2 + 1
        n = i * 2
        for j in range(7, -1, -1):
            k = 7 - j
            ipByte[i * 8 + k] = originalData[j * 8 + m]
            ipByte[i * 8 + k + 32] = originalData[j * 8 + n]
    return ipByte


def expandPermute(rightData):
    epByte = [0] * 48
    for i in range(8):
        if i == 0:
            epByte[i * 6 + 0] = rightData[31]
        else:
            epByte[i * 6 + 0] = rightData[i * 4 - 1]
        epByte[i * 6 + 1] = rightData[i * 4 + 0]
        epByte[i * 6 + 2] = rightData[i * 4 + 1]
        epByte[i * 6 + 3] = rightData[i * 4 + 2]
        epByte[i * 6 + 4] = rightData[i * 4 + 3]
        if i == 7:
            epByte[i * 6 + 5] = rightData[0]
        else:
            epByte[i * 6 + 5] = rightData[i * 4 + 4]
    return epByte


def xor_(byteOne, byteTwo):
    return [byteOne[i] ^ byteTwo[i] for i in range(len(byteOne))]


def sBoxPermute(expandByte):
    sBoxByte = [0] * 32
    s1 = [
        [14, 4, 13, 1, 2, 15, 11, 8, 3, 10, 6, 12, 5, 9, 0, 7],
        [0, 15, 7, 4, 14, 2, 13, 1, 10, 6, 12, 11, 9, 5, 3, 8],
        [4, 1, 14, 8, 13, 6, 2, 11, 15, 12, 9, 7, 3, 10, 5, 0],
        [15, 12, 8, 2, 4, 9, 1, 7, 5, 11, 3, 14, 10, 0, 6, 13],
    ]
    s2 = [
        [15, 1, 8, 14, 6, 11, 3, 4, 9, 7, 2, 13, 12, 0, 5, 10],
        [3, 13, 4, 7, 15, 2, 8, 14, 12, 0, 1, 10, 6, 9, 11, 5],
        [0, 14, 7, 11, 10, 4, 13, 1, 5, 8, 12, 6, 9, 3, 2, 15],
        [13, 8, 10, 1, 3, 15, 4, 2, 11, 6, 7, 12, 0, 5, 14, 9],
    ]
    s3 = [
        [10, 0, 9, 14, 6, 3, 15, 5, 1, 13, 12, 7, 11, 4, 2, 8],
        [13, 7, 0, 9, 3, 4, 6, 10, 2, 8, 5, 14, 12, 11, 15, 1],
        [13, 6, 4, 9, 8, 15, 3, 0, 11, 1, 2, 12, 5, 10, 14, 7],
        [1, 10, 13, 0, 6, 9, 8, 7, 4, 15, 14, 3, 11, 5, 2, 12],
    ]
    s4 = [
        [7, 13, 14, 3, 0, 6, 9, 10, 1, 2, 8, 5, 11, 12, 4, 15],
        [13, 8, 11, 5, 6, 15, 0, 3, 4, 7, 2, 12, 1, 10, 14, 9],
        [10, 6, 9, 0, 12, 11, 7, 13, 15, 1, 3, 14, 5, 2, 8, 4],
        [3, 15, 0, 6, 10, 1, 13, 8, 9, 4, 5, 11, 12, 7, 2, 14],
    ]
    s5 = [
        [2, 12, 4, 1, 7, 10, 11, 6, 8, 5, 3, 15, 13, 0, 14, 9],
        [14, 11, 2, 12, 4, 7, 13, 1, 5, 0, 15, 10, 3, 9, 8, 6],
        [4, 2, 1, 11, 10, 13, 7, 8, 15, 9, 12, 5, 6, 3, 0, 14],
        [11, 8, 12, 7, 1, 14, 2, 13, 6, 15, 0, 9, 10, 4, 5, 3],
    ]
    s6 = [
        [12, 1, 10, 15, 9, 2, 6, 8, 0, 13, 3, 4, 14, 7, 5, 11],
        [10, 15, 4, 2, 7, 12, 9, 5, 6, 1, 13, 14, 0, 11, 3, 8],
        [9, 14, 15, 5, 2, 8, 12, 3, 7, 0, 4, 10, 1, 13, 11, 6],
        [4, 3, 2, 12, 9, 5, 15, 10, 11, 14, 1, 7, 6, 0, 8, 13],
    ]
    s7 = [
        [4, 11, 2, 14, 15, 0, 8, 13, 3, 12, 9, 7, 5, 10, 6, 1],
        [13, 0, 11, 7, 4, 9, 1, 10, 14, 3, 5, 12, 2, 15, 8, 6],
        [1, 4, 11, 13, 12, 3, 7, 14, 10, 15, 6, 8, 0, 5, 9, 2],
        [6, 11, 13, 8, 1, 4, 10, 7, 9, 5, 0, 15, 14, 2, 3, 12],
    ]
    s8 = [
        [13, 2, 8, 4, 6, 15, 11, 1, 10, 9, 3, 14, 5, 0, 12, 7],
        [1, 15, 13, 8, 10, 3, 7, 4, 12, 5, 6, 11, 0, 14, 9, 2],
        [7, 11, 4, 1, 9, 12, 14, 2, 0, 6, 10, 13, 15, 3, 5, 8],
        [2, 1, 14, 7, 4, 10, 8, 13, 15, 12, 9, 0, 3, 5, 6, 11],
    ]
    sboxes = [s1, s2, s3, s4, s5, s6, s7, s8]

    for m in range(8):
        i = expandByte[m * 6 + 0] * 2 + expandByte[m * 6 + 5]
        j = expandByte[m * 6 + 1] * 8 + expandByte[m * 6 + 2] * 4 + expandByte[m * 6 + 3] * 2 + expandByte[m * 6 + 4]
        val = sboxes[m][i][j]
        binary = getBoxBinary(val)
        sBoxByte[m * 4 + 0] = int(binary[0])
        sBoxByte[m * 4 + 1] = int(binary[1])
        sBoxByte[m * 4 + 2] = int(binary[2])
        sBoxByte[m * 4 + 3] = int(binary[3])
    return sBoxByte


def pPermute(sBoxByte):
    idx = [
        15,
        6,
        19,
        20,
        28,
        11,
        27,
        16,
        0,
        14,
        22,
        25,
        4,
        17,
        30,
        9,
        1,
        7,
        23,
        13,
        31,
        26,
        2,
        8,
        18,
        12,
        29,
        5,
        21,
        10,
        3,
        24,
    ]
    return [sBoxByte[i] for i in idx]


def finallyPermute(endByte):
    idx = [
        39,
        7,
        47,
        15,
        55,
        23,
        63,
        31,
        38,
        6,
        46,
        14,
        54,
        22,
        62,
        30,
        37,
        5,
        45,
        13,
        53,
        21,
        61,
        29,
        36,
        4,
        44,
        12,
        52,
        20,
        60,
        28,
        35,
        3,
        43,
        11,
        51,
        19,
        59,
        27,
        34,
        2,
        42,
        10,
        50,
        18,
        58,
        26,
        33,
        1,
        41,
        9,
        49,
        17,
        57,
        25,
        32,
        0,
        40,
        8,
        48,
        16,
        56,
        24,
    ]
    return [endByte[i] for i in idx]


def getBoxBinary(i: int) -> str:
    mapping = {
        0: "0000",
        1: "0001",
        2: "0010",
        3: "0011",
        4: "0100",
        5: "0101",
        6: "0110",
        7: "0111",
        8: "1000",
        9: "1001",
        10: "1010",
        11: "1011",
        12: "1100",
        13: "1101",
        14: "1110",
        15: "1111",
    }
    return mapping[i]


def generateKeys(keyByte):
    key = [0] * 56
    keys = [[0] * 48 for _ in range(16)]
    loop = [1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1]

    for i in range(7):
        for j, k in zip(range(8), range(7, -1, -1), strict=True):
            key[i * 8 + j] = keyByte[8 * k + i]

    for i in range(16):
        for _ in range(loop[i]):
            tempLeft = key[0]
            tempRight = key[28]
            for k in range(27):
                key[k] = key[k + 1]
                key[28 + k] = key[29 + k]
            key[27] = tempLeft
            key[55] = tempRight
        tempKey = [0] * 48
        mapping = [
            13,
            16,
            10,
            23,
            0,
            4,
            2,
            27,
            14,
            5,
            20,
            9,
            22,
            18,
            11,
            3,
            25,
            7,
            15,
            6,
            26,
            19,
            12,
            1,
            40,
            51,
            30,
            36,
            46,
            54,
            29,
            39,
            50,
            44,
            32,
            47,
            43,
            48,
            38,
            55,
            33,
            52,
            45,
            41,
            49,
            35,
            28,
            31,
        ]
        for m in range(48):
            tempKey[m] = key[mapping[m]]
        keys[i] = tempKey
    return keys


def des(username: str, password: str, random: str) -> tuple[str, str]:
    return strEnc(username, random), strEnc(password, random)
