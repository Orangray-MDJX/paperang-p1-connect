# -*- coding: utf-8 -*-
"""本地 HTTP API（仅绑定 127.0.0.1）。

端点::
    GET  /api/status                       设备与队列状态
    GET  /api/scan                         BLE 扫描
    POST /api/connect {transport?}         连接设备
    POST /api/disconnect                   断开
    POST /api/print/text   {text,...}      打印文本
    POST /api/print/image  (base64/file)   打印图片
    POST /api/print/file   {path}          打印 PS/PDF/图片文件
    POST /api/selftest                     自检页
    GET  /api/config  /  PUT /api/config   配置读写
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Literal
from fastapi.responses import FileResponse, Response

from .config import Config, find_ghostscript
from .job_queue import JobQueue, PrintJob

log = logging.getLogger(__name__)


class PrintTextReq(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    font_size: int | None = Field(default=None, ge=1, le=384)
    dither: Literal['floyd-steinberg', 'atkinson', 'threshold'] | None = None
    density: int | None = Field(default=None, ge=0, le=100)


class PrintImageReq(BaseModel):
    b64: str | None = None
    path: str | None = None
    density: int | None = Field(default=None, ge=0, le=100)
    dither: Literal['floyd-steinberg', 'atkinson', 'threshold'] | None = None
    invert: bool = False


class PrintFileReq(BaseModel):
    path: str
    density: int | None = Field(default=None, ge=0, le=100)
    dither: Literal['floyd-steinberg', 'atkinson', 'threshold'] | None = None


class PowerOffReq(BaseModel):
    seconds: int = Field(ge=0, le=65535)


class ConnectReq(BaseModel):
    transport: Literal['auto','usb','spp','ble','vendor'] | None = None


def create_app(cfg: Config, mgr, jobs: JobQueue) -> FastAPI:
    app = FastAPI(title="Paperang P1 服务", version="0.1.0")
    restart_pending = False

    @app.get('/', include_in_schema=False)
    async def dashboard():
        return FileResponse(Path(__file__).parent / 'static' / 'index.html', headers={'Cache-Control': 'no-store'})

    @app.get('/assets/{name}', include_in_schema=False)
    async def asset(name: str):
        if name not in {'logo.svg', 'fluent.css'}:
            raise HTTPException(404, '资源不存在')
        return FileResponse(Path(__file__).parent / 'static' / name)

    @app.get('/api/lan-qr', include_in_schema=False)
    async def lan_qr():
        if not cfg.lan_enabled or restart_pending:
            raise HTTPException(409, '局域网打印尚未生效，请重启服务')
        import qrcode
        url = f'http://{cfg.lan_address}:{cfg.ipp_port}/long-image'
        image = qrcode.make(url, box_size=8, border=2)
        data = io.BytesIO()
        image.save(data, format='PNG')
        return Response(data.getvalue(), media_type='image/png', headers={'Cache-Control': 'no-store'})

    def _png_page(img_l, dither: str | None, invert: bool) -> bytes:
        from PIL import Image

        from .render import prepare
        p = prepare(img_l, dither=dither or cfg.dither,
                    threshold=cfg.threshold, invert=invert)
        buf = io.BytesIO()
        p.convert("L").save(buf, "PNG")
        return buf.getvalue()

    @app.get("/api/status")
    async def status():
        st = mgr.status()
        st.update({"queue": {
            "pending": jobs.stats.pending, "done": jobs.stats.done,
            "failed": jobs.stats.failed, "printing": jobs.stats.printing,
            "last_error": jobs.stats.last_error,
        }, "ghostscript": bool(find_ghostscript(cfg)), "lan": {"enabled": cfg.lan_enabled, "restart_required": restart_pending, "address": cfg.lan_address, "ipp_url": f"http://{cfg.lan_address}:{cfg.ipp_port}/ipp/print" if cfg.lan_enabled else None, "long_image_url": f"http://{cfg.lan_address}:{cfg.ipp_port}/long-image" if cfg.lan_enabled else None}})
        return st

    @app.get("/api/scan")
    async def scan(timeout: float = 6.0):
        from .transport_ble import scan_paperang

        try:
            found = await scan_paperang(timeout, cfg.ble_name_prefixes)
            return {"devices": found}
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"扫描失败: {e}") from e

    @app.post("/api/connect")
    async def connect(req: ConnectReq):
        try:
            async with mgr.operation_lock:
                dev = await mgr.ensure_connected(req.transport)
            return {"ok": True, "transport": dev.transport.name}
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"连接失败: {e}") from e

    @app.post("/api/disconnect")
    async def disconnect():
        async with mgr.operation_lock:
            await mgr.disconnect()
        # 让位给手机等临时主机：断开后暂停自动重连 5 分钟，
        # 打印任务或显式 connect 立即恢复。
        mgr.pause(300)
        return {"ok": True, "auto_reconnect_paused_s": 300}

    @app.post('/api/power-off')
    async def power_off(req: PowerOffReq):
        async with mgr.operation_lock:
            try:
                dev = await mgr.ensure_connected()
                await dev.set_power_down_time(req.seconds)
            except Exception as e:
                raise HTTPException(502, str(e)) from e
            cfg.disable_auto_poweroff = req.seconds == 0
            cfg.save()
            return {'ok': True, 'power_down_time': dev.power_down_time}

    @app.post("/api/selftest")
    async def selftest(density: int | None = Query(default=None, ge=0, le=100), dither: Literal['floyd-steinberg','atkinson','threshold'] | None = None):
        from .render import selftest_image

        png = _png_page(selftest_image(), dither, False)
        job_id = jobs.submit(PrintJob(title="API 自检页", pages=[png],
                             density=density, source="api"))
        return {"ok": True, "queued": 1, "job_id": job_id}

    @app.post("/api/print/text")
    async def print_text(req: PrintTextReq):
        from .render import text_image

        img = text_image(req.text, cfg.font_path,
                         req.font_size or cfg.font_size)
        png = _png_page(img, req.dither, False)
        job_id = jobs.submit(PrintJob(title=f"文本: {req.text[:24]!r}", pages=[png],
                             density=req.density, source="api"))
        return {"ok": True, "queued": 1, "job_id": job_id}

    @app.post("/api/print/image")
    async def print_image(req: PrintImageReq):
        from .render import load_image

        if req.b64:
            img = load_image(base64.b64decode(req.b64))
        elif req.path:
            p = Path(req.path)
            if not p.exists():
                raise HTTPException(404, f"文件不存在: {p}")
            img = load_image(p)
        else:
            raise HTTPException(400, "需要 b64 或 path 之一")
        png = _png_page(img, req.dither, req.invert)
        job_id = jobs.submit(PrintJob(title="图片(API)", pages=[png],
                             density=req.density, source="api"))
        return {"ok": True, "queued": 1, "job_id": job_id}

    @app.post("/api/print/file")
    async def print_file(req: PrintFileReq):
        from .render import load_image, rasterize_document

        p = Path(req.path)
        if not p.exists():
            raise HTTPException(404, f"文件不存在: {p}")
        suffix = p.suffix.lower()
        if suffix in (".ps", ".eps", ".pdf"):
            gs = find_ghostscript(cfg)
            if not gs:
                raise HTTPException(500, "未安装 Ghostscript")
            pages = await __import__("asyncio").to_thread(
                rasterize_document, p, gs)
        elif suffix in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"):
            pages = [load_image(p)]
        else:
            raise HTTPException(400, f"不支持的类型: {suffix}")
        pngs = [_png_page(im, req.dither, False) for im in pages]
        job_id = jobs.submit(PrintJob(title=f"文件: {p.name}", pages=pngs,
                             density=req.density, source="api"))
        return {"ok": True, "queued": len(pngs), "job_id": job_id}

    @app.get("/api/config")
    async def get_config():
        return cfg.__dict__

    @app.put("/api/config")
    async def put_config(items: dict):
        nonlocal restart_pending
        from dataclasses import replace, fields
        names = {f.name for f in fields(cfg)}
        if set(items) - names: raise HTTPException(400, 'Unknown configuration fields')
        candidate = replace(cfg, **items)
        try: candidate.validate()
        except ValueError as e: raise HTTPException(400, str(e)) from e
        restart = any(k in items and items[k] != getattr(cfg,k) for k in ('api_port','ipp_port','spool_port','lan_enabled','lan_address','lan_network','lan_name'))
        reconnect = bool(set(items) & {'transport_pref','protocol_mode','spp_address','ble_address','usb_vid','usb_pid','rfcomm_data_channel','keepalive','keepalive_interval_s','disable_auto_poweroff'})
        async with mgr.operation_lock:
            candidate.save()
            if reconnect: await mgr.disconnect()
            cfg.__dict__.update(candidate.__dict__)
            restart_pending = restart_pending or restart
        return {'ok': True, 'restart_required': restart}

    @app.get('/api/jobs')
    async def list_jobs():
        return jobs.list()

    @app.get('/api/jobs/{job_id}')
    async def get_job(job_id: int):
        try: return jobs.get(job_id)
        except KeyError: raise HTTPException(404, '任务不存在') from None

    @app.post('/api/jobs/{job_id}/cancel')
    async def cancel_job(job_id: int):
        try: return jobs.cancel(job_id)
        except KeyError: raise HTTPException(404, '任务不存在') from None

    @app.post('/api/jobs/{job_id}/resume')
    async def resume_job(job_id: int):
        try: return jobs.resume(job_id)
        except KeyError: raise HTTPException(404, '任务不存在') from None
        except ValueError as e: raise HTTPException(409, str(e)) from e

    return app
