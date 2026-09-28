"""协议层单测：向量全部来自官方 App 抓包/开源实现，已经人工复算验证。"""

import pytest

from paperang_p1.protocol import (
    Cmd, Frame, FrameParser, build, crc32, handshake_bytes, is_ack,
    STANDARD_KEY,
)

SESSION_KEY = 0x4E048354  # 官方 App 抓包会话密钥（PAPER/FEED/PRINT 帧所属会话，已复算验证）


def h(s: str) -> bytes:
    return bytes.fromhex(s.replace(" ", ""))


# SET_CRC_KEY 握手帧（三组实测向量）
V_HANDSHAKE_IHCIAH = h("02 18 00 04 00 78 7A CE 33 2C 89 80 F0 03")   # key=0x06B8EF59
V_HANDSHAKE_ZERO = h("02 18 00 04 00 21 95 76 35 1C DF 44 21 03")     # key=0
V_HANDSHAKE_OFFICIAL = h("02 18 00 04 00 5E 5A C4 72 A2 A6 A0 B6 03") # key=0x47B2CF7F（另一会话）
V_ACK_STD = h("02 00 00 01 00 00 46 89 5E 9E 03")                      # ACK（标准种子）
V_PAPER_TYPE = h("02 2C 00 01 00 00 E3 7E 4A BE 03")                   # SET_PAPER_TYPE(0)
V_FEED_10 = h("02 1A 00 02 00 0A 00 BB FE 50 11 03")                   # FEED_LINE(10)
V_PRINT_432FF = (
    h("02 00 00 B0 01") + b"\xFF" * 432 + h("43 E1 2E 36 03")
)  # PRINT_DATA 432B（P2 抓包，同一 CRC 算法，用于回归）


def test_handshake_vectors():
    assert handshake_bytes(0x06B8EF59) == V_HANDSHAKE_IHCIAH
    assert handshake_bytes(0) == V_HANDSHAKE_ZERO
    assert handshake_bytes(0x47B2CF7F) == V_HANDSHAKE_OFFICIAL


def test_official_capture_frames_roundtrip():
    assert build(Cmd.SET_PAPER_TYPE, b"\x00", session_key=SESSION_KEY) == V_PAPER_TYPE
    assert build(Cmd.FEED_LINE, b"\x0A\x00", session_key=SESSION_KEY) == V_FEED_10
    assert (
        build(Cmd.PRINT_DATA, b"\xFF" * 432, index=0, session_key=SESSION_KEY)
        == V_PRINT_432FF
    )


def test_parse_official_frames():
    parser = FrameParser(seeds=[STANDARD_KEY, SESSION_KEY])
    frames = parser.feed(V_HANDSHAKE_OFFICIAL + V_PAPER_TYPE + V_FEED_10)
    assert [f.cmd for f in frames] == [
        Cmd.SET_CRC_KEY, Cmd.SET_PAPER_TYPE, Cmd.FEED_LINE,
    ]


def test_parse_with_noise_and_arbitrary_chunking():
    data = b"\x00\xff garbage" + V_ACK_STD + V_FEED_10
    # 按每个可能的切分点分块喂入
    for cut in range(1, len(data)):
        parser = FrameParser(seeds=[STANDARD_KEY, SESSION_KEY])
        out = parser.feed(data[:cut]) + parser.feed(data[cut:])
        assert [(f.cmd, f.payload) for f in out] == [
            (Cmd.PRINT_DATA, b"\x00"),      # ACK(cmd=0, payload=0)
            (Cmd.FEED_LINE, b"\x0A\x00"),
        ]


def test_is_ack():
    f = FrameParser(seeds=[STANDARD_KEY]).feed(V_ACK_STD)[0]
    assert is_ack(f, Cmd.PRINT_DATA)
    assert not is_ack(f, Cmd.SET_CRC_KEY)


def test_crc_matches_zlib_semantics():
    assert crc32(b"\x00", STANDARD_KEY) == 0x9E5E8946  # 由 V_ACK_STD 尾部反推
