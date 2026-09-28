"""经典蓝牙 SPP (RFCOMM) 传输 —— WinRT StreamSocket，免 COM 口。

新固件 Paperang（gen2 家族，BLE 广播名 Paperang_P1/P2）的数据通道是经典蓝牙
SPP（服务 UUID 00001101），需要先在 Windows 中配对设备（一次即可）。
BLE FF00 服务只作为辅助通道（连接事件/状态上报），不承载数据。
"""

from __future__ import annotations

import asyncio
import logging

from .transport import Transport

log = logging.getLogger(__name__)

SPP_UUID = "00001101-0000-1000-8000-00805f9b34fb"
FEE7_UUID = "0000fee7-0000-1000-8000-00805f9b34fb"

# 连接后蓝牙栈/固件需要短暂就绪时间（实测立即写首帧易被断链）
_SETTLE_S = 2.0
_READ_CHUNK = 1024


def mac_to_u64(mac: str) -> int:
    return int(mac.replace(":", "").replace("-", ""), 16)


class SppTransport(Transport):
    name = "spp"
    max_payload = 1008  # 与 USB 相同量级；SPP 链路可靠，按 21 行分包

    def __init__(self, address: str) -> None:
        super().__init__()
        self._address = address.replace("-", ":").upper()
        self._sock = None
        self._writer = None
        self._reader = None
        self._reader_task: asyncio.Task | None = None
        self._closing = False

    @property
    def is_open(self) -> bool:
        return self._sock is not None and not self._closing

    async def open(self) -> None:
        import winrt.windows.networking  # noqa: F401 - HostName 类注册
        from winrt.windows.devices.bluetooth import BluetoothDevice
        from winrt.windows.networking.sockets import StreamSocket
        from winrt.windows.storage.streams import DataReader, DataWriter

        bt = await BluetoothDevice.from_bluetooth_address_async(
            mac_to_u64(self._address))
        if bt is None:
            raise ConnectionError(
                f"未发现经典蓝牙设备 {self._address}（请确认打印机已开机）")
        svc = None
        try:
            count = bt.rfcomm_services.size
        except Exception:
            count = 0
        for i in range(count):
            s = bt.rfcomm_services.get_at(i)
            if str(s.service_id.uuid).lower() in (SPP_UUID, FEE7_UUID):
                svc = s
                break
            if svc is None:
                svc = s  # 兜底取第一个
        if svc is None:
            raise ConnectionError(
                f"设备 {self._address} 未提供 SPP 服务（请先在 Windows 设置中配对打印机）")

        sock = StreamSocket()
        await sock.connect_async(svc.connection_host_name, svc.connection_service_name)
        self._sock = sock
        self._writer = DataWriter(sock.output_stream)
        self._reader = DataReader(sock.input_stream)
        self._closing = False
        log.info("SPP 已连接 %s (svc=%s)", self._address, svc.service_id.uuid)
        await asyncio.sleep(_SETTLE_S)
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        from winrt.windows.storage.streams import DataReader  # noqa: F401
        while not self._closing:
            try:
                n = await self._reader.load_async(_READ_CHUNK)
            except Exception as e:
                if not self._closing:
                    log.warning("SPP 读取结束: %r", e)
                    self._fire_disconnected()
                return
            if not n:
                continue
            data = bytes(bytearray(self._reader.read_bytes(n)))
            if data and self.on_bytes:
                try:
                    self.on_bytes(data)
                except Exception:
                    log.exception("SPP on_bytes 回调异常")

    async def write(self, data: bytes) -> None:
        if not self.is_open:
            raise ConnectionError("SPP 未连接")
        try:
            self._writer.write_bytes(data)
            await self._writer.store_async()
        except Exception as e:
            raise ConnectionError(f"SPP 写入失败: {e}") from e

    async def close(self) -> None:
        self._closing = True
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                log.exception("SPP 关闭出错")
        self._sock = None

    def _fire_disconnected(self) -> None:
        log.warning("SPP 连接已断开: %s", self._address)
        if self.on_disconnected:
            try:
                self.on_disconnected()
            except Exception:
                log.exception("on_disconnected 回调异常")


async def list_paired_spp() -> list[dict]:
    """Enumerate paired classic devices without WinRT overload dependencies."""
    return await asyncio.to_thread(_paired_devices)


def _paired_devices():
    import ctypes as C
    from ctypes import wintypes as W
    class Search(C.Structure):
        _fields_ = [('size', W.DWORD), ('authenticated', W.BOOL),
                    ('remembered', W.BOOL), ('unknown', W.BOOL),
                    ('connected', W.BOOL), ('inquiry', W.BOOL),
                    ('timeout', C.c_ubyte), ('radio', W.HANDLE)]
    class Device(C.Structure):
        _fields_ = [('size', W.DWORD), ('address', C.c_ulonglong),
                    ('device_class', W.DWORD), ('connected', W.BOOL),
                    ('remembered', W.BOOL), ('authenticated', W.BOOL),
                    ('seen', W.WORD * 8), ('used', W.WORD * 8),
                    ('name', W.WCHAR * 248)]
    lib = C.WinDLL('BluetoothAPIs', use_last_error=True)
    lib.BluetoothFindFirstDevice.argtypes = [C.POINTER(Search), C.POINTER(Device)]
    lib.BluetoothFindFirstDevice.restype = W.HANDLE
    lib.BluetoothFindNextDevice.argtypes = [W.HANDLE, C.POINTER(Device)]
    lib.BluetoothFindDeviceClose.argtypes = [W.HANDLE]
    search = Search(); search.size = C.sizeof(search)
    search.authenticated = search.remembered = search.connected = True
    device = Device(); device.size = C.sizeof(device)
    handle = lib.BluetoothFindFirstDevice(C.byref(search), C.byref(device))
    if not handle:
        error = C.get_last_error()
        if error == 259: return []
        raise C.WinError(error)
    found = []
    try:
        while True:
            address = ':'.join(f'{device.address:012X}'[i:i+2] for i in range(0,12,2))
            found.append({'address': address, 'name': device.name})
            if not lib.BluetoothFindNextDevice(handle, C.byref(device)): break
    finally:
        lib.BluetoothFindDeviceClose(handle)
    return found
