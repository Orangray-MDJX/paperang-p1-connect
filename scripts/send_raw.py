# -*- coding: utf-8 -*-
"""向打印队列提交 RAW 数据（绕过驱动渲染，直达 usbprint bulk OUT）。

用法: python send_raw.py <queue-name> <hexfile|-> [二进制文件]
"""
import ctypes
import ctypes.wintypes as wt
import sys
from pathlib import Path

winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)


class DOC_INFO_1W(ctypes.Structure):
    _fields_ = [("pDocName", wt.LPWSTR), ("pOutputFile", wt.LPWSTR),
                ("pDatatype", wt.LPWSTR)]


class PRINTER_DEFAULTSW(ctypes.Structure):
    _fields_ = [("pDatatype", wt.LPWSTR), ("pDevMode", ctypes.c_void_p),
                ("DesiredAccess", wt.DWORD)]


def send_raw(queue: str, data: bytes) -> None:
    pd = PRINTER_DEFAULTSW()
    pd.DesiredAccess = 0x02000000 | 0x00020000 | 0x00010000  # SERVER|PRINTER_ACCESS_USE
    h = wt.HANDLE()
    if not winspool.OpenPrinterW(queue, ctypes.byref(h), ctypes.byref(pd)):
        raise OSError(f"OpenPrinter({queue}) 失败: {ctypes.get_last_error()}")
    try:
        di = DOC_INFO_1W("PaperangRaw", None, "RAW")
        job = winspool.StartDocPrinterW(h, 1, ctypes.byref(di))
        if not job:
            raise OSError(f"StartDocPrinter 失败: {ctypes.get_last_error()}")
        try:
            if not winspool.StartPagePrinter(h):
                raise OSError("StartPagePrinter 失败")
            written = wt.DWORD(0)
            off = 0
            while off < len(data):
                chunk = data[off:off + 4096]
                if not winspool.WritePrinter(h, chunk, len(chunk),
                                             ctypes.byref(written)):
                    raise OSError(f"WritePrinter 失败 @ {off}")
                off += written.value
            winspool.EndPagePrinter(h)
        finally:
            winspool.EndDocPrinter(h)
        print(f"RAW 已提交 {len(data)} 字节")
    finally:
        winspool.ClosePrinter(h)


def main() -> int:
    queue = sys.argv[1]
    src = sys.argv[2]
    data = Path(src).read_bytes() if src != "-" else sys.stdin.buffer.read()
    send_raw(queue, data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
