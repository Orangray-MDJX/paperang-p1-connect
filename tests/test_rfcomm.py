from paperang_p1.config import Config
from paperang_p1.connection_manager import DeviceManager
from paperang_p1.device_a5 import A5Device
from paperang_p1.transport_rfcomm import RfcommTransport


def test_remote_disconnect_reports_cause_and_invalidates_ready_session():
    class Socket:
        def recv(self, size):
            return b''

    class Loop:
        def call_soon_threadsafe(self, callback, *args):
            callback(*args)

    transport = RfcommTransport('AA:BB:CC:DD:EE:FF')
    transport.sock = Socket()
    transport.loop = Loop()
    device = A5Device(transport, Config())
    device.state = 'ready'
    manager = DeviceManager(Config())
    manager.device = device
    manager.state = 'ready'
    transport._read_loop()
    status = manager.status()
    assert not status['connected'] and status['state'] == 'fault'
    assert 'EOF' in status['last_error']


def test_intentional_shutdown_does_not_log_remote_fault():
    transport = RfcommTransport('AA:BB:CC:DD:EE:FF')
    transport.stopping.set()
    transport._read_loop()
    assert transport.last_error is None
