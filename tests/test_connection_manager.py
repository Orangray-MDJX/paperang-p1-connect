import asyncio
import pytest
from paperang_p1.config import Config
from paperang_p1.connection_manager import DeviceManager
from paperang_p1.device import DeviceError


class Transport:
    name = 'usb'
    is_open = False


class Device:
    protocol = 'a5'
    def __init__(self, transport, cfg):
        self.transport = transport
        self.state = 'disconnected'
        self.battery = self.sn = self.power_down_time = self.connected_at = None
    async def connect(self):
        self.transport.is_open = True
        self.state = 'ready'
    async def keepalive_setup(self): pass
    async def close(self):
        self.transport.is_open = False
        self.state = 'disconnected'


def test_usb_only_recovers_after_unplug_without_bluetooth_fallback(monkeypatch):
    async def run():
        manager = DeviceManager(Config(transport_pref='usb', protocol_mode='a5', keepalive=False))
        available = True
        requested = []
        async def transport(name):
            requested.append(name)
            if not available: raise ConnectionError('USB unplugged')
            return Transport()
        manager._transport = transport
        monkeypatch.setattr('paperang_p1.connection_manager.A5Device', Device)
        original = await manager.ensure_connected()
        original.transport.is_open = False; original.state = 'fault'; available = False
        with pytest.raises(DeviceError): await manager.ensure_connected()
        assert manager.device is None and manager.status()['state'] == 'fault'
        available = True
        recovered = await manager.ensure_connected()
        assert recovered is not original and manager.status()['connected']
        assert requested == ['usb', 'usb', 'usb']
        await manager.disconnect()
    asyncio.run(run())
