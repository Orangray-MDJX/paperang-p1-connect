"""Paperang 设备会话：握手、查询、打印。

生命周期::

    dev = PaperangDevice(transport, cfg)
    await dev.connect()          # 建链 + CRC 会话握手
    await dev.get_battery()
    await dev.print_rows(blob)   # blob = 48B/行 的 1-bit 位图，MSB 在前，1=黑
    await dev.close()
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time

from . import LINE_BYTES
from .config import Config
from .protocol import (
    Cmd, Frame, FrameParser, GEN2_HANDSHAKE, STANDARD_KEY, build, handshake_bytes, is_ack,
)
from .transport import Transport

log = logging.getLogger(__name__)

ACK_TIMEOUT_S = 2.0


class DeviceError(RuntimeError):
    pass


class _Waiter:
    __slots__ = ("cmd", "future", "want_ack")

    def __init__(self, cmd: int, want_ack: bool, future: asyncio.Future):
        self.cmd = cmd
        self.want_ack = want_ack
        self.future = future


class PaperangDevice:
    def __init__(self, transport: Transport, cfg: Config) -> None:
        self.transport = transport
        self.cfg = cfg
        self.session_key = STANDARD_KEY
        self.parser = FrameParser(seeds=[STANDARD_KEY])
        self._waiters: list[_Waiter] = []
        self._closed = False
        # 最近一次查询到的状态
        self.battery: int | None = None
        self.sn: str | None = None
        self.power_down_time: int | None = None
        self.connected_at: float | None = None

        transport.on_bytes = self._on_bytes
        transport.on_disconnected = self._handle_disconnected

    # ---------------------------------------------------------------- 连接

    async def connect(self) -> None:
        await self.transport.open()
        await self._handshake()
        self.connected_at = time.monotonic()
        log.info("设备会话建立 (%s)", self.transport.name)

    async def close(self) -> None:
        self._closed = True
        for w in self._waiters:
            if not w.future.done():
                w.future.cancel()
        self._waiters.clear()
        try:
            await self.transport.close()
        except Exception:
            log.exception("关闭传输层出错")

    async def _handshake(self) -> None:
        mode = getattr(self.cfg, "handshake_mode", "gen2")
        if mode == "gen1":
            key = secrets.randbits(32)
            ack = self._register(Cmd.SET_CRC_KEY, want_ack=True)
            # ACK 可能用新旧任一种子算 CRC，两种都接受
            self.parser.seeds = [STANDARD_KEY, key]
            await self.transport.write(handshake_bytes(key))
            # 发出后立即切换本端发送种子（设备收到即切换）
            self.session_key = key
            await asyncio.wait_for(ack, ACK_TIMEOUT_S)
            log.info("CRC 会话握手完成 key=0x%08X", key)
        elif mode == "gen2":
            # gen2：固定 magic 包（种子 0 计算），此后全程种子 0；不等 ACK
            await self.transport.write(GEN2_HANDSHAKE)
            self.session_key = 0
            self.parser.seeds = [0, STANDARD_KEY]
            await asyncio.sleep(0.2)
            log.info("gen2 握手包已发送（种子 0 会话）")
        else:  # none：不做握手，直接种子 0
            self.session_key = 0
            self.parser.seeds = [0, STANDARD_KEY]

    # ---------------------------------------------------------------- 命令

    def _register(self, cmd: Cmd, want_ack: bool) -> asyncio.Future:
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._waiters.append(_Waiter(int(cmd), want_ack, fut))
        return fut

    async def command(self, cmd: Cmd, payload: bytes = b"",
                      expect_reply: bool = False,
                      timeout: float = ACK_TIMEOUT_S) -> Frame | None:
        """发指令 → 等 ACK（可选再等 SENT_* 应答帧）。

        wait_ack_cmd=False（gen2 固件）时不等 ACK 直接返回；
        expect_reply 时仍短暂等待应答帧，有则返回、无则 None。
        """
        reply: asyncio.Future | None = None
        if self.cfg.wait_ack_cmd:
            ack = self._register(cmd, want_ack=True)
            if expect_reply:
                reply = self._register(Cmd(int(cmd) + 1), want_ack=False)
            await self.transport.write(build(cmd, payload, session_key=self.session_key))
            try:
                await asyncio.wait_for(ack, timeout)
            except asyncio.TimeoutError:
                self._drop_waiter(reply)
                raise DeviceError(f"指令 0x{int(cmd):02X} 等待 ACK 超时") from None
        else:
            if expect_reply:
                reply = self._register(Cmd(int(cmd) + 1), want_ack=False)
            await self.transport.write(build(cmd, payload, session_key=self.session_key))
            await asyncio.sleep(0.02)

        if reply is not None:
            try:
                return await asyncio.wait_for(reply, timeout)
            except asyncio.TimeoutError:
                return None
        return None

    def _drop_waiter(self, fut: asyncio.Future | None) -> None:
        if fut is None:
            return
        self._waiters = [w for w in self._waiters if w.future is not fut]

    # ---------------------------------------------------------------- 查询

    async def get_battery(self) -> int:
        f = await self.command(Cmd.GET_BAT_STATUS, b"\x01", expect_reply=True)
        self.battery = f.payload[0] if f and f.payload else None
        return self.battery

    async def get_sn(self) -> str:
        f = await self.command(Cmd.GET_SN, b"\x01", expect_reply=True)
        self.sn = f.payload.decode("ascii", "replace").strip("\x00") if f else None
        return self.sn

    async def get_power_down_time(self) -> int:
        f = await self.command(Cmd.GET_POWER_DOWN_TIME, b"\x01", expect_reply=True)
        if f and len(f.payload) >= 2:
            self.power_down_time = int.from_bytes(f.payload[:2], "little")
        return self.power_down_time

    # ---------------------------------------------------------------- 设置

    async def set_density(self, value: int | None = None) -> None:
        v = self.cfg.density if value is None else value
        await self.command(Cmd.SET_HEAT_DENSITY, bytes([max(0, min(100, v))]))

    async def feed(self, lines: int) -> None:
        await self.command(Cmd.FEED_LINE, int(max(0, lines)).to_bytes(2, "little"))

    async def set_power_down_time(self, seconds: int) -> None:
        """设 0 禁用自动关机（保活）。单位为秒（推断值，真机可验证）。"""
        await self.command(Cmd.SET_POWER_DOWN_TIME,
                           int(max(0, seconds)).to_bytes(2, "little"))

    async def keepalive_setup(self) -> None:
        if self.cfg.disable_auto_poweroff:
            try:
                await self.set_power_down_time(0)
            except DeviceError:
                log.warning("禁用自动关机失败，继续")
        try:
            await self.get_battery()
        except DeviceError:
            pass

    # ---------------------------------------------------------------- 打印

    async def print_rows(self, blob: bytes, density: int | None = None,
                         pre_feed: int | None = None,
                         post_feed: int | None = None) -> None:
        """发送 1-bit 位图（每行 LINE_BYTES 字节）并打印。"""
        if len(blob) % LINE_BYTES:
            raise DeviceError(f"位图长度 {len(blob)} 不是 {LINE_BYTES} 的整倍数")
        await self.set_density(density)
        await self.feed(self.cfg.pre_feed_lines if pre_feed is None else pre_feed)
        await self.command(Cmd.SET_PAPER_TYPE, b"\x00")

        chunk_bytes = (self.transport.max_payload // LINE_BYTES) * LINE_BYTES
        delay = getattr(self.cfg, f"chunk_delay_ms_{self.transport.name}", 60.0) / 1000.0
        total = (len(blob) + chunk_bytes - 1) // chunk_bytes
        for i, off in enumerate(range(0, len(blob), chunk_bytes)):
            await self.transport.write(
                build(Cmd.PRINT_DATA, blob[off:off + chunk_bytes],
                      index=i & 0xFF, session_key=self.session_key))
            if self.cfg.wait_ack:
                await asyncio.sleep(0)  # 占位：默认不等 ACK，与官方行为一致
            if i < total - 1:
                await asyncio.sleep(delay)

        await self.feed(self.cfg.post_feed_lines if post_feed is None else post_feed)

    async def print_png(self, png: bytes, density: int | None = None) -> None:
        """PNG（通常已是 1-bit）→ 行数据 → 打印。与 VendorPrinter 接口对齐。"""
        import io
        from PIL import Image

        from .render import prepare, rows_from_image
        img = Image.open(io.BytesIO(png))
        rows = rows_from_image(prepare(img, dither="threshold",
                                       threshold=self.cfg.threshold))
        await self.print_rows(rows, density=density)

    # ---------------------------------------------------------------- 接收

    def _on_bytes(self, data: bytes) -> None:
        try:
            for frame in self.parser.feed(data):
                self._dispatch(frame)
        except Exception:
            log.exception("解析设备数据出错")

    def _dispatch(self, frame: Frame) -> None:
        for i, w in enumerate(list(self._waiters)):
            if w.future.done():
                self._waiters.remove(w)
                continue
            if w.cmd == frame.cmd and (
                    (w.want_ack and is_ack(frame, frame.cmd)) or not w.want_ack):
                w.future.set_result(frame)
                self._waiters.remove(w)
                return
        log.debug("未匹配的应答帧: %s payload=%s", frame, frame.payload.hex())

    def _handle_disconnected(self) -> None:
        for w in self._waiters:
            if not w.future.done():
                w.future.set_exception(DeviceError("连接已断开"))
        self._waiters.clear()
