"""Protocol-aware connections and serialized print/keepalive operations."""
import asyncio
import logging
import time
from .device import DeviceError, PaperangDevice
from .device_a5 import A5Device

log = logging.getLogger(__name__)


class DeviceManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.device = None
        self.last_error = None
        self.state = 'disconnected'
        self.operation_lock = asyncio.Lock()
        self._lock = asyncio.Lock()
        self._keepalive_task = None
        self.last_seen = None

    def pause(self, seconds: float = 300.0):
        """按请求暂停自动重连（如让位给手机临时打印）；
        打印任务或手动 connect 不受影响，到期自动恢复。"""
        self._paused_until = time.monotonic() + seconds
        log.info('自动重连暂停 %s 秒', int(seconds))

    @property
    def connection_paused(self):
        return time.monotonic() < getattr(self, '_paused_until', 0.0)

    async def ensure_connected(self, pref=None, background: bool = False):
        if background and self.connection_paused:
            return None
        async with self._lock:
            if (not pref or pref == 'auto' or (self.device and self.device.transport.name == pref)) and self.device and self.device.transport.is_open and getattr(self.device, 'state', 'ready') == 'ready':
                return self.device
            if self.device: await self.disconnect()
            await self._connect(pref or self.cfg.transport_pref)
            return self.device

    async def _transport(self, name):
        if name == 'usb':
            from .transport_usbprint import UsbPrintTransport
            return UsbPrintTransport(self.cfg.usb_vid, self.cfg.usb_pid)
        if name == 'spp':
            from .transport_spp import list_paired_spp
            from .transport_rfcomm import RfcommTransport
            address = self.cfg.spp_address
            if not address:
                devices = await list_paired_spp()
                candidates = [d for d in devices if 'paperang' in d['name'].lower() or 'miaomiao' in d['name'].lower()]
                if not candidates: raise DeviceError('未找到已配对的 P1，请开机并在 Windows 蓝牙设置中配对')
                if len(candidates) > 1: raise DeviceError('发现多个 P1，请配置 spp_address')
                address = candidates[0]['address']
            return RfcommTransport(address, self.cfg.rfcomm_data_channel)
        if name == 'ble':
            from .transport_ble import BleTransport, scan_paperang
            address = self.cfg.ble_address
            if not address:
                devices = await scan_paperang(6, self.cfg.ble_name_prefixes)
                if len(devices) != 1: raise DeviceError('BLE 未发现唯一 P1，请指定 ble_address')
                address = devices[0]['address']
            return BleTransport(address)
        raise DeviceError(f'未知通道 {name}')

    async def _connect(self, pref):
        orders = {'auto': ['usb', 'spp'], 'usb': ['usb'], 'spp': ['spp'], 'ble': ['ble'], 'vendor': ['vendor']}
        if pref not in orders: raise DeviceError(f'未知通道偏好 {pref}')
        errors = []; self.state = 'connecting'
        poked = False
        for name in orders[pref]:
            modes = ['a5', 'legacy'] if self.cfg.protocol_mode == 'auto' else [self.cfg.protocol_mode]
            for mode in modes:
                # 经典通道失败后先 BLE 敲门唤醒再重试一次（深睡的 P1 只有被
                # GATT 触碰后才会响应寻呼，实机 2026-09-29 验证）。
                attempts = 2 if name == 'spp' else 1
                for attempt in range(attempts):
                    dev = None
                    try:
                        if name == 'vendor':
                            from .vendor_bridge import VendorPrinter
                            dev = VendorPrinter(self.cfg)
                        else:
                            transport = await self._transport(name)
                            dev = A5Device(transport, self.cfg) if mode == 'a5' else PaperangDevice(transport, self.cfg)
                        await dev.connect()
                        # Legacy handshakes must also prove a response, not just an open handle.
                        if mode == 'legacy' or name == 'vendor':
                            if not await dev.get_sn(): raise DeviceError('未收到有效设备身份响应')
                        self.device = dev
                        self.state = 'ready'; self.last_error = None
                        self.last_seen = time.monotonic()
                        try: await dev.keepalive_setup()
                        except Exception as e:
                            log.warning('保活设置未确认: %s', e)
                            self.last_error = str(e)
                            if not dev.transport.is_open:
                                raise DeviceError('保活初始化期间失联') from e
                        self._keepalive_task = asyncio.create_task(self._keepalive_loop()) if self.cfg.keepalive else None
                        return
                    except Exception as e:
                        errors.append(f'{name}/{mode}: {e}')
                        if dev: await dev.close()
                        self.device = None
                        if name == 'spp' and attempt == 0 and not poked:
                            poked = True
                            if await self._ble_poke():
                                log.info('BLE 敲门完成，重试经典蓝牙连接')
                                continue
                        break
        self.state = 'fault'; self.last_error = '; '.join(errors)
        raise DeviceError(f'连接失败，请开机/唤醒: {self.last_error}')

    async def _ble_poke(self):
        """扫描并用 GATT 短连唤醒 P1：设备接受连接后约 30ms 主动断开，
        随后经典蓝牙恢复响应。任何异常都只当敲门失败处理。"""
        try:
            from .transport_ble import BleTransport, scan_paperang
            devices = await scan_paperang(4, self.cfg.ble_name_prefixes)
            if not devices:
                return False
            poke = BleTransport(devices[0]['address'])
            try:
                await asyncio.wait_for(poke.open(), timeout=5)
            except Exception:
                pass  # 被设备立刻断开正是预期的敲门效果
            finally:
                try:
                    await poke.close()
                except Exception:
                    pass
            log.info('BLE 敲门: %s', devices[0]['address'])
            return True
        except Exception as e:
            log.debug('BLE 敲门未生效: %s', e)
            return False

    async def disconnect(self):
        if self._keepalive_task and self._keepalive_task is not asyncio.current_task():
            self._keepalive_task.cancel()
            try: await self._keepalive_task
            except asyncio.CancelledError: pass
        self._keepalive_task = None
        if self.device: await self.device.close()
        self.device = None; self.state = 'disconnected'

    async def _keepalive_loop(self):
        while True:
            await asyncio.sleep(self.cfg.keepalive_interval_s)
            async with self.operation_lock:
                try:
                    if not self.device: return
                    value = await self.device.get_battery()
                    if value is None: raise DeviceError('心跳没有有效应答')
                    media_query = getattr(self.device, 'get_media_status', None)
                    if media_query: await media_query()
                    self.last_seen = time.monotonic()
                    log.info('heartbeat: %s battery=%s poweroff=%s', self.device.transport.name, value, self.device.power_down_time)
                except Exception as e:
                    self.last_error = str(e); self.state = 'fault'
                    if self.device: await self.device.close()
                    return

    def status(self):
        dev = self.device
        connected = bool(dev and dev.transport.is_open and getattr(dev, 'state', 'ready') == 'ready')
        lid = getattr(dev, 'lid_closed', None)
        paper = getattr(dev, 'paper_present', None)
        return {'connected': connected, 'printable': connected and lid is not False and paper is not False,
                'lid_closed': lid, 'paper_present': paper,
                'dpi': getattr(dev, 'dpi', None), 'paper_width_mm': getattr(dev, 'paper_width_mm', None),
                'state': ('blocked' if lid is False or paper is False else self.state) if connected else ('fault' if dev else self.state),
                'protocol': getattr(dev, 'protocol', 'legacy') if dev else None,
                'transport': dev.transport.name if dev else None, 'version': getattr(dev, 'version', None),
                'battery': dev.battery if dev else None, 'sn': dev.sn if dev else None,
                'power_down_time': dev.power_down_time if dev else None,
                'uptime_s': round(time.monotonic() - dev.connected_at, 1) if connected and dev.connected_at else None,
                'last_seen_age_s': round(time.monotonic() - self.last_seen, 1) if self.last_seen else None,
                'last_error': (getattr(dev, 'last_error', None) or self.last_error) if not connected else self.last_error}
