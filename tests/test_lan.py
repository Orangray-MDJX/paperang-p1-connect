import asyncio
import struct
import httpx
import pytest
from paperang_p1.urf_raster import decode
from paperang_p1.service import create_ipp_app
from paperang_p1.ipp import attribute, parse
from paperang_p1.config import Config
from paperang_p1.job_queue import JobQueue
from test_jobs import Manager


def urf(body=b'\x01\xff\x00\xff'):
    header=bytearray(32); header[0]=8
    struct.pack_into('>III',header,12,2,2,300)
    return b'UNIRAST\0'+struct.pack('>I',1)+header+body


def test_urf_literal_repeat_and_invalid_dimensions():
    image=decode(urf())[0]
    assert image.size==(2,2) and image.getpixel((0,1))==0 and image.getpixel((1,1))==255
    with pytest.raises(ValueError): decode(urf()[:-1])
    with pytest.raises(ValueError): decode(urf(b'\x02\xff\x00\xff'))


def test_lan_exposes_ipp_only_and_returns_reachable_job_uris(tmp_path):
    async def run():
        cfg=Config(lan_enabled=True,lan_address='192.0.2.10',lan_network='192.0.2.0/24')
        mgr=Manager(); mgr.status=lambda:{'connected':False,'last_error':None}
        jobs=JobQueue(mgr,db_path=tmp_path/'jobs.db'); app=create_ipp_app(cfg,mgr,jobs)
        request=struct.pack('>BBHI',2,0,5,1)+b'\x01'+attribute('attributes-charset',0x47,'utf-8')+b'\x03'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('192.0.2.22',1234)),base_url='http://192.0.2.10:8631') as c:
            assert (await c.get('/api/config')).status_code==404
            assert (await c.get('/docs')).status_code==404
            assert (await c.get('/assets/fluent.css')).status_code==200
            attrs=parse((await c.post('/ipp/print',content=request)).content)[3]
            assert attrs['job-uri'][0].startswith('ipp://192.0.2.10:8631/')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('198.51.100.9',1234)),base_url='http://192.0.2.10:8631') as c:
            assert (await c.post('/ipp/print',content=request)).status_code==403
        await jobs.stop()
    asyncio.run(run())
