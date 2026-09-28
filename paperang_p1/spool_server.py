# -*- coding: utf-8 -*-
"""Windows 打印假脱机接收服务：监听 127.0.0.1:9100（RAW 语义）。

配合安装脚本创建的 "Microsoft PS Class Driver + Standard TCP/IP Port" 打印机：
每个 TCP 连接 = 一个打印任务，连接关闭即任务结束。PostScript 流经
Ghostscript 光栅化为 203dpi 位图后进入打印队列。
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from .config import APP_DIR, Config, find_ghostscript
from .job_queue import JobQueue, PrintJob

log = logging.getLogger(__name__)

MAX_JOB_BYTES = 64 * 1024 * 1024
IDLE_TIMEOUT_S = 300.0


class SpoolServer:
    def __init__(self, cfg: Config, jobs: JobQueue) -> None:
        self.cfg = cfg
        self.jobs = jobs
        self._server: asyncio.AbstractEventServer | None = None
        self.jobs_received = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle, host="127.0.0.1", port=self.cfg.spool_port)
        log.info("假脱机服务监听 127.0.0.1:%d（Windows 打印机端口）", self.cfg.spool_port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(self, reader: asyncio.StreamReader,
                      writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        log.info("收到打印连接 %s", peer)
        buf = bytearray()
        try:
            while len(buf) < MAX_JOB_BYTES:
                chunk = await asyncio.wait_for(reader.read(65536), IDLE_TIMEOUT_S)
                if not chunk:
                    break
                buf.extend(chunk)
        except asyncio.TimeoutError:
            log.warning("任务读取超时，按已收内容处理")
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

        if not buf:
            log.info("空任务，忽略")
            return
        self.jobs_received += 1
        title = f"Windows打印 #{self.jobs_received} ({len(buf)}B)"

        spool_dir = APP_DIR / "spool"
        spool_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        src = spool_dir / f"job-{stamp}.ps"
        try:
            src.write_bytes(bytes(buf))
            # 只保留最近 20 个任务文件
            olds = sorted(spool_dir.glob("job-*.ps"))
            for old in olds[:-20]:
                old.unlink(missing_ok=True)
        except Exception:
            log.exception("保存假脱机文件失败")

        try:
            pages = await self._render_pages(bytes(buf))
        except Exception as e:  # noqa: BLE001
            log.exception("光栅化失败: %s", e)
            self.jobs._emit("error", f"{title} 光栅化失败: {e}")
            return
        self.jobs.submit(PrintJob(title=title, pages=pages, source="spool"))

    async def _render_pages(self, data: bytes) -> list[bytes]:
        from .render import prepare, rasterize_document

        gs = find_ghostscript(self.cfg)
        if not gs:
            raise RuntimeError("未找到 Ghostscript（winget 无包，请从官网安装或配置 gs_path）")
        pages = await asyncio.to_thread(rasterize_document, data, gs)
        out = []
        for img in pages:
            out.append(await asyncio.to_thread(self._page_png, img, self.cfg.dither,
                                               self.cfg.threshold))
        return out

    @staticmethod
    def _page_png(img, dither: str, threshold: int) -> bytes:
        import io

        from PIL import Image

        from .render import prepare
        p = prepare(img, dither=dither, threshold=threshold)
        buf = io.BytesIO()
        p.convert("L").save(buf, "PNG")
        return buf.getvalue()
