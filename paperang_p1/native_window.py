"""Launch or activate the WinUI 3 desktop management app."""
from __future__ import annotations

import ctypes
from pathlib import Path
import subprocess
import sys


TITLE = '喵喵机 P1'
WINDOW_CLASS = 'WinUIDesktopWin32WindowClass'
LAN_EVENT_NAME = 'Local\\PaperangP1ShowLan'
ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'winui' / 'PaperangP1'


def executable() -> Path:
    candidates = (
        ROOT / 'winui' / 'dist' / 'PaperangP1.exe',
        PROJECT / 'bin' / 'x64' / 'Release' / 'net8.0-windows10.0.19041.0' / 'win-x64' / 'PaperangP1.exe',
        PROJECT / 'bin' / 'x64' / 'Debug' / 'net8.0-windows10.0.19041.0' / 'win-x64' / 'PaperangP1.exe',
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError('未找到 WinUI 3 管理程序。请先运行 scripts\\build_winui.ps1。')


def activate_existing(section: str = '') -> bool:
    if sys.platform != 'win32':
        return False
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    handle = user32.FindWindowW(WINDOW_CLASS, TITLE)
    if not handle:
        return False
    user32.ShowWindow(handle, 9)
    user32.SetForegroundWindow(handle)
    if section == 'lan':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenEventW.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_wchar_p]
        kernel.OpenEventW.restype = ctypes.c_void_p
        kernel.SetEvent.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        event = kernel.OpenEventW(0x0002, False, LAN_EVENT_NAME)
        if event:
            try:
                kernel.SetEvent(event)
            finally:
                kernel.CloseHandle(event)
    return True


def launch(section: str = '') -> None:
    if activate_existing(section):
        return
    target = executable()
    args = [str(target)]
    if section == 'lan':
        args.append('--lan')
    subprocess.Popen(args, cwd=target.parent)


def run(section: str = '') -> None:
    launch(section)


if __name__ == '__main__':
    run('lan' if '--lan' in sys.argv else '')
