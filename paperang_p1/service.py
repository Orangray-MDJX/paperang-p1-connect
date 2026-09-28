"""Headless service entry point; tray uses the same runtime."""
import asyncio
import ctypes
import logging
from logging.handlers import RotatingFileHandler
import time
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response, FileResponse
from pathlib import Path
import ipaddress
from .lan_discovery import Discovery
from .api import create_app
from .config import APP_DIR, Config
from .connection_manager import DeviceManager
from .ipp import install_routes
from .job_queue import JobQueue
from .spool_server import SpoolServer


class Runtime:
    def __init__(self, cfg, on_event=None):
        self.cfg = cfg
        self.mgr = DeviceManager(cfg)
        self.on_event = on_event
        self.jobs = self.spool = None
        self.servers = []
        self.tasks = []
        self.started_at = time.monotonic()
        self.mutex = None
        self.discovery = None

    @property
    def should_exit(self): return any(s.should_exit for s in self.servers)

    @should_exit.setter
    def should_exit(self, value):
        for s in self.servers: s.should_exit = value

    async def start(self):
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        k.CreateMutexW.restype = ctypes.c_void_p
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        self.k = k
        self.mutex = k.CreateMutexW(None, False, 'Local\\PaperangP1ConnectService')
        if not self.mutex: raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:
            k.CloseHandle(self.mutex); self.mutex = None
            raise RuntimeError('Paperang P1 服务已经运行')
        self.jobs = JobQueue(self.mgr, self.on_event)
        self.spool = SpoolServer(self.cfg, self.jobs)
        app = create_app(self.cfg, self.mgr, self.jobs)
        install_routes(app, self.cfg, self.mgr, self.jobs)
        self.jobs.start()
        try:
            await self.spool.start()
            ipp_app = create_ipp_app(self.cfg, self.mgr, self.jobs)
            endpoints = [(self.cfg.api_port, '127.0.0.1', app), (self.cfg.ipp_port, '0.0.0.0' if self.cfg.lan_enabled else '127.0.0.1', ipp_app)]
            for port, host, endpoint in endpoints:
                server = uvicorn.Server(uvicorn.Config(endpoint, host=host, port=port, log_config=None, timeout_graceful_shutdown=5))
                self.servers.append(server)
                self.tasks.append(asyncio.create_task(server.serve()))
            for _ in range(100):
                if all(s.started for s in self.servers): break
                if any(t.done() for t in self.tasks): raise RuntimeError('API/IPP 端口绑定失败')
                await asyncio.sleep(.05)
            else: raise RuntimeError('API/IPP 启动超时')
            if self.cfg.lan_enabled:
                self.discovery = Discovery(self.cfg)
                await self.discovery.start()
                logging.getLogger(__name__).info('LAN printer advertised: %s:%s', self.cfg.lan_address, self.cfg.ipp_port)
            self.monitor = asyncio.create_task(self._monitor())
        except BaseException:
            await self.close(); raise

    async def _monitor(self):
        while True:
            try:
                async with self.mgr.operation_lock:
                    await self.mgr.ensure_connected()
            except Exception as e:
                logging.getLogger(__name__).warning('设备等待唤醒: %s', e)
            await asyncio.sleep(30)

    async def wait(self):
        try: await asyncio.wait(self.tasks, return_when=asyncio.FIRST_COMPLETED)
        finally: await self.close()

    async def close(self):
        self.should_exit = True
        if self.discovery:
            await self.discovery.close(); self.discovery = None
        monitor = getattr(self, 'monitor', None)
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        if self.tasks: await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.spool:
            await self.spool.stop(); self.spool = None
        if self.jobs:
            await self.jobs.stop(); self.jobs = None
        await self.mgr.disconnect()
        if self.mutex:
            self.k.CloseHandle(self.mutex); self.mutex = None


def create_ipp_app(cfg, mgr, jobs):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    @app.get('/assets/{name}', include_in_schema=False)
    async def asset(name: str):
        if name not in {'logo.svg', 'fluent.css'}:
            raise HTTPException(404, '资源不存在')
        return FileResponse(Path(__file__).parent / 'static' / name)
    @app.get('/test-page', include_in_schema=False)
    async def test_page():
        return FileResponse(Path(__file__).parent / 'static' / 'test-page.html')
    @app.middleware('http')
    async def restrict_network(request: Request, call_next):
        address = ipaddress.ip_address(request.client.host)
        if not address.is_loopback and (not cfg.lan_enabled or address not in ipaddress.ip_network(cfg.lan_network)):
            return Response(status_code=403)
        return await call_next(request)
    install_routes(app, cfg, mgr, jobs)
    from .long_image import install_routes as install_images
    install_images(app, cfg, mgr, jobs)
    return app


def setup_logging(filename="service.log"):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(APP_DIR / filename, maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(name)s %(message)s')


async def main():
    runtime = Runtime(Config.load())
    await runtime.start()
    await runtime.wait()


if __name__ == '__main__':
    setup_logging()
    asyncio.run(main())
