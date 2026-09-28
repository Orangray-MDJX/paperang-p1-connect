# -*- coding: utf-8 -*-
"""Set/clear PRINTER_ATTRIBUTE_ENABLE_BIDI (0x40) on a printer queue.

Usage: python set_bidi.py <printer-name> <on|off>
"""
import ctypes
import ctypes.wintypes as wt
import sys

winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)

PRINTER_ATTRIBUTE_ENABLE_BIDI = 0x40


class PRINTER_INFO_2W(ctypes.Structure):
    _fields_ = [
        ("pServerName", wt.LPWSTR), ("pPrinterName", wt.LPWSTR),
        ("pShareName", wt.LPWSTR), ("pPortName", wt.LPWSTR),
        ("pDriverName", wt.LPWSTR), ("pComment", wt.LPWSTR),
        ("pLocation", wt.LPWSTR), ("pDevMode", ctypes.c_void_p),
        ("pSepFile", wt.LPWSTR), ("pPrintProcessor", wt.LPWSTR),
        ("pDatatype", wt.LPWSTR), ("pParameters", wt.LPWSTR),
        ("pSecurityDescriptor", ctypes.c_void_p),
        ("Attributes", wt.DWORD), ("Priority", wt.DWORD),
        ("DefaultPriority", wt.DWORD), ("StartTime", wt.DWORD),
        ("UntilTime", wt.DWORD), ("Status", wt.DWORD), ("cJobs", wt.DWORD),
        ("AveragePPM", wt.DWORD),
    ]


def main(name: str, on: bool) -> int:
    h = wt.HANDLE()
    if not winspool.OpenPrinterW(name, ctypes.byref(h), None):
        print("OpenPrinter failed:", ctypes.get_last_error())
        return 1
    try:
        pcb = wt.DWORD(0)
        winspool.GetPrinterW(h, 2, None, 0, ctypes.byref(pcb))
        buf = ctypes.create_string_buffer(max(pcb.value, 1))
        if not winspool.GetPrinterW(h, 2, buf, pcb, ctypes.byref(pcb)):
            print("GetPrinter failed:", ctypes.get_last_error())
            return 1
        info = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_2W)).contents
        old = info.Attributes
        if on:
            info.Attributes = old | PRINTER_ATTRIBUTE_ENABLE_BIDI
        else:
            info.Attributes = old & ~PRINTER_ATTRIBUTE_ENABLE_BIDI
        if not winspool.SetPrinterW(h, 2, buf, 0):
            print("SetPrinter failed:", ctypes.get_last_error())
            return 1
        print(f"attributes: {old} -> {info.Attributes}")
        return 0
    finally:
        winspool.ClosePrinter(h)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2].lower() == "on"))
