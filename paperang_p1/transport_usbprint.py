"""Bounded, cancellable overlapped I/O using the existing usbprint.sys driver."""
import asyncio
import ctypes as C
from ctypes import wintypes as W
import threading
import time
import uuid

from .transport import Transport


class Interface(C.Structure):
    _fields_ = [('size', W.DWORD), ('guid', C.c_byte * 16), ('flags', W.DWORD), ('reserved', C.c_void_p)]


class Overlapped(C.Structure):
    _fields_ = [('internal', C.c_size_t), ('internal_high', C.c_size_t), ('offset', W.DWORD), ('offset_high', W.DWORD), ('event', W.HANDLE)]


def bindings():
    k = C.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateFileW': ([W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE], W.HANDLE),
        'CreateEventW': ([C.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR], W.HANDLE),
        'CloseHandle': ([W.HANDLE], W.BOOL),
        'ReadFile': ([W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.POINTER(Overlapped)], W.BOOL),
        'WriteFile': ([W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.POINTER(Overlapped)], W.BOOL),
        'GetOverlappedResult': ([W.HANDLE, C.POINTER(Overlapped), C.POINTER(W.DWORD), W.BOOL], W.BOOL),
        'CancelIoEx': ([W.HANDLE, C.c_void_p], W.BOOL),
        'WaitForSingleObject': ([W.HANDLE, W.DWORD], W.DWORD),
    }
    for name, (args, ret) in signatures.items():
        f = getattr(k, name); f.argtypes = args; f.restype = ret
    return k


def enumerate_paths(vid=0x4348, pid=0x5584):
    s = C.WinDLL('setupapi', use_last_error=True)
    s.SetupDiGetClassDevsW.argtypes = [C.c_void_p, W.LPCWSTR, W.HWND, W.DWORD]
    s.SetupDiGetClassDevsW.restype = W.HANDLE
    s.SetupDiEnumDeviceInterfaces.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(Interface)]
    s.SetupDiGetDeviceInterfaceDetailW.argtypes = [W.HANDLE, C.POINTER(Interface), C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
    s.SetupDiDestroyDeviceInfoList.argtypes = [W.HANDLE]
    guid = C.create_string_buffer(uuid.UUID('a5dcbf10-6530-11d2-901f-00c04fb951ed').bytes_le)
    h = s.SetupDiGetClassDevsW(guid, None, None, 0x12)
    if h in (None, C.c_void_p(-1).value):
        raise C.WinError(C.get_last_error())
    paths = []
    try:
        i = 0
        while True:
            interface = Interface(); interface.size = C.sizeof(interface)
            if not s.SetupDiEnumDeviceInterfaces(h, None, guid, i, C.byref(interface)):
                if C.get_last_error() != 259:
                    raise C.WinError(C.get_last_error())
                break
            need = W.DWORD()
            s.SetupDiGetDeviceInterfaceDetailW(h, C.byref(interface), None, 0, C.byref(need), None)
            detail = C.create_string_buffer(need.value)
            C.cast(detail, C.POINTER(W.DWORD))[0] = 8 if C.sizeof(C.c_void_p) == 8 else 6
            if not s.SetupDiGetDeviceInterfaceDetailW(h, C.byref(interface), detail, need.value, C.byref(need), None):
                raise C.WinError(C.get_last_error())
            path = C.wstring_at(C.addressof(detail) + 4)
            if f'vid_{vid:04x}&pid_{pid:04x}' in path.lower():
                paths.append(path)
            i += 1
    finally:
        s.SetupDiDestroyDeviceInfoList(h)
    return paths


class UsbPrintTransport(Transport):
    name = 'usb'
    max_payload = 1024

    def __init__(self, vid=0x4348, pid=0x5584):
        super().__init__()
        self.vid, self.pid = vid, pid
        self.handle = None
        self.stopping = threading.Event()
        self.reader = None
        self._writes = asyncio.Lock()

    @property
    def is_open(self):
        return self.handle is not None and not self.stopping.is_set()

    async def open(self):
        paths = await asyncio.to_thread(enumerate_paths, self.vid, self.pid)
        if not paths:
            raise ConnectionError('P1 USB 未枚举，请开机并重新插入 USB 数据线')
        self.k = bindings()
        self.handle = self.k.CreateFileW(paths[0], 0xc0000000, 0, None, 3, 0x40000000, None)
        if self.handle in (None, C.c_void_p(-1).value):
            self.handle = None
            raise C.WinError(C.get_last_error())
        self.stopping.clear()
        self.loop = asyncio.get_running_loop()
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def _io(self, data=None, timeout=5):
        buffer = C.create_string_buffer(data) if data is not None else C.create_string_buffer(65536)
        size = len(data) if data is not None else 65536
        event = self.k.CreateEventW(None, True, False, None)
        if not event:
            raise C.WinError(C.get_last_error())
        ov = Overlapped(); ov.event = event
        count = W.DWORD()
        try:
            f = self.k.WriteFile if data is not None else self.k.ReadFile
            ok = f(self.handle, buffer, size, C.byref(count), C.byref(ov))
            if not ok and C.get_last_error() != 997:
                raise C.WinError(C.get_last_error())
            deadline = time.monotonic() + timeout
            while not ok:
                wait = self.k.WaitForSingleObject(event, 100)
                if wait == 0:
                    ok = self.k.GetOverlappedResult(self.handle, C.byref(ov), C.byref(count), False)
                    if not ok:
                        raise C.WinError(C.get_last_error())
                    break
                if wait != 258 or self.stopping.is_set() or time.monotonic() >= deadline:
                    self.k.CancelIoEx(self.handle, C.byref(ov))
                    self.k.GetOverlappedResult(self.handle, C.byref(ov), C.byref(count), True)
                    raise TimeoutError('USB I/O 已取消或超时')
            return count.value if data is not None else bytes(buffer.raw[:count.value])
        finally:
            self.k.CloseHandle(event)

    def _read_loop(self):
        try:
            while not self.stopping.is_set():
                try:
                    data = self._io(timeout=1)
                except TimeoutError:
                    continue
                if data and self.on_bytes:
                    self.loop.call_soon_threadsafe(self.on_bytes, data)
                elif not data:
                    self.stopping.wait(0.01)
        except OSError:
            self.stopping.set()
            if self.on_disconnected:
                self.loop.call_soon_threadsafe(self.on_disconnected)

    async def write(self, data):
        async with self._writes:
            if not self.is_open:
                raise ConnectionError('USB 已断开')
            offset = 0
            while offset < len(data):
                work = asyncio.create_task(asyncio.to_thread(self._io, data[offset:], 5))
                try:
                    n = await asyncio.shield(work)
                except asyncio.CancelledError:
                    self.k.CancelIoEx(self.handle, None)
                    try: await work
                    except Exception: pass
                    raise
                if not n:
                    raise ConnectionError('USB 写入未前进')
                offset += n

    async def close(self):
        async with self._writes:
            self.stopping.set()
            if self.handle is not None:
                self.k.CancelIoEx(self.handle, None)
                if self.reader:
                    await asyncio.to_thread(self.reader.join)
                self.k.CloseHandle(self.handle)
                self.handle = None
