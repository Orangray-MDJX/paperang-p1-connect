# -*- coding: utf-8 -*-
"""vendor 桥端到端验证：连接 + 打印自检图。"""
import asyncio
import io
import sys

sys.path.insert(0, ".")

from paperang_p1.config import Config
from paperang_p1.vendor_bridge import VendorPrinter
from paperang_p1.render import prepare, selftest_image
from PIL import Image


async def main():
    cfg = Config.load()
    dev = VendorPrinter(cfg)
    await dev.connect(timeout=30)
    print("== 官方库已连接！")

    img = prepare(selftest_image(), dither=cfg.dither)
    buf = io.BytesIO()
    img.convert("L").save(buf, "PNG")
    print(f"== 打印自检图 {img.size} ...")
    await dev.print_png(buf.getvalue(), density=80, copies=1)
    print("== 打印指令完成，等待出纸...")
    await asyncio.sleep(15)
    await dev.close()
    print("== done")


asyncio.run(main())
