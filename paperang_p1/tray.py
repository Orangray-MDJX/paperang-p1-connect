"""Tray client for the single background service; never opens the USB device."""
import ctypes
import logging
from pathlib import Path
import subprocess
import sys
import threading
import time
import httpx
from PIL import Image, ImageDraw, ImageFont
import pystray
from .config import Config
from .service import setup_logging
from .native_window import launch as launch_window

log = logging.getLogger(__name__)


def run():
    setup_logging("tray.log")
    cfg = Config.load()
    api = f'http://127.0.0.1:{cfg.api_port}'
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = kernel.CreateMutexW(None, False, 'Local\\PaperangP1ConnectTray')
    if not mutex: raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(mutex)
        launch_window()
        return
    client = httpx.Client(base_url=api, trust_env=False, timeout=30)
    stopping = threading.Event()
    cached = {}
    cache_lock = threading.Lock()

    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def snapshot():
        with cache_lock: return cached.copy()

    def icon_image(state):
        """The tray rendition of static/logo.svg with a live state and charge badge."""
        image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        ink = '#252a33'
        accent = '#df805f'
        draw.rounded_rectangle((7, 11, 55, 51), radius=11, fill=ink)
        draw.polygon([(15, 14), (18, 4), (28, 12)], fill=ink)
        draw.polygon([(36, 12), (46, 4), (49, 14)], fill=ink)
        draw.ellipse((22, 23, 27, 28), fill='white')
        draw.ellipse((37, 23, 42, 28), fill='white')
        draw.arc((26, 27, 38, 39), 8, 172, fill='white', width=2)
        draw.rounded_rectangle((14, 45, 50, 57), radius=3, fill='white', outline=ink, width=2)
        battery = state.get('battery')
        draw.line((20, 51, 44, 51), fill='#aab0b8', width=3)
        if state.get('connected') and isinstance(battery, (int, float)):
            level = max(0, min(100, battery))
            draw.line((20, 51, 20 + round(24 * level / 100), 51), fill=accent, width=3)
        status = ('#d95d4f' if not state.get('connected') else
                  '#d7982b' if state.get('printable') is False or state.get('queue', {}).get('printing') else
                  '#33a377')
        draw.ellipse((1, 42, 18, 59), fill='white')
        draw.ellipse((4, 45, 15, 56), fill=status)
        if state.get('connected') and isinstance(battery, (int, float)):
            badge = str(max(0, min(100, round(battery))))
            draw.rounded_rectangle((37, 0, 63, 16), radius=6, fill=accent)
            draw.text((50, 8), badge, font=ImageFont.load_default(), fill='white', anchor='mm')
        return image

    def dashboard(icon=None, item=None): launch_window()
    def reconnect(icon, item):
        def work():
            try:
                request('POST','/api/connect',json={})
                refresh()
            except Exception as error:
                log.warning('托盘连接失败: %s',error)
                icon.notify('请按实体键唤醒打印机并检查连接。','喵喵机 P1')
        threading.Thread(target=work,daemon=True).start()
    def quit_tray(icon, item):
        stopping.set(); icon.stop()
    def status_label(item):
        state = snapshot()
        if state.get('queue', {}).get('printing'): return '正在打印'
        if state.get('lid_closed') is False: return '请合好纸仓盖'
        if state.get('paper_present') is False: return '打印机缺纸'
        return ({'usb':'USB','spp':'蓝牙','ble':'BLE'}.get(state.get('transport'),'设备')+' 已就绪') if state.get('connected') else '等待打印机'
    def battery_label(item):
        value = snapshot().get('battery')
        return f"电量：{value}%" if value is not None else '电量：未知'
    def queue_label(item): return f"等待任务：{snapshot().get('queue',{}).get('pending',0)}"

    icon = pystray.Icon('PaperangP1',icon_image({}),'喵喵机 P1',pystray.Menu(
        pystray.MenuItem('打开打印管理',dashboard,default=True),
        pystray.MenuItem('连接打印机',reconnect),
        pystray.MenuItem('局域网与长图打印',lambda icon, item: launch_window('lan')),
        pystray.MenuItem(status_label,None),
        pystray.MenuItem(battery_label,None),
        pystray.MenuItem(queue_label,None),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('退出托盘（服务继续运行）',quit_tray)))

    def refresh():
        try: state = request('GET','/api/status')
        except Exception as error:
            state = {'connected':False,'last_error':str(error)}
        with cache_lock:
            cached.clear(); cached.update(state)
        icon.icon = icon_image(state)
        state_text = status_label(None)
        battery = state.get('battery')
        charge_text = f' · 电量 {battery}%' if state.get('connected') and battery is not None else ''
        pending = state.get('queue', {}).get('pending', 0)
        icon.title = f'喵喵机 P1 · {state_text}{charge_text} · 等待 {pending}'
        icon.update_menu()

    def observe():
        try:
            try: request('GET','/api/status')
            except httpx.ConnectError:
                root = Path(__file__).resolve().parents[1]
                executable = Path(sys.executable).with_name('pythonw.exe')
                subprocess.Popen([str(executable),str(root/'scripts'/'run_service.py')],
                                 cwd=root,creationflags=subprocess.CREATE_NO_WINDOW)
                log.info('托盘启动后台打印服务')
                for _ in range(20):
                    if stopping.wait(.5): return
                    try: request('GET','/api/status'); break
                    except httpx.ConnectError: continue
            except Exception: log.exception('读取打印服务失败')
            while not stopping.is_set():
                refresh()
                if stopping.wait(15): break
        finally:
            log.info('托盘观察线程结束')
    thread = threading.Thread(target=observe,daemon=True)
    try:
        thread.start()
        icon.run()
    finally:
        stopping.set()
        thread.join(timeout=35)
        if not thread.is_alive(): client.close()
        kernel.CloseHandle(mutex)


if __name__ == '__main__': run()
