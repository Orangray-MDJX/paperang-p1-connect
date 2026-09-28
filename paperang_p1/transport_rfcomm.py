"""Native Winsock RFCOMM, explicit channel selection and bounded socket I/O."""
import asyncio
import ctypes as C
import logging
import select
import socket
import threading
from .transport import Transport

log = logging.getLogger(__name__)


class Address(C.Structure):
    _pack_ = 1
    _fields_ = [('family', C.c_ushort), ('mac', C.c_ulonglong),
                ('service', C.c_ubyte * 16), ('port', C.c_ulong)]


class RfcommTransport(Transport):
    name = 'spp'
    max_payload = 1024

    def __init__(self, address, channel=1):
        super().__init__()
        self.address, self.channel = address, channel
        self.sock = None
        self.stopping = threading.Event()
        self.reader = None
        self.last_error = None
        self._write_lock = asyncio.Lock()

    @property
    def is_open(self):
        return self.sock is not None and not self.stopping.is_set()

    def _connect(self):
        sock = socket.socket(32, socket.SOCK_STREAM, 3)
        try:
            sock.setblocking(False)
            ws = C.WinDLL('ws2_32', use_last_error=True)
            ws.connect.argtypes = [C.c_size_t, C.c_void_p, C.c_int]
            addr = Address(); addr.family = 32
            addr.mac = int(self.address.replace(':', '').replace('-', ''), 16)
            addr.port = self.channel
            if ws.connect(sock.fileno(), C.byref(addr), C.sizeof(addr)) != 0:
                error = ws.WSAGetLastError()
                if error not in (10035, 10036): raise OSError(error, 'RFCOMM connect')
                _, writable, errors = select.select([], [sock], [sock], 8)
                if errors or not writable: raise TimeoutError('RFCOMM connect timeout')
                error = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if error: raise OSError(error, 'RFCOMM connect')
            sock.settimeout(1)
            return sock
        except BaseException:
            sock.close(); raise

    async def open(self):
        opening = asyncio.create_task(asyncio.to_thread(self._connect))
        try:
            self.sock = await asyncio.shield(opening)
        except asyncio.CancelledError:
            try: (await opening).close()
            except Exception: pass
            raise
        self.stopping.clear()
        self.last_error = None
        self.loop = asyncio.get_running_loop()
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def _read_loop(self):
        try:
            while not self.stopping.is_set():
                try: data = self.sock.recv(65536)
                except socket.timeout: continue
                if not data:
                    if not self.stopping.is_set():
                        self.last_error = 'RFCOMM 对端关闭连接 (EOF)'
                    break
                if self.on_bytes: self.loop.call_soon_threadsafe(self.on_bytes, data)
        except OSError as e:
            if not self.stopping.is_set():
                self.last_error = f'RFCOMM 读取失败: {e}'
        finally:
            if self.last_error:
                log.warning('%s channel=%s: %s', self.address, self.channel, self.last_error)
            self.stopping.set()
            if self.on_disconnected: self.loop.call_soon_threadsafe(self.on_disconnected)

    async def write(self, data):
        async with self._write_lock:
            if not self.is_open: raise ConnectionError('RFCOMM disconnected')
            writing = asyncio.create_task(asyncio.to_thread(self.sock.sendall, data))
            try: await asyncio.shield(writing)
            except asyncio.CancelledError:
                try: self.sock.shutdown(socket.SHUT_RDWR)
                except OSError: pass
                try: await writing
                except Exception: pass
                raise

    async def close(self):
        async with self._write_lock:
            self.stopping.set()
            if self.sock:
                try: self.sock.shutdown(socket.SHUT_RDWR)
                except OSError: pass
                if self.reader: await asyncio.to_thread(self.reader.join)
                self.sock.close(); self.sock = None
