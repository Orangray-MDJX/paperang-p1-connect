"""BLE GATT 传输（bleak / Windows WinRT 后端）。

P1 使用 Nordic-UART 风格的透传服务：
- Service: 49535343-FE7D-4AE5-8FA9-9FAFD205E455
- 写特征存在两个已知变体（不同批次固件），按 GATT 属性自动探测；
- 通知特征: 49535343-1E4D-4BD9-BA61-23C647249616
- 无需系统配对。
"""

from __future__ import annotations

import asyncio
import logging

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

from .transport import Transport

log = logging.getLogger(__name__)

SERVICE_UUIDS = (
    "49535343-fe7d-4ae5-8fa9-9fafd205e455",   # Nordic-UART 风格（Yrr0r 实测 P1）
    "0000ff00-0000-1000-8000-00805f9b34fb",    # FF00 profile（本机 P1 实测）
)
KNOWN_WRITE_CHARS = (
    "49535343-6daa-4d02-abf6-19569aca69fe",
    "49535343-8841-43f4-a8d4-ecbe34729bb3",
    "0000ff02-0000-1000-8000-00805f9b34fb",
)
KNOWN_NOTIFY_CHARS = (
    "49535343-1e4d-4bd9-ba61-23c647249616",
    "0000ff01-0000-1000-8000-00805f9b34fb",
    "0000ff03-0000-1000-8000-00805f9b34fb",
)

# Windows 上 WinRT 通知启动偶有滞后，连接后稍作等待（paperang-cli 经验值）
_NOTIFY_SETTLE_S = 0.2


async def scan_paperang(timeout: float = 5.0, name_prefixes: list[str] | None = None) -> list[dict]:
    """扫描疑似 Paperang 设备，返回 [{address, name, rssi}]。"""
    prefixes = tuple(p.lower() for p in (name_prefixes or ["MiaoMiaoJi", "Paperang"]))
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    svc_set = {u.lower() for u in SERVICE_UUIDS}
    out = []
    for d, adv in devices.values():
        name = adv.local_name or d.name or ""
        adv_svcs = {str(u).lower() for u in (adv.service_uuids or [])}
        if name.lower().startswith(prefixes) or adv_svcs & svc_set:
            out.append({"address": d.address, "name": name, "rssi": adv.rssi})
    out.sort(key=lambda x: -(x["rssi"] or -999))
    return out


class BleTransport(Transport):
    name = "ble"
    max_payload = 480  # 10 行 × 48B；更大会触发 ATT MTU 限制

    def __init__(self, address: str) -> None:
        super().__init__()
        self._address = address
        self._client: BleakClient | None = None
        self._write_char: BleakGATTCharacteristic | None = None

    @property
    def is_open(self) -> bool:
        return bool(self._client and self._client.is_connected)

    async def open(self) -> None:
        self._client = BleakClient(
            self._address, disconnected_callback=lambda _c: self._fire_disconnected())
        await self._client.connect()
        await self._detect_characteristics()
        await asyncio.sleep(_NOTIFY_SETTLE_S)

    async def _detect_characteristics(self) -> None:
        assert self._client is not None
        chars = []
        for svc in self._client.services:
            svc_lower = svc.uuid.lower()
            if svc_lower in {u.lower() for u in SERVICE_UUIDS}:
                chars.extend(svc.characteristics)
        if not chars:
            # 服务 UUID 变体：退化为用已知特征 UUID 直取
            for uid in (*KNOWN_WRITE_CHARS, *KNOWN_NOTIFY_CHARS):
                c = self._client.services.get_characteristic(uid)
                if c:
                    chars.append(c)

        write_char = None
        for uid in KNOWN_WRITE_CHARS:  # 优先已知变体
            for c in chars:
                if c.uuid.lower() == uid and ("write" in c.properties):
                    write_char = c
                    break
            if write_char:
                break
        if write_char is None:  # 退化为任意可写特征
            for c in chars:
                if "write" in c.properties:
                    write_char = c
                    break
        notify_char = None
        for uid in KNOWN_NOTIFY_CHARS:
            for c in chars:
                if c.uuid.lower() == uid and "notify" in c.properties:
                    notify_char = c
                    break
            if notify_char:
                break
        if notify_char is None:
            for c in chars:
                if "notify" in c.properties:
                    notify_char = c
                    break
        if write_char is None or notify_char is None:
            raise ConnectionError(
                f"BLE 服务特征不完整: write={write_char} notify={notify_char}，"
                "可能连接到了非 Paperang 设备")
        self._write_char = write_char
        log.info("BLE 特征: write=%s notify=%s", write_char.uuid, notify_char.uuid)
        await self._client.start_notify(
            notify_char, self._handle_notification)

    def _handle_notification(self, _char: BleakGATTCharacteristic, data: bytearray) -> None:
        if self.on_bytes:
            self.on_bytes(bytes(data))

    async def write(self, data: bytes) -> None:
        if not self.is_open or self._write_char is None:
            raise ConnectionError("BLE 未连接")
        # response=False 对应 WriteWithoutResponse；若特征不支持则用有响应写
        use_response = "write-without-response" not in self._write_char.properties
        await self._client.write_gatt_char(
            self._write_char, data, response=use_response)

    async def close(self) -> None:
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception:
                log.exception("BLE 断开时出错")
        self._client = None

    def _fire_disconnected(self) -> None:
        log.warning("BLE 连接已断开: %s", self._address)
        if self.on_disconnected:
            try:
                self.on_disconnected()
            except Exception:
                log.exception("on_disconnected 回调异常")
