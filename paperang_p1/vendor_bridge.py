# -*- coding: utf-8 -*-
"""64 位主服务侧：管理 32 位辅助进程，提供 VendorPrinter 设备抽象。

架构::

  主服务(64bit asyncio)
     │  JSON 行协议 (stdin/stdout)
     ▼
  vendor_helper.py (32bit) ──ctypes──> libprw.dll (官方协议库)
                                        │  蓝牙: SPP COM 口
                                        │  USB : usbprint 设备
                                        ▼
                                     Paperang P1
"""

from __future__ import annotations

import asyncio
import base64
import io
import itertools
import logging
import os
import sys
from pathlib import Path

from . import LINE_DOTS
from .config import Config
from .device import DeviceError

log = logging.getLogger(__name__)

_HERE = Path(__file__).parent
_HELPER = _HERE / "vendor_helper.py"

PY32_ROOTS = (
    # 官方 PC 库 libprw.dll 为 32 位，需要 32 位 Python 辅助进程加载；
    # 按常见安装布局探测，具体路径建议用配置项 vendor_py32 或环境变量指定。
    Path.home() / "AppData" / "Local" / "Programs" / "Python",
    Path("C:/"),
)


def find_py32(cfg: Config) -> str | None:
    if cfg.vendor_py32 and Path(cfg.vendor_py32).exists():
        return cfg.vendor_py32
    p = os.environ.get("PAPERANG_PY32")
    if p and Path(p).exists():
        return p
    for root in PY32_ROOTS:
        cands = sorted(root.glob("Python3*-32/python.exe"))
        if cands:
            return str(cands[-1])
    return None


class VendorBridge:
    """与 32 位辅助进程的会话。"""

    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self.on_event = None  # callable(name: str, data)

    @property
    def is_running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self, py32: str) -> None:
        if self.is_running:
            return
        from .config import APP_DIR
        APP_DIR.mkdir(parents=True, exist_ok=True)
        errlog = open(APP_DIR / "vendor_helper.log", "ab")
        self.proc = await asyncio.create_subprocess_exec(
            py32, str(_HELPER),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=errlog,
            cwd=str(_HERE.parent),
        )
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            try:
                msg = __import__("json").loads(line.decode("utf-8", "replace"))
            except Exception:
                continue
            rid = msg.get("id")
            if rid is not None and rid in self._pending:
                fut = self._pending.pop(rid)
                if "error" in msg:
                    if not fut.done():
                        fut.set_exception(DeviceError(str(msg["error"])))
                else:
                    if not fut.done():
                        fut.set_result(msg.get("resp"))
            elif "event" in msg:
                name = msg["event"]
                data = msg.get("data")
                log.info("vendor 事件: %s %s", name, data)
                if self.on_event:
                    try:
                        self.on_event(name, data)
                    except Exception:
                        log.exception("vendor 事件回调异常")
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(DeviceError("辅助进程已退出"))
        self._pending.clear()

    async def request(self, cmd: str, timeout: float = 30.0, **kw):
        import json as _json
        if not self.is_running:
            raise DeviceError("辅助进程未运行")
        rid = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        msg = _json.dumps({"id": rid, "cmd": cmd, **kw}, ensure_ascii=False)
        assert self.proc and self.proc.stdin
        self.proc.stdin.write((msg + "\n").encode("utf-8"))
        await self.proc.stdin.drain()
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            raise DeviceError(f"vendor 请求超时: {cmd}") from None

    async def stop(self) -> None:
        try:
            if self.is_running:
                await self.request("stop", timeout=5)
        except Exception:
            pass
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None


class _TransportShim:
    """让 VendorPrinter 适配 PaperangDevice 的 transport 访问面。"""

    name = "vendor"

    def __init__(self) -> None:
        self.is_open = False


class VendorPrinter:
    """与 PaperangDevice 同构的官方库打印机（连接/打印/状态走 libprw）。"""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.transport = _TransportShim()
        self.bridge = VendorBridge()
        self.battery: int | None = None
        self.sn: str | None = None
        self.connected_at: float | None = None
        self._serial: str | None = None
        self._inserted = asyncio.Event()

        def on_event(name, data):
            if name == "inserted":
                d = data or {}
                if d.get("connect_type") in (1, 2):
                    self._serial = d.get("serial") or self._serial
                    self._inserted.set()
            elif name in ("removed", "req_disconnect"):
                self._inserted.clear()
                self.transport.is_open = False

        self.bridge.on_event = on_event

    # ------------------------------------------------------------- 连接

    async def connect(self, timeout: float = 30.0) -> None:
        import time
        py32 = find_py32(self.cfg)
        if not py32:
            raise DeviceError(
                "未找到 32 位 Python（vendor 桥需要它加载 32 位 libprw.dll），"
                "可安装: winget install Python.Python.3.12 --architecture x86")
        await self.bridge.start(py32)

        # USB 插入时官方库会自动挂载并直接上报 inserted 事件（强状态，优先）
        try:
            await asyncio.wait_for(self._inserted.wait(), timeout=8)
            self.transport.is_open = True
            self.connected_at = time.monotonic()
            log.info("vendor 桥：USB 自动挂载完成")
            return
        except asyncio.TimeoutError:
            pass

        # 蓝牙路径：轮询设备列表 → 显式连接 COM 口 → 等待 inserted
        deadline = time.monotonic() + timeout
        target = None
        while time.monotonic() < deadline:
            devs = await self.bridge.request("list", timeout=10) or []
            for d in devs:
                name = (d.get("name") or "") + " " + (d.get("model") or "")
                if "paperang" in name.lower() or "miaomiaoji" in name.lower():
                    target = d
                    break
            if target:
                break
            await asyncio.sleep(1.0)
        if not target:
            raise DeviceError(
                "官方库未发现 Paperang（请确认打印机已开机且 USB 已插入，"
                "或已在 Windows 设置中配对蓝牙）")
        serial = target.get("serial") or target.get("sn") or ""
        self.sn = target.get("sn")
        log.info("vendor 桥连接 %s (%s)", target.get("name"), serial)
        await self.bridge.request("connect", serial=serial, timeout=10)
        try:
            await asyncio.wait_for(self._inserted.wait(), timeout=20)
        except asyncio.TimeoutError:
            raise DeviceError("等待官方库连接事件超时") from None
        self.transport.is_open = True
        self.connected_at = time.monotonic()

    async def close(self) -> None:
        if self._serial:
            try:
                await self.bridge.request("disconnect", serial=self._serial, timeout=5)
            except Exception:
                pass
        await self.bridge.stop()
        self.transport.is_open = False

    # ------------------------------------------------------------- 打印

    async def print_png(self, png: bytes, density: int | None = None,
                        copies: int = 1) -> None:
        if not self.transport.is_open:
            raise DeviceError("vendor 打印机未连接")
        if density is not None:
            await self.bridge.request(
                "density", value=max(0, min(100, density)), timeout=10)
        b64 = base64.b64encode(png).decode()
        await self.bridge.request("print_b64", b64=b64, copies=copies, timeout=120)

    async def print_rows(self, rows: bytes, density: int | None = None,
                         pre_feed: int | None = None,
                         post_feed: int | None = None) -> None:
        """兼容自家管线：1-bit 行数据（1=黑）→ PNG → 官方库打印。"""
        from PIL import Image
        height = len(rows) // (LINE_DOTS // 8)
        data = bytearray(height * LINE_DOTS)
        for y in range(height):
            base = y * (LINE_DOTS // 8)
            for x in range(LINE_DOTS):
                bit = (rows[base + x // 8] >> (7 - x % 8)) & 1
                data[y * LINE_DOTS + x] = 0 if bit else 255
        img = Image.frombytes("L", (LINE_DOTS, height), bytes(data))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        await self.print_png(buf.getvalue(), density=density)

    # ------------------------------------------------------------- 保活

    async def keepalive_setup(self) -> None:
        if self.cfg.disable_auto_poweroff:
            log.info("vendor 通道：自动关机策略由官方库管理（连接保持即保活）")

    async def get_battery(self) -> int | None:
        return self.battery

    async def get_sn(self) -> str | None:
        return self.sn
