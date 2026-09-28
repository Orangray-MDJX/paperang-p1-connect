"""质量档位（浓度 density 0-100）全链路验证。

各端入口 → SQLite jobs.density → A5 0x0511 帧字节 → 打印机解析应答。
打印机端为模拟固件：按 P1 01.03.18 抓包行为逐条应答 type2 帧，
并记录主机下发的 0x0511 载荷用于与用户选择比对。
"""
import asyncio
import base64
import io
import socket
import struct

import httpx
import pytest
import uvicorn
from PIL import Image

from paperang_p1 import cli, mcp_server
from paperang_p1.api import create_app
from paperang_p1.config import Config
from paperang_p1.device_a5 import A5Device
from paperang_p1.ipp import attribute, install_routes as install_ipp
from paperang_p1.job_queue import JobQueue
from paperang_p1.long_image import install_routes as install_long_image
from paperang_p1.protocol_a5 import Parser, build, tlv


class FakePrinter:
    """模拟打印机固件：解析主机 A5 帧，逐条回 CRC 正确的应答帧。"""

    name = 'usb'

    def __init__(self):
        self.parser = Parser()
        self.commands = []          # (command, content) 主机→打印机全部命令
        self.on_bytes = None
        self.on_disconnected = None
        self.is_open = True
        self.values = {
            0x0115: b'01.03.18',
            0x0102: b'P1FAKE0000000001',
            0x0114: (1024).to_bytes(2, 'little'),
            0x0504: (200).to_bytes(2, 'little'),
            0x0502: b'\x01\x02\x00\x39\x00',
            0x050c: b'\x01',
            0x050d: b'\x01',
            0x010b: (990).to_bytes(2, 'little'),
            0x0109: (0).to_bytes(2, 'little'),
        }

    async def open(self):
        pass

    async def close(self):
        self.is_open = False
        if self.on_disconnected:
            self.on_disconnected()

    async def write(self, data):
        for frame in self.parser.feed(data):
            self.commands.append((frame.command, frame.content))
            value = self.values.get(frame.command)
            self.on_bytes(build(frame.command, tlv(1, value if value is not None else b''),
                                message_type=2))


class FakeManager:
    def __init__(self, device):
        self.operation_lock = asyncio.Lock()
        self.device = device
        self.last_seen = 0.0

    async def ensure_connected(self, transport=None):
        if self.device.state != 'ready':
            await self.device.connect()
        return self.device

    async def disconnect(self):
        await self.device.close()

    def status(self):
        return {'connected': self.device.state == 'ready', 'printable': True,
                'lid_closed': True, 'paper_present': True, 'state': self.device.state,
                'protocol': 'a5', 'transport': 'usb', 'last_error': None}


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Harness:
    def __init__(self, tmp_path):
        self.printer = FakePrinter()
        self.cfg = Config()
        self.port = free_port()
        self.cfg.api_port = self.port
        self.device = A5Device(self.printer, self.cfg)
        self.mgr = FakeManager(self.device)
        self.jobs = JobQueue(self.mgr, db_path=tmp_path / 'jobs.db')
        self.app = create_app(self.cfg, self.mgr, self.jobs)
        install_ipp(self.app, self.cfg, self.mgr, self.jobs)
        install_long_image(self.app, self.cfg, self.mgr, self.jobs)
        self.server = None

    def client(self, **kwargs):
        # 进程内 ASGI 客户端：绝大多数用例不需要真实端口，
        # 避免与本机正在运行的服务或并行测试竞争套接字。
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                 base_url='http://test', trust_env=False,
                                 timeout=10, **kwargs)

    async def start(self):
        # 仅 CLI/MCP 用例需要真实监听端口（它们各自构造 HTTP 客户端）；
        # free_port 存在 TOCTOU，绑定失败时换端口重试。
        last_error = None
        for _ in range(3):
            self.port = free_port()
            self.cfg.api_port = self.port
            try:
                await self._serve_once()
                return
            except RuntimeError as e:
                last_error = e
        raise last_error

    async def _serve_once(self):
        self.server = uvicorn.Server(uvicorn.Config(
            self.app, host='127.0.0.1', port=self.port, log_config=None))
        self.task = asyncio.create_task(self.server.serve())
        for _ in range(200):
            if self.server.started:
                return
            if self.task.done():
                raise RuntimeError('测试服务端口绑定失败') from self.task.exception()
            await asyncio.sleep(.02)
        raise RuntimeError('测试服务启动超时')

    async def stop(self):
        if self.server is not None:
            self.server.should_exit = True
            await asyncio.gather(self.task, return_exceptions=True)
        await self.jobs.stop()

    def mark(self):
        return len(self.printer.commands)

    def density_after(self, mark):
        sent = [content for cmd, content in self.printer.commands[mark:] if cmd == 0x0511]
        assert len(sent) == 1, f'期望恰好一次浓度设置，实际 {len(sent)} 次'
        assert len(sent[0]) == 1, f'0x0511 载荷应为单字节，实际 {sent[0].hex()}'
        return sent[0][0]


async def wait_terminal(client, job_id, timeout=15):
    for _ in range(300):
        job = (await client.get(f'/api/jobs/{job_id}')).json()
        if job['state'] in ('completed', 'failed', 'unknown', 'held', 'cancelled'):
            return job
        await asyncio.sleep(.05)
    raise AssertionError(f'任务 {job_id} 未在超时内结束: {job["state"]}')


def tiny_png():
    image = Image.new('L', (384, 24), 255)
    for x in range(384):
        image.putpixel((x, 12), 0)
    buf = io.BytesIO(); image.save(buf, 'PNG')
    return buf.getvalue()


def tiny_jpeg():
    image = Image.new('L', (96, 24), 255)
    for x in range(96):
        image.putpixel((x, 12), 0)
    buf = io.BytesIO(); image.save(buf, 'JPEG')
    return buf.getvalue()


def ipp_print_job(quality=None):
    attrs = b'\x01'
    attrs += attribute('attributes-charset', 0x47, 'utf-8')
    attrs += attribute('attributes-natural-language', 0x48, 'en')
    attrs += attribute('printer-uri', 0x45, 'ipp://127.0.0.1/ipp/print')
    attrs += attribute('job-name', 0x42, 'quality-test')
    attrs += attribute('document-format', 0x49, 'image/jpeg')
    if quality is not None:
        attrs += attribute('print-quality', 0x23, quality)
    return struct.pack('>BBHI', 1, 1, 2, 1) + attrs + b'\x03' + tiny_jpeg()


@pytest.mark.parametrize('level', [0, 30, 80, 100])
def test_api_density_levels_reach_printer_byte_exact(tmp_path, level):
    async def run():
        h = Harness(tmp_path)
        try:
            async with h.client() as c:
                mark = h.mark()
                r = await c.post('/api/print/text', json={'text': f'档位{level}', 'density': level})
                job = await wait_terminal(c, r.json()['job_id'])
                assert job['state'] == 'completed', job
                assert job['density'] == level
                assert h.density_after(mark) == level
        finally:
            await h.stop()
    asyncio.run(run())


def test_api_unset_density_uses_global_default(tmp_path):
    async def run():
        h = Harness(tmp_path)
        try:
            async with h.client() as c:
                mark = h.mark()
                r = await c.post('/api/print/image', json={'b64': base64.b64encode(tiny_png()).decode()})
                job = await wait_terminal(c, r.json()['job_id'])
                assert job['state'] == 'completed' and job['density'] is None
                assert h.density_after(mark) == h.cfg.density
        finally:
            await h.stop()
    asyncio.run(run())


@pytest.mark.parametrize('bad', [-1, 101, 200])
def test_api_rejects_out_of_range_density(tmp_path, bad):
    async def run():
        h = Harness(tmp_path)
        try:
            async with h.client() as c:
                for body in ({'text': 'x', 'density': bad},
                             {'b64': base64.b64encode(tiny_png()).decode(), 'density': bad}):
                    assert (await c.post('/api/print/text', json=body)).status_code == 422
                assert (await c.get('/api/jobs')).json() == []
        finally:
            await h.stop()
    asyncio.run(run())


def test_config_density_change_applies_to_new_jobs(tmp_path, monkeypatch):
    async def run():
        import paperang_p1.config as config_module
        monkeypatch.setattr(config_module, 'CONFIG_PATH', tmp_path / 'config.json')
        monkeypatch.setattr(config_module, 'APP_DIR', tmp_path)
        h = Harness(tmp_path)
        try:
            async with h.client() as c:
                assert (await c.put('/api/config', json={'density': 40})).status_code == 200
                mark = h.mark()
                r = await c.post('/api/print/text', json={'text': '默认档跟随配置'})
                job = await wait_terminal(c, r.json()['job_id'])
                assert job['state'] == 'completed' and job['density'] is None
                assert h.density_after(mark) == 40
                assert (await c.put('/api/config', json={'density': 101})).status_code == 400
        finally:
            await h.stop()
    asyncio.run(run())


def test_cli_density_flag_reaches_printer(tmp_path):
    async def run():
        h = Harness(tmp_path); await h.start()
        try:
            args = cli.build_parser().parse_args(['print-text', 'CLI 档位', '--density', '30'])
            assert await cli.execute(h.cfg, args) == 0
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{h.port}', trust_env=False, timeout=30) as c:
                jid = (await c.get('/api/jobs')).json()[0]['id']
                job = await wait_terminal(c, jid)
                assert job['state'] == 'completed' and job['density'] == 30
                assert h.density_after(0) == 30
        finally:
            await h.stop()
    asyncio.run(run())


def test_mcp_density_parameter_reaches_printer(tmp_path, monkeypatch):
    async def run():
        h = Harness(tmp_path); await h.start()
        monkeypatch.setattr(mcp_server, 'API', f'http://127.0.0.1:{h.port}')
        try:
            mark = h.mark()
            # fastmcp 在工作线程中执行工具（同步 httpx），与真实部署一致
            result = await asyncio.to_thread(mcp_server.paperang_print_text, 'MCP 档位', None, 25)
            jid = __import__('json').loads(result)['job_id']
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{h.port}', trust_env=False, timeout=30) as c:
                job = await wait_terminal(c, jid)
                assert job['state'] == 'completed' and job['density'] == 25
                assert h.density_after(mark) == 25
        finally:
            await h.stop()
    asyncio.run(run())


def test_long_image_has_no_quality_selector_uses_default(tmp_path):
    async def run():
        h = Harness(tmp_path)
        try:
            async with h.client(headers={'X-P1-Upload': '1', 'Origin': 'http://test'}) as c:
                r = await c.post('/long-image/preview', content=tiny_png())
                token = r.json()['token']
                jid = (await c.post('/long-image/submit', headers={'X-P1-Token': token})).json()['job_id']
                job = await wait_terminal(c, jid)
                assert job['state'] == 'completed' and job['density'] is None
                assert h.density_after(0) == h.cfg.density
        finally:
            await h.stop()
    asyncio.run(run())


@pytest.mark.parametrize('quality,expected', [(3, 50), (4, 80), (5, 100)])
def test_ipp_print_quality_maps_to_density(tmp_path, quality, expected):
    async def run():
        h = Harness(tmp_path)
        try:
            async with h.client() as c:
                mark = h.mark()
                r = await c.post('/ipp/print', content=ipp_print_job(quality),
                                 headers={'Content-Type': 'application/ipp'})
                assert r.status_code == 200
                jobs = (await c.get('/api/jobs')).json()
                job = await wait_terminal(c, jobs[0]['id'])
                assert job['state'] == 'completed', job
                assert job['density'] == expected
                assert h.density_after(mark) == expected
        finally:
            await h.stop()
    asyncio.run(run())


def test_ipp_without_quality_uses_default(tmp_path):
    async def run():
        h = Harness(tmp_path)
        try:
            async with h.client() as c:
                mark = h.mark()
                r = await c.post('/ipp/print', content=ipp_print_job(None),
                                 headers={'Content-Type': 'application/ipp'})
                assert r.status_code == 200
                jobs = (await c.get('/api/jobs')).json()
                job = await wait_terminal(c, jobs[0]['id'])
                assert job['state'] == 'completed' and job['density'] is None
                assert h.density_after(mark) == h.cfg.density
        finally:
            await h.stop()
    asyncio.run(run())


def test_density_command_sequence_matches_capture_order(tmp_path):
    async def run():
        h = Harness(tmp_path)
        try:
            async with h.client() as c:
                mark = h.mark()
                r = await c.post('/api/print/text', json={'text': '顺序', 'density': 60})
                job = await wait_terminal(c, r.json()['job_id'])
                assert job['state'] == 'completed'
                session = {0x0511, 0x0516, 0x0519, 0x051a, 0x051b, 0x0520}
                order = [cmd for cmd, _ in h.printer.commands[mark:] if cmd in session]
                assert order[:3] == [0x0511, 0x0520, 0x0519]     # 浓度先于会话开始
                assert set(order[3:-2]) == {0x051b} and order[-2:] == [0x051a, 0x0516]
        finally:
            await h.stop()
    asyncio.run(run())
