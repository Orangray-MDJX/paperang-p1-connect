# -*- coding: utf-8 -*-
"""usbprint 裸设备双向读写（免 Zadig）。

usbprint.sys 为 USB 打印机暴露设备接口，CreateFile 打开后
WriteFile → bulk OUT、ReadFile → bulk IN，可双向对话。

用法:
  python usb_raw_io.py --list
  python usb_raw_io.py --send <hex> [--expect 64] [--timeout 3]
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import uuid

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
setupapi.SetupDiEnumDeviceInterfaces.restype = wt.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wt.BOOL
setupapi.SetupDiDestroyDeviceInfoList.restype = wt.BOOL

GUID_USBPRINT = uuid.UUID("{28d78fad-bb36-4c65-932a-f6c6e40ff7d4}")
GUID_USBPRINTER_CLASS = uuid.UUID("{a5dcbf10-6530-11d2-901f-00c04fb951ed}")

GENERIC_READ_WRITE = 0xC0000000
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("interfaceClassGuid", ctypes.c_char * 16),
                ("flags", wt.DWORD), ("reserved", ctypes.c_void_p)]


class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("devicePath", ctypes.c_wchar * 1024)]


def find_usbprint_paths():
    paths = []
    for g in (GUID_USBPRINT, GUID_USBPRINTER_CLASS):
        gb = g.bytes_le
        h = setupapi.SetupDiGetClassDevsW(gb, None, None, 0x10 | 2)
        if not h or h == 0xFFFFFFFFFFFFFFFF:
            continue
        idx = 0
        while True:
            did = SP_DEVICE_INTERFACE_DATA()
            did.cbSize = ctypes.sizeof(did)
            did.interfaceClassGuid = gb
            if not setupapi.SetupDiEnumDeviceInterfaces(
                    ctypes.c_void_p(h), None, gb, idx, ctypes.byref(did)):
                break
            det = SP_DEVICE_INTERFACE_DETAIL_DATA_W()
            det.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            need = wt.DWORD()
            if setupapi.SetupDiGetDeviceInterfaceDetailW(
                    ctypes.c_void_p(h), ctypes.byref(did), ctypes.byref(det),
                    ctypes.sizeof(det), ctypes.byref(need), None):
                if det.devicePath:
                    paths.append(det.devicePath)
            idx += 1
        setupapi.SetupDiDestroyDeviceInfoList(ctypes.c_void_p(h))
    return paths


def open_dev(path: str):
    kernel32.CreateFileW.restype = ctypes.c_void_p
    h = kernel32.CreateFileW(path, GENERIC_READ_WRITE, 0, None,
                             OPEN_EXISTING, 0, None)
    if h in (None, 0, 0xFFFFFFFFFFFFFFFF):
        raise OSError(f"CreateFile 失败 err={ctypes.get_last_error()}: {path}")
    return ctypes.c_void_p(h)


def usb_write(h, data: bytes) -> int:
    written = wt.DWORD()
    ok = kernel32.WriteFile(h, data, len(data), ctypes.byref(written), None)
    if not ok:
        raise OSError(f"WriteFile err={ctypes.get_last_error()}")
    return written.value


def usb_read(h, size: int = 512, timeout_ms: int = 3000):
    """同步读（阻塞）。用 SetCommTimeouts 无效于 usbprint；改为线程+超时。"""
    import threading
    buf = ctypes.create_string_buffer(size)
    got = wt.DWORD()

    def rd():
        ok = kernel32.ReadFile(h, buf, size, ctypes.byref(got), None)
        if not ok:
            got.value = 0

    t = threading.Thread(target=rd, daemon=True)
    t.start()
    t.join(timeout_ms / 1000)
    if t.is_alive():
        return None  # 超时（线程还挂着，句柄关闭时线程会结束）
    return buf.raw[:got.value] if got.value else b""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--send", help="hex 字节")
    ap.add_argument("--expect", type=int, default=512)
    ap.add_argument("--timeout", type=float, default=3.0)
    args = ap.parse_args()

    paths = find_usbprint_paths()
    if args.list or not args.send:
        for p in paths:
            print(p)
        return
    if not paths:
        print("无 usbprint 设备接口")
        return
    path = next((p for p in paths if "vid_4348" in p.lower()), paths[0])
    print("打开:", path)
    h = open_dev(path)
    try:
        data = bytes.fromhex(args.send)
        n = usb_write(h, data)
        print(f"已写 {n}B")
        r = usb_read(h, args.expect, int(args.timeout * 1000))
        print("读到:", "超时" if r is None else (r.hex() or "(0B/EOF)"))
    finally:
        kernel32.CancelIoEx(h, None)
        kernel32.CloseHandle(h)


if __name__ == "__main__":
    main()
