"""P1 A5 session. Commands validated against the CRC-correct phone capture."""
import asyncio
import io
import time
from PIL import Image

from .device import DeviceError
from .protocol_a5 import Parser, build, bitmap_content, parse_tlv
from .render import prepare, rows_from_image


class A5Device:
    protocol = 'a5'

    def __init__(self, transport, cfg):
        self.transport, self.cfg = transport, cfg
        self.parser = Parser()
        self.state = 'disconnected'
        self.battery = self.sn = self.power_down_time = self.connected_at = None
        self.version = None
        self.last_error = None
        self.max_length = 1024
        self.media_supported = False
        self.lid_closed = self.paper_present = self.dpi = self.paper_width_mm = None
        self.media_checked_at = None
        self._command_lock = asyncio.Lock()
        self._pending = None
        transport.on_bytes = self._on_bytes
        transport.on_disconnected = self._disconnected

    def _on_bytes(self, data):
        for frame in self.parser.feed(data):
            p = self._pending
            if p and frame.message_type == 2 and frame.command == p[0] and not p[1].done():
                p[1].set_result(frame)

    def _disconnected(self):
        self.state = 'fault'
        self.last_error = getattr(self.transport, 'last_error', None) or 'A5 连接已断开'
        if self._pending and not self._pending[1].done():
            self._pending[1].set_exception(DeviceError('A5 连接已断开'))

    async def connect(self):
        self.state = 'connecting'
        self.last_error = None
        try:
            await self.transport.open()
            self.state = 'initializing'
            if self.transport.name == 'usb':
                await self.transport.write(bytes.fromhex('badcfe00c00300000a00'))
                await asyncio.sleep(.25)
            self.version = (await self.query(0x0115)).decode('ascii').rstrip('\x00')
            self.sn = (await self.query(0x0102)).decode('ascii').rstrip('\x00')
            self.max_length = int.from_bytes(await self.query(0x0114), 'little')
            if not self.version or not self.sn or self.max_length < 62:
                raise DeviceError('A5 设备身份/包长无效')
            # This contract is verified on the local P1 firmware, not all A5 models.
            self.media_supported = self.sn.startswith('P1') and self.version == '01.03.18'
            if self.media_supported:
                raw_dpi = await self.query(0x0504)
                widths = parse_tlv(await self.query(0x0502))
                if len(raw_dpi) != 2 or len(widths.get(1, b'')) != 2:
                    raise DeviceError('A5 打印规格返回格式无效')
                self.dpi = int.from_bytes(raw_dpi, 'little')
                self.paper_width_mm = int.from_bytes(widths[1], 'little')
                if not 50 <= self.dpi <= 1200 or not 20 <= self.paper_width_mm <= 300:
                    raise DeviceError('A5 打印规格超出有效范围')
                await self.get_media_status()
            self.state = 'ready'; self.connected_at = time.monotonic()
        except BaseException:
            self.state = 'fault'
            await self.transport.close()
            raise

    async def close(self):
        self._disconnected()
        await self.transport.close()
        self.state = 'disconnected'

    async def command(self, cmd, content=b'', timeout=5):
        async with self._command_lock:
            if self.state in ('fault', 'disconnected'):
                raise DeviceError('A5 会话不可用，请重新连接')
            fut = asyncio.get_running_loop().create_future()
            self._pending = (cmd, fut)
            try:
                await self.transport.write(build(cmd, content))
                return await asyncio.wait_for(fut, timeout)
            except asyncio.CancelledError:
                self.state = 'fault'
                await self.transport.close()
                raise
            except (TimeoutError, OSError, ConnectionError) as e:
                self.state = 'fault'
                await self.transport.close()
                raise DeviceError(f'A5 0x{cmd:04X} 应答失败；会话已关闭，不能盲目重试: {e}') from e
            finally:
                self._pending = None
                if not fut.done(): fut.cancel()

    async def query(self, cmd):
        f = await self.command(cmd)
        values = parse_tlv(f.content)
        if 1 not in values:
            raise DeviceError(f'A5 0x{cmd:04X} 缺少返回值')
        return values[1]

    async def ack(self, cmd, content=b'', timeout=5):
        result = await self.query_content(cmd, content, timeout)
        if result not in (b'', b'\x00'):
            raise DeviceError(f'A5 0x{cmd:04X} 返回错误: {result.hex()}')

    async def query_content(self, cmd, content, timeout=5):
        f = await self.command(cmd, content, timeout)
        values = parse_tlv(f.content)
        if 1 not in values:
            raise DeviceError(f'A5 0x{cmd:04X} 缺少 ACK 字段')
        return values[1]

    async def get_battery(self):
        value = int.from_bytes(await self.query(0x010b), 'little') / 10
        if not 0 <= value <= 100:
            raise DeviceError('电量返回值超出范围')
        self.battery = value
        return value

    async def get_media_status(self):
        if not self.media_supported:
            return {}
        lid = await self.query(0x050c)
        paper = await self.query(0x050d)
        if lid not in (b'\x00', b'\x01') or paper not in (b'\x00', b'\x01'):
            raise DeviceError('A5 盖/纸状态返回格式无效')
        self.lid_closed, self.paper_present = lid == b'\x01', paper == b'\x01'
        self.media_checked_at = time.monotonic()
        return {'lid_closed': self.lid_closed, 'paper_present': self.paper_present}

    async def get_sn(self):
        self.sn = (await self.query(0x0102)).decode('ascii').rstrip('\x00')
        return self.sn

    async def get_power_down_time(self):
        self.power_down_time = int.from_bytes(await self.query(0x0109), 'little')
        return self.power_down_time

    async def set_power_down_time(self, seconds):
        if not 0 <= seconds <= 65535:
            raise ValueError('关机时间必须为 0..65535 秒')
        await self.ack(0x010a, seconds.to_bytes(2, 'little'))
        if await self.get_power_down_time() != seconds:
            raise DeviceError('设备未确认关机时间设置')

    async def keepalive_setup(self):
        await self.get_battery()
        await self.get_power_down_time()
        if self.cfg.disable_auto_poweroff:
            await self.set_power_down_time(0)

    async def selftest(self):
        await self.ack(0x0517)

    async def feed(self, lines):
        await self.ack(0x0516, int(lines).to_bytes(2, 'little'))

    async def print_png(self, png, density=None, cancel_check=None):
        img = prepare(Image.open(io.BytesIO(png)), dither='threshold', threshold=self.cfg.threshold)
        await self.print_rows(rows_from_image(img), density, cancel_check=cancel_check)

    async def print_rows(self, rows, density=None, **kwargs):
        if not rows or len(rows) % 48:
            raise DeviceError('P1 位图必须每行 48 字节')
        chunk_size = min(960, ((self.max_length - 26) // 48) * 48)
        if chunk_size < 48:
            raise DeviceError('设备包长不支持位图')
        # Capture has one byte density, paper type 0, then start/data/finish.
        level = self.cfg.density if density is None else density
        await self.ack(0x0511, bytes([max(0, min(100, level))]))
        await self.ack(0x0520, b'\x00\x00')
        await self.ack(0x0519)
        for order, off in enumerate(range(0, len(rows), chunk_size), 1):
            if kwargs.get('cancel_check') and kwargs['cancel_check']():
                raise DeviceError('用户中止图像发送，结果未知；缓冲内容仍可能出纸，不会自动重打')
            await self.ack(0x051b, bitmap_content(rows[off:off + chunk_size], order), timeout=15)
        if kwargs.get('cancel_check') and kwargs['cancel_check']():
            raise DeviceError('用户中止图像发送，结果未知；缓冲内容仍可能出纸，不会自动重打')
        await self.ack(0x051a, timeout=30)
        # P1 rejects bitmap frames when status queries interrupt start/data/end.
        # Query only after the uninterrupted print session has finished.
        if self.media_supported:
            media = await self.get_media_status()
            if not media['lid_closed'] or not media['paper_present']:
                raise DeviceError('打印结束后检测到开盖或缺纸，结果未知；不会自动重打')
        if self.cfg.post_feed_lines:
            await self.feed(self.cfg.post_feed_lines)
