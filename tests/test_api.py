import asyncio
import httpx
from paperang_p1.api import create_app
from paperang_p1.config import Config
from paperang_p1.job_queue import JobQueue
from test_jobs import Manager


def test_bad_print_settings_cannot_enqueue_or_mutate_configuration(tmp_path):
    async def run():
        cfg = Config()
        manager = Manager()
        jobs = JobQueue(manager, db_path=tmp_path/'jobs.db')
        app = create_app(cfg, manager, jobs)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local') as client:
            assert (await client.get('/')).status_code == 200
            for payload in ({'text':'label','font_size':0},{'text':'label','density':101},{'text':''}):
                assert (await client.post('/api/print/text',json=payload)).status_code == 422
            assert (await client.post('/api/selftest?density=101')).status_code == 422
            for payload in ({'keepalive_interval_s':0},{'api_port':True},{'ipp_port':cfg.api_port},{'unexpected':1}):
                assert (await client.put('/api/config',json=payload)).status_code == 400
            assert cfg.keepalive_interval_s == 60 and cfg.api_port == 8765
            assert jobs.list() == []
        await jobs.stop()
    asyncio.run(run())


def test_lan_qr_only_when_enabled_and_assets_are_allowlisted(tmp_path):
    async def run():
        cfg = Config(lan_enabled=True, lan_address='192.0.2.10',
                     lan_network='192.0.2.0/24')
        jobs = JobQueue(Manager(), db_path=tmp_path/'jobs.db')
        app = create_app(cfg, jobs.mgr, jobs)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='http://local') as client:
            qr = await client.get('/api/lan-qr')
            assert qr.status_code == 200
            assert qr.headers['content-type'] == 'image/png'
            assert qr.content.startswith(b'\x89PNG\r\n\x1a\n')
            assert (await client.get('/assets/logo.svg')).status_code == 200
            assert (await client.get('/assets/fluent.css')).status_code == 200
            assert (await client.get('/assets/other')).status_code == 404
            cfg.lan_enabled = False
            assert (await client.get('/api/lan-qr')).status_code == 409
        await jobs.stop()
    asyncio.run(run())
