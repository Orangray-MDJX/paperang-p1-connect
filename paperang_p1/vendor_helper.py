# -*- coding: utf-8 -*-
"""32 位辅助进程：通过 ctypes 驱动官方 libprw.dll（Go 协议库）。

libprw.dll 是 32 位库（喵喵机 PC 客户端 2.0.15 同款），提供蓝牙 COM 口与
USB 两条通道的完整 Paperang 协议实现。本脚本必须用 32 位 Python 运行，
以 JSON 行协议（stdin/stdout）对主服务提供：

  请求:  {"id": 1, "cmd": "list"|"connect"|"disconnect"|"print_b64"|"density"|"stop", ...}
  应答:  {"id": 1, "resp": ...} 或 {"id": 1, "error": "..."}
  事件:  {"event": "inserted"|"removed"|"status"|"req_disconnect", "data": {...}}
"""

import base64
import ctypes
import json
import os
import sys
import threading

PRINT_LOCK = threading.Lock()


def log_line(obj):
    with PRINT_LOCK:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def find_dll() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (
        os.path.join(here, "..", "vendor", "libprw.dll"),
        os.path.join(here, "vendor", "libprw.dll"),
    ):
        p = os.path.normpath(cand)
        if os.path.exists(p):
            return p
    raise FileNotFoundError("vendor/libprw.dll 不存在（请从喵喵机 PC 客户端获取）")


def main() -> int:
    dll_path = find_dll()
    os.add_dll_directory(os.path.dirname(dll_path))
    lib = ctypes.CDLL(dll_path)

    lib.SetDebugLevel.argtypes = [ctypes.c_int]
    lib.SetDebugLevel.restype = None
    lib.ListBlueToothDevice.argtypes = []
    lib.ListBlueToothDevice.restype = ctypes.c_char_p
    lib.ConnectSerialBlueTooth.argtypes = [ctypes.c_char_p]
    lib.ConnectSerialBlueTooth.restype = None
    lib.DisConnectSerialBlueTooth.argtypes = [ctypes.c_char_p]
    lib.DisConnectSerialBlueTooth.restype = None
    lib.PrintBase64Image.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.PrintBase64Image.restype = None
    lib.EventLoopCallback.argtypes = [ctypes.c_void_p]
    lib.EventLoopCallback.restype = None
    lib.Start.restype = None
    lib.Stop.restype = None
    lib.SetDensity.argtypes = [ctypes.c_int]
    lib.SetDensity.restype = None

    event_map = {
        "EvtPrinterInserted": "inserted",
        "EvtPrinterRemoved": "removed",
        "EvtPrinterStatusChanged": "status",
        "EvtPrinterRequiredDisconnectFromServer": "req_disconnect",
        "EvtNoUSBDeviceFounded": "no_usb",
    }

    @ctypes.CFUNCTYPE(None, ctypes.c_char_p)
    def on_event(arg):
        try:
            j = json.loads(arg.decode("utf-8", "replace"))
        except Exception:
            return
        name = event_map.get(j.get("event_name", ""))
        if name:
            log_line({"event": name, "data": j.get("data")})

    def handle(req):
        cmd = req.get("cmd")
        rid = req.get("id")
        try:
            if cmd == "list":
                raw = lib.ListBlueToothDevice()
                devices = json.loads(raw.decode("utf-8", "replace")) if raw else []
                return {"resp": devices}
            if cmd == "connect":
                lib.ConnectSerialBlueTooth(req["serial"].encode())
                return {"resp": "connecting"}
            if cmd == "disconnect":
                lib.DisConnectSerialBlueTooth(req["serial"].encode())
                return {"resp": "ok"}
            if cmd == "print_b64":
                lib.PrintBase64Image(req["b64"].encode(), int(req.get("copies", 1)))
                return {"resp": "ok"}
            if cmd == "density":
                lib.SetDensity(int(req["value"]))
                return {"resp": "ok"}
            if cmd == "stop":
                lib.Stop()
                return {"resp": "ok"}
            return {"error": f"unknown cmd {cmd}"}
        except Exception as e:  # noqa: BLE001
            return {"error": repr(e)}

    lib.EventLoopCallback(on_event)
    lib.Start()
    lib.SetDebugLevel(1)
    log_line({"event": "helper_ready"})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        out = handle(req)
        out["id"] = req.get("id")
        log_line(out)
        if req.get("cmd") == "stop":
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
