"""A5 framing verified against the P1 01.03.18 USB capture and Android oracle.

The third payload byte is message type (1=request/push, 2=response), NOT
a transaction counter. Commands must be serialized; a timeout poisons the
session because a late response cannot be distinguished from a new request.
"""
from dataclasses import dataclass
import struct
import zlib

SEED = 0x35769521
MAX_FRAME = 65535


def tlv(key: int, value: bytes) -> bytes:
    return bytes([key]) + struct.pack('<H', len(value)) + value


def parse_tlv(data: bytes) -> dict[int, bytes]:
    result = {}
    while data:
        if len(data) < 3:
            raise ValueError('truncated TLV header')
        key, size = data[0], struct.unpack_from('<H', data, 1)[0]
        if size > len(data) - 3 or key in result:
            raise ValueError('invalid/duplicate TLV')
        result[key] = data[3:3 + size]
        data = data[3 + size:]
    return result


def build(command: int, content: bytes = b'', message_type: int = 1) -> bytes:
    payload = struct.pack('>H', command) + bytes([message_type]) + struct.pack('<H', len(content)) + content
    if len(payload) > MAX_FRAME:
        raise ValueError('A5 payload too large')
    return b'\xa5\x01' + struct.pack('<H', len(payload)) + payload + struct.pack('<I', zlib.crc32(payload, SEED) & 0xffffffff) + b'\x5a'


def bitmap_content(rows: bytes, order: int, row_bytes=48, offset=0) -> bytes:
    if not rows or len(rows) % row_bytes or not 1 <= order <= 65535:
        raise ValueError('invalid A5 bitmap chunk')
    inner = struct.pack('<BHHBH', 1, row_bytes, offset, 0, len(rows)) + rows
    return struct.pack('<HH', order, len(inner)) + inner


@dataclass(frozen=True)
class Frame:
    command: int
    message_type: int
    content: bytes
    sync: int = 1


class Parser:
    def __init__(self):
        self.buffer = bytearray()
        self.bad_frames = 0

    def feed(self, data: bytes) -> list[Frame]:
        self.buffer.extend(data)
        frames = []
        while len(self.buffer) >= 4:
            if self.buffer[0] != 0xa5 or self.buffer[1] not in (0, 1):
                del self.buffer[0]
                continue
            size = struct.unpack_from('<H', self.buffer, 2)[0]
            if size < 5:
                self.bad_frames += 1
                del self.buffer[0]
                continue
            total = size + 9
            if len(self.buffer) < total:
                break
            payload = bytes(self.buffer[4:4 + size])
            crc = struct.unpack_from('<I', self.buffer, 4 + size)[0]
            inner = struct.unpack_from('<H', payload, 3)[0]
            if self.buffer[total - 1] != 0x5a or crc != (zlib.crc32(payload, SEED) & 0xffffffff) or inner != size - 5:
                self.bad_frames += 1
                del self.buffer[0]
                continue
            frames.append(Frame(int.from_bytes(payload[:2], 'big'), payload[2], payload[5:], self.buffer[1]))
            del self.buffer[:total]
        return frames
