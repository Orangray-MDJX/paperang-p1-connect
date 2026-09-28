"""USB bulk 传输（pyusb + libusb1 + WinUSB）。

P1 的 USB 为厂商私有 bulk 接口（非 HID/CDC）：
- VID:PID = 0x4348:0x5584（WCH 分配的打印适配线 ID）
- 配置 1 / 接口 0；OUT 端点 0x02，IN 端点 0x81
- Windows 默认将其绑给 usbprint.sys，需先用 Zadig 换成 WinUSB 驱动
  （WinUSB 为微软签名驱动，Secure Boot 下也可用）。
"""

from __future__ import annotations

import asyncio
import logging
import threading

from .transport import Transport

log = logging.getLogger(__name__)

READ_SIZE = 512
READ_TIMEOUT_MS = 500

ZADIG_HINT = (
    "USB 通道不可用：请确认打印机已开机并插入 USB，且已用 Zadig 将 "
    "USB 设备 (VID 4348 / PID 5584) 的驱动替换为 WinUSB（详见 installer/README-USB.md）"
)


def _load_libusb_backend():
    try:
        import libusb_package
        import usb.backend.libusb1 as libusb1_backend
        backend = libusb1_backend.get_backend(find_library=libusb_package.find_library)
        if backend is None:
            raise RuntimeError("libusb_package 未能定位 libusb1.dll")
        return backend
    except ImportError:
        import usb.backend.libusb1 as libusb1_backend
        return libusb1_backend.get_backend()
    except Exception as e:  # noqa: BLE001
        raise ConnectionError(
            f"libusb 后端加载失败（缺少 libusb1.dll？pip install libusb-package）: {e}") from e


def _find_device(vid: int, pid: int):
    import usb.core
    backend = _load_libusb_backend()
    return usb.core.find(idVendor=vid, idProduct=pid, backend=backend)


def probe_usb(vid: int = 0x4348, pid: int = 0x5584) -> bool:
    """同步探测设备是否可被 libusb 打开（用于诊断）。"""
    return _find_device(vid, pid) is not None


class UsbTransport(Transport):
    name = "usb"
    max_payload = 1008  # 21 行 × 48B，sharperang 实证值

    def __init__(self, vid: int, pid: int) -> None:
        super().__init__()
        self._vid, self._pid = vid, pid
        self._dev = None
        self._ep_out = None
        self._ep_in = None
        self._reader: threading.Thread | None = None
        self._closing = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_open(self) -> bool:
        return self._dev is not None and not self._closing.is_set()

    async def open(self) -> None:
        self._loop = asyncio.get_running_loop()
        dev = await asyncio.to_thread(self._open_sync)
        self._dev = dev
        self._closing.clear()
        self._reader = threading.Thread(
            target=self._read_loop, name="paperang-usb-reader", daemon=True)
        self._reader.start()
        log.info("USB 已打开 0x%04X:0x%04X", self._vid, self._pid)

    def _open_sync(self):
        import usb.core
        import usb.util
        try:
            dev = _find_device(self._vid, self._pid)
            if dev is None:
                raise ConnectionError(ZADIG_HINT)
            dev.set_configuration()
            cfg = dev.get_active_configuration()
        except ConnectionError:
            raise
        except Exception as e:  # noqa: BLE001 - libusb 各类错误都指向驱动问题
            raise ConnectionError(f"{e}。{ZADIG_HINT}") from e
        intf = cfg[(0, 0)]
        intf = cfg[(0, 0)]
        self._ep_out = usb.util.find_descriptor(
            intf, custom_match=lambda e: usb.util.endpoint_direction(
                e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
        self._ep_in = usb.util.find_descriptor(
            intf, custom_match=lambda e: usb.util.endpoint_direction(
                e.bEndpointAddress) == usb.util.ENDPOINT_IN)
        if self._ep_out is None or self._ep_in is None:
            raise ConnectionError(
                f"USB 端点不完整: out={self._ep_out} in={self._ep_in}")
        return dev

    def _read_loop(self) -> None:
        import usb.core
        while not self._closing.is_set():
            try:
                data = self._ep_in.read(READ_SIZE, READ_TIMEOUT_MS)
            except usb.core.USBError as e:
                # 超时是常态；其他错误视为断开
                if "timeout" not in str(e).lower() and e.errno != -7:
                    log.warning("USB 读取错误: %s", e)
                    self._emit_disconnect()
                    return
                continue
            except Exception:
                log.exception("USB 读取线程异常")
                self._emit_disconnect()
                return
            if data and self.on_bytes and self._loop:
                data_bytes = bytes(data)
                self._loop.call_soon_threadsafe(self._safe_emit, data_bytes)

    def _safe_emit(self, data: bytes) -> None:
        if self.on_bytes:
            try:
                self.on_bytes(data)
            except Exception:
                log.exception("USB on_bytes 回调异常")

    def _emit_disconnect(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._safe_disconnect)

    def _safe_disconnect(self) -> None:
        if self.on_disconnected:
            try:
                self.on_disconnected()
            except Exception:
                log.exception("on_disconnected 回调异常")

    async def write(self, data: bytes) -> None:
        if not self.is_open:
            raise ConnectionError("USB 未连接")
        import usb.core
        try:
            await asyncio.to_thread(self._ep_out.write, data, READ_TIMEOUT_MS)
        except usb.core.USBError as e:
            raise ConnectionError(f"USB 写入失败: {e}") from e

    async def close(self) -> None:
        self._closing.set()
        if self._reader and self._reader.is_alive():
            self._reader.join(timeout=READ_TIMEOUT_MS / 500 + 0.5)
        if self._dev is not None:
            try:
                import usb.util
                await asyncio.to_thread(usb.util.dispose_resources, self._dev)
            except Exception:
                log.exception("USB 释放资源出错")
        self._dev = None
