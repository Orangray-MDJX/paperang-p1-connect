"""Paperang 私有帧协议：封包、CRC 会话、流式解析。

帧格式（SPP / BLE GATT / USB bulk 三种载体完全相同）::

    0x02 | cmd(1B) | index(1B) | len(u16 LE) | payload | crc32(u32 LE) | 0x03

- CRC32 = zlib.crc32(payload, seed)，seed 即会话密钥。
- 握手（SET_CRC_KEY=0x18）：payload = LE32(new_key ^ 0x35769521)，
  握手帧自身用固定种子 0x35769521，此后双方改用 new_key。
- 设备对每条指令先回 ACK（cmd 同值，payload=b"\\x00"），查询类指令随后
  再回 SENT_* 应答帧（cmd = 请求 cmd + 1）。
"""

from __future__ import annotations

import logging
import struct
import zlib
from dataclasses import dataclass, field
from enum import IntEnum

log = logging.getLogger(__name__)

STX = 0x02
ETX = 0x03
HEADER_LEN = 5          # stx + cmd + index + len(2)
TAIL_LEN = 5            # crc(4) + etx
STANDARD_KEY = 0x35769521


class Cmd(IntEnum):
    PRINT_DATA = 0x00
    PRINT_DATA_COMPRESS = 0x01
    FIRMWARE_DATA = 0x02
    USB_UPDATE_FIRMWARE = 0x03
    GET_VERSION = 0x04
    SENT_VERSION = 0x05
    GET_MODEL = 0x06
    SENT_MODEL = 0x07
    GET_BT_MAC = 0x08
    SENT_BT_MAC = 0x09
    GET_SN = 0x0A
    SENT_SN = 0x0B
    GET_STATUS = 0x0C
    SENT_STATUS = 0x0D
    GET_VOLTAGE = 0x0E
    SENT_VOLTAGE = 0x0F
    GET_BAT_STATUS = 0x10
    SENT_BAT_STATUS = 0x11
    GET_TEMP = 0x12
    SENT_TEMP = 0x13
    SET_FACTORY_STATUS = 0x14
    GET_FACTORY_STATUS = 0x15
    SENT_FACTORY_STATUS = 0x16
    SENT_BT_STATUS = 0x17
    SET_CRC_KEY = 0x18
    SET_HEAT_DENSITY = 0x19
    FEED_LINE = 0x1A
    PRINT_TEST_PAGE = 0x1B
    GET_HEAT_DENSITY = 0x1C
    SENT_HEAT_DENSITY = 0x1D
    SET_POWER_DOWN_TIME = 0x1E
    GET_POWER_DOWN_TIME = 0x1F
    SENT_POWER_DOWN_TIME = 0x20
    FEED_TO_HEAD_LINE = 0x21
    PRINT_DEFAULT_PARA = 0x22
    GET_BOARD_VERSION = 0x23
    SENT_BOARD_VERSION = 0x24
    GET_HW_INFO = 0x25
    SENT_HW_INFO = 0x26
    SET_MAX_GAP_LENGTH = 0x27
    GET_MAX_GAP_LENGTH = 0x28
    SENT_MAX_GAP_LENGTH = 0x29
    GET_GAP_LENGTH = 0x2A
    SENT_GAP_LENGTH = 0x2B
    SET_PAPER_TYPE = 0x2C
    GET_COUNTRY_NAME = 0x2D
    SENT_COUNTRY_NAME = 0x2E
    DISCONNECT_BT = 0x2F
    GET_DEV_NAME = 0x30
    SENT_DEV_NAME = 0x31


def crc32(payload: bytes, seed: int) -> int:
    return zlib.crc32(payload, seed) & 0xFFFFFFFF


@dataclass
class Frame:
    cmd: int
    index: int = 0
    payload: bytes = b""

    def encode(self, session_key: int) -> bytes:
        return (
            bytes((STX, self.cmd & 0xFF, self.index & 0xFF))
            + struct.pack("<H", len(self.payload))
            + self.payload
            + struct.pack("<I", crc32(self.payload, session_key))
            + bytes((ETX,))
        )

    def __str__(self) -> str:  # pragma: no cover - 调试用
        return f"Frame(cmd=0x{self.cmd:02X}, index=0x{self.index:02X}, len={len(self.payload)})"


def build(cmd: Cmd | int, payload: bytes = b"", index: int = 0,
          session_key: int = STANDARD_KEY) -> bytes:
    return Frame(int(cmd), index, payload).encode(session_key)


def handshake_bytes(new_key: int) -> bytes:
    payload = struct.pack("<I", (new_key ^ STANDARD_KEY) & 0xFFFFFFFF)
    return build(Cmd.SET_CRC_KEY, payload, session_key=STANDARD_KEY)


# gen2 固件（新 P1/P2，如 BLE 名 Paperang_P1）使用的固定握手包：
# payload = LE32(0x35769521)，CRC 以种子 0 计算；此后会话种子保持 0
GEN2_HANDSHAKE = bytes.fromhex("0218000400219576351cdf442103")


def is_ack(frame: Frame, of_cmd: Cmd | int) -> bool:
    """设备对指令的即时应答：cmd 同值、payload 为单字节 0。"""
    return frame.cmd == int(of_cmd) and frame.payload == b"\x00"


@dataclass
class FrameParser:
    """流式解析器：喂入任意分块的字节流，吐出完整 Frame。

    CRC 校验按候选种子列表逐个尝试（处理握手 ACK 用新/旧 key 的二义性）；
    全部失败时记警告并丢弃该帧，从下一个 STX 重新同步。
    """

    seeds: list[int] = field(default_factory=lambda: [STANDARD_KEY])
    _buf: bytearray = field(default_factory=bytearray, repr=False)

    def feed(self, data: bytes) -> list[Frame]:
        self._buf.extend(data)
        frames: list[Frame] = []
        while True:
            frame, consumed = self._try_parse_one()
            if frame is not None:
                frames.append(frame)
            if consumed <= 0:
                break
            del self._buf[:consumed]
        return frames

    def _try_parse_one(self) -> tuple[Frame | None, int]:
        buf = self._buf
        start = 0
        while True:
            start = buf.find(bytes((STX,)), start)
            if start < 0:
                # 无帧头：清掉全部（保留末尾 1 字节以防 STX 被拆开）
                return None, max(0, len(buf) - 1)
            if len(buf) - start < HEADER_LEN:
                return None, start  # 帧头不完整，丢弃前面的噪声
            cmd, index = buf[start + 1], buf[start + 2]
            (plen,) = struct.unpack_from("<H", buf, start + 3)
            total = HEADER_LEN + plen + TAIL_LEN
            if len(buf) - start < total:
                return None, start
            payload = bytes(buf[start + HEADER_LEN:start + HEADER_LEN + plen])
            (crc,) = struct.unpack_from("<I", buf, start + HEADER_LEN + plen)
            if buf[start + total - 1] != ETX or crc not in (crc32(payload, s) for s in self.seeds):
                log.debug("帧校验失败，跳过 1 字节重新同步: cmd=0x%02X", cmd)
                return None, start + 1
            return Frame(cmd, index, payload), start + total
