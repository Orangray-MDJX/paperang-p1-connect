import asyncio
import struct
import pytest
from paperang_p1.protocol_a5 import Parser, build, bitmap_content, parse_tlv
from paperang_p1.device_a5 import A5Device
from paperang_p1.config import Config
from paperang_p1.device import DeviceError


def parse_rfcomm(l2: bytes):
    """RFCOMM 帧 -> (dlci, ftype, credit, user)。user 不含 credit/FCS。

    长度字段不含可选 credit 字节与 FCS；若按长度切片前先去掉 credit，
    会静默丢掉应用层最后一字节（A5 的帧尾 0x5A）——本测试即验证这一点。
    """
    if len(l2) < 4:
        return None, None, None, None
    addr, ctrl, lb = l2[0], l2[1], l2[2]
    if lb & 1:
        length, off = lb >> 1, 3
    else:
        length, off = (lb >> 1) | (l2[3] << 7), 4
    dlci = addr >> 2
    ftype = ctrl & 0xEF
    credit = None
    user = None
    if ftype == 0xEF and dlci:
        if (ctrl >> 4) & 1:
            if len(l2) <= off:
                raise ValueError('truncated RFCOMM credit')
            credit = l2[off]
            off += 1
        if len(l2) < off + length + 1:
            raise ValueError('truncated RFCOMM information/FCS')
        user = bytes(l2[off:off + length])
    return dlci, ftype, credit, user


VERSION = bytes.fromhex('a50110000115020b0001080030312e30332e3138b4204a405a')
ACK = bytes.fromhex('a5010800051b020300010000ac4a277f5a')


def test_real_p1_media_frames_and_sensor_polarity():
    frames = [
        ('a5010900050c02040001010000b945a4675a', 0x050c, b'\x00'),
        ('a5010900050d0204000101000027450eab5a', 0x050d, b'\x00'),
        ('a5010a000504020500010200c800e41be16c5a', 0x0504, b'\xc8\x00'),
        ('a5010d000502020800010500010200390033677db05a', 0x0502, b'\x01\x02\x00\x39\x00'),
    ]
    for raw, cmd, value in frames:
        frame = Parser().feed(bytes.fromhex(raw))[0]
        assert frame.command == cmd and parse_tlv(frame.content)[1] == value
    async def run():
        device = A5Device(FakeTransport(), Config())
        device.media_supported = True
        async def query(cmd): return b'\x01' if cmd == 0x050c else b'\x00'
        device.query = query
        assert await device.get_media_status() == {'lid_closed': True, 'paper_present': False}
    asyncio.run(run())


def test_media_query_never_interrupts_bitmap_session_and_loss_prevents_feed():
    async def run():
        device = A5Device(FakeTransport(), Config())
        device.media_supported = True
        commands = []
        async def ack(cmd, *args, **kwargs): commands.append(cmd)
        async def media():
            assert commands[-1] == 0x051a
            return {'lid_closed': True, 'paper_present': False}
        device.ack = ack; device.get_media_status = media
        with pytest.raises(DeviceError, match='打印结束后'):
            await device.print_rows(b'\x00' * 48 * 120)
        assert commands.count(0x051b) == 6
        assert 0x051a in commands and 0x0516 not in commands
    asyncio.run(run())


def test_real_frames_every_fragment_boundary():
    for split in range(len(VERSION) + 1):
        p = Parser(); frames = p.feed(VERSION[:split]) + p.feed(VERSION[split:] + ACK)
        assert [f.command for f in frames] == [0x115, 0x51b]
        assert frames[0].message_type == 2
        assert parse_tlv(frames[0].content)[1] == b'01.03.18'
        assert parse_tlv(frames[1].content) == {1: b''}


def test_crc_corruption_noise_and_inner_length():
    bad = bytearray(VERSION); bad[12] ^= 1
    p = Parser(); out = p.feed(b'noise' + bad + ACK)
    assert len(out) == 1 and out[0].command == 0x51b
    assert p.bad_frames > 0
    with pytest.raises(ValueError): parse_tlv(b'\x01\x04\x00x')


def test_print_chunk_matches_real_capture_header():
    content = bitmap_content(b'\xff' * 960, 1)
    assert content[:12].hex() == '0100c803013000000000c003'
    assert len(content) == 972
    frame = Parser().feed(build(0x51b, content))[0]
    assert frame.content == content


def test_rfcomm_credit_does_not_truncate_a5_tail():
    # DLCI2, UIH+P/F, credit 7, info length14, FCS separate.
    query = build(0x115)
    packet = bytes([2 << 2 | 3, 0xff, len(query) << 1 | 1, 7]) + query + b'\x99'
    dlci, ft, credit, user = parse_rfcomm(packet)
    assert (dlci, ft, credit, user) == (2, 0xef, 7, query)
    with pytest.raises(ValueError): parse_rfcomm(packet[:-2])


class FakeTransport:
    name = 'usb'
    is_open = True
    writes = 0
    async def write(self, data): self.writes += 1
    async def close(self): self.is_open = False


def test_unrelated_response_does_not_satisfy_waiter_timeout_closes_session():
    async def run():
        t = FakeTransport(); d = A5Device(t, Config()); d.state = 'ready'
        task = asyncio.create_task(d.command(0x115, timeout=.02))
        await asyncio.sleep(0)
        d._on_bytes(ACK)
        d._on_bytes(build(0x115))  # request/push type1 is not a response
        with pytest.raises(DeviceError): await task
        assert not t.is_open and d.state == 'fault'
        with pytest.raises(DeviceError): await d.command(0x115)
        assert t.writes == 1
    asyncio.run(run())


def test_cancelled_command_closes_session_before_late_reply():
    async def run():
        t = FakeTransport(); d = A5Device(t, Config()); d.state = 'ready'
        task = asyncio.create_task(d.command(0x115))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        d._on_bytes(VERSION)
        assert not t.is_open and d.state == 'fault' and d._pending is None
        with pytest.raises(DeviceError): await d.command(0x115)
    asyncio.run(run())
