"""Temporary commissioning guard; yields USB ownership to the main service.

Once powered on, disable the timer with readback and monitor every 30 seconds.
Each check closes the device; access denied means another process owns it.
"""
import asyncio
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paperang_p1.config import APP_DIR, Config
from paperang_p1.device_a5 import A5Device
from paperang_p1.transport_usbprint import UsbPrintTransport


async def main():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        d = A5Device(UsbPrintTransport(), Config(disable_auto_poweroff=False))
        try:
            await d.connect()
            before = await d.get_power_down_time()
            if before != 0:
                await d.set_power_down_time(0)
            value = await d.get_power_down_time()
            message = f'USB ready; poweroff={value}s; battery={await d.get_battery()}%'
        except Exception as e:
            message = f'waiting for powered-on USB device: {e}'
        finally:
            await d.close()
        with (APP_DIR / 'keepalive-guard.log').open('a', encoding='utf-8') as out:
            out.write(time.strftime('%Y-%m-%d %H:%M:%S ') + message + '\n')
        await asyncio.sleep(30)


if __name__ == '__main__':
    asyncio.run(main())
