"""Native Windows management window backed by the loopback print service."""
from __future__ import annotations

import ctypes
import base64
import json
import logging
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

import httpx

from .config import Config
from .service import setup_logging


TITLE = 'Paperang P1 Connect'
MUTEX_NAME = 'Local\\PaperangP1ConnectWindow'
LAN_EVENT_NAME = 'Local\\PaperangP1ConnectShowLan'
log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / 'static'


def activate_existing() -> bool:
    """Restore the existing app window when the tray is clicked again."""
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    handle = user32.FindWindowW(None, TITLE)
    if not handle:
        return False
    user32.ShowWindow(handle, 9)  # SW_RESTORE
    user32.SetForegroundWindow(handle)
    return True


def signal_lan() -> bool:
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenEventW.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_wchar_p]
    kernel.OpenEventW.restype = ctypes.c_void_p
    kernel.SetEvent.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    event = kernel.OpenEventW(0x0002, False, LAN_EVENT_NAME)
    if event:
        try:
            return bool(kernel.SetEvent(event))
        finally:
            kernel.CloseHandle(event)
    return False


def launch(section: str = '') -> None:
    """Open the app from a tray callback without blocking the tray loop."""
    if activate_existing():
        if section == 'lan':
            signal_lan()
        return
    root = Path(__file__).resolve().parents[1]
    executable = Path(sys.executable).with_name('pythonw.exe')
    if not executable.exists():
        executable = Path(sys.executable)
    args = [str(executable), '-m', 'paperang_p1.window']
    if section == 'lan':
        args.append('--lan')
    subprocess.Popen(args, cwd=root, creationflags=subprocess.CREATE_NO_WINDOW)


def ensure_service(base_url: str) -> None:
    """Use the same single service as the tray; let its mutex handle races."""
    for attempt in range(24):
        try:
            response = httpx.get(base_url + '/api/status', timeout=0.6, trust_env=False)
            response.raise_for_status()
            return
        except (httpx.HTTPError, OSError):
            if attempt == 2:
                root = Path(__file__).resolve().parents[1]
                executable = Path(sys.executable).with_name('pythonw.exe')
                if not executable.exists():
                    executable = Path(sys.executable)
                subprocess.Popen([str(executable), str(root / 'scripts' / 'run_service.py')],
                                 cwd=root, creationflags=subprocess.CREATE_NO_WINDOW)
            time.sleep(0.5)
    raise RuntimeError('后台打印服务未能启动，请检查 service.log')


class WindowControls:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self._window = None
        self.maximized = False

    def _local(self) -> bool:
        current = urlsplit(self._window.get_current_url() or '')
        expected = urlsplit(self.base_url)
        return current.scheme == 'http' and current.hostname == expected.hostname and current.port == expected.port

    def minimize(self):
        if self._local():
            self._window.minimize()

    def toggle_maximize(self):
        if self._local():
            if self.maximized:
                self._window.restore()
            else:
                self._window.maximize()
            self.maximized = not self.maximized
            return self.maximized
        return False

    def close(self):
        if self._local():
            self._window.destroy()


def install_native_assets(window) -> None:
    """Style the app from bundled files even while an older service is running."""
    window.load_css((STATIC_DIR / 'fluent.css').read_text(encoding='utf-8'))
    logo = 'data:image/svg+xml;base64,' + base64.b64encode(
        (STATIC_DIR / 'logo.svg').read_bytes()).decode('ascii')
    window.run_js(
        'document.querySelectorAll("img[src=\'/assets/logo.svg\']")'
        f'.forEach(image => image.src = {json.dumps(logo)});')
    window.run_js((STATIC_DIR / 'window-chrome.js').read_text(encoding='utf-8'))


def run(section: str = '') -> None:
    if sys.platform != 'win32':
        raise RuntimeError('管理窗口仅支持 Windows')
    setup_logging('window.log')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = kernel.CreateMutexW(None, False, MUTEX_NAME)
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(mutex)
        activate_existing()
        return
    try:
        cfg = Config.load()
        base_url = f'http://127.0.0.1:{cfg.api_port}'
        ensure_service(base_url)
        import webview

        controls = WindowControls(base_url)
        url = base_url + ('/#lan-tools' if section == 'lan' else '/')
        window = webview.create_window(TITLE, url, js_api=controls, width=1120,
                                       height=820, min_size=(760, 540),
                                       frameless=True, easy_drag=False, shadow=True,
                                       background_color='#f4f5f8', text_select=True)
        controls._window = window
        window.events.maximized += lambda: setattr(controls, 'maximized', True)
        window.events.restored += lambda: setattr(controls, 'maximized', False)
        window.events.shown += lambda: log.info('管理窗口已显示')
        def install_chrome():
            install_native_assets(window)
            def report_style():
                style = window.evaluate_js("({font: getComputedStyle(document.body).fontFamily, card: getComputedStyle(document.querySelector('.card')).borderRadius, controls: !document.querySelector('.window-controls').hidden, logo: document.querySelector('.titlebar-brand img').src.startsWith('data:')})")
                log.info('管理窗口页面已加载: %s; 样式=%s', window.get_current_url(), style)
            threading.Timer(0.7, report_style).start()
        window.events.loaded += install_chrome
        kernel.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
        kernel.CreateEventW.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        lan_event = kernel.CreateEventW(None, False, False, LAN_EVENT_NAME)
        if not lan_event:
            raise ctypes.WinError(ctypes.get_last_error())
        watcher_stop = threading.Event()
        def watch_navigation():
            while not watcher_stop.is_set():
                if kernel.WaitForSingleObject(lan_event, 500) == 0:
                    log.info('托盘请求显示局域网工具')
                    window.load_url(base_url + '/#lan-tools')
        watcher = threading.Thread(target=watch_navigation, daemon=True)
        window.events.shown += watcher.start
        icon = Path(__file__).parent / 'static' / 'app.ico'
        try:
            webview.start(gui='edgechromium', icon=str(icon))
        finally:
            watcher_stop.set()
            if watcher.is_alive():
                watcher.join(timeout=1)
            kernel.CloseHandle(lan_event)
    except Exception:
        log.exception('管理窗口启动失败')
        raise
    finally:
        kernel.CloseHandle(mutex)


if __name__ == '__main__':
    run('lan' if '--lan' in sys.argv else '')
