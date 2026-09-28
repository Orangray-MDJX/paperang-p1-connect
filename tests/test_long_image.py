import asyncio
import io
import time
import httpx
import pytest
from PIL import Image
from paperang_p1.config import Config
from paperang_p1.long_image import render, MAX_ROWS
from paperang_p1.service import create_ipp_app
from paperang_p1.job_queue import JobQueue
from test_jobs import Manager


def png(size=(100,1000), mode='RGB'):
    image=Image.new(mode,size,'white'); image.putpixel((min(10,size[0]-1),min(10,size[1]-1)),0 if mode=='L' else (0,0,0))
    buf=io.BytesIO(); image.save(buf,'PNG'); return buf.getvalue()


def test_ratio_trim_and_limit():
    _,rows=render(png(),Config()); assert rows==3840
    _,rows=render(png(),Config(),True); assert rows==384
    with pytest.raises(ValueError,match='16000'): render(png((10,1000)),Config())
    rgba=Image.new('RGBA',(384,3),(0,0,0,0)); b=io.BytesIO();rgba.save(b,'PNG')
    out,_=render(b.getvalue(),Config()); assert Image.open(io.BytesIO(out)).getextrema()==(255,255)


def test_preview_confirmation_persists_idempotently_and_capability_isolation(tmp_path):
    async def run():
        cfg=Config(); mgr=Manager();mgr.status=lambda:{'dpi':200}
        q=JobQueue(mgr,db_path=tmp_path/'jobs.db');app=create_ipp_app(cfg,mgr,q)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local') as c:
            h={'X-P1-Upload':'1'}
            assert (await c.post('/long-image/preview',content=png())).status_code==403
            p=(await c.post('/long-image/preview',content=png(),headers=h)).json()
            assert q.list()==[]
            h['X-P1-Token']=p['token']
            first_token=p['token']
            assert (await c.get('/long-image/preview.png',headers=h)).status_code==200
            a=(await c.post('/long-image/submit',headers=h)).json()
            b=(await c.post('/long-image/submit',headers=h)).json();assert a==b
            assert len(q.list())==1 and q.get(a['job_id'])['source']=='lan-image'
            assert (await c.get('/long-image/job',headers={'X-P1-Token':'x'*43})).status_code==404
            assert (await c.post('/long-image/cancel',headers=h)).status_code==200
            assert q.get(a['job_id'])['state']=='cancelled'
            p=(await c.post('/long-image/preview',content=png(),headers=h)).json();h['X-P1-Token']=p['token']
            q.db.execute('UPDATE image_previews SET created=? WHERE job_id IS NULL',(time.time()-1801,));q.db.commit()
            assert (await c.post('/long-image/submit',headers=h)).status_code==410
            assert (await c.post('/long-image/preview',content=png(),headers={**h,'Origin':'http://evil'})).status_code==403
        await q.stop()
        q=JobQueue(mgr,db_path=tmp_path/'jobs.db');assert len(q.list())==1
        app=create_ipp_app(cfg,mgr,q)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local') as c:
            repeated=(await c.post('/long-image/submit',headers={'X-P1-Token':first_token,'X-P1-Upload':'1'})).json()
            assert repeated==a and len(q.list())==1
        await q.stop()
    asyncio.run(run())


def test_nested_media_col_and_catalog():
    from paperang_p1.ipp import collection, parse, media_catalog
    from test_ipp import request
    attrs=collection('media-col',[('media-size',0x34,[('x-dimension',0x21,5700),('y-dimension',0x21,30000)])])
    result=parse(request(4,attrs))[3]
    assert result['media-col'][0]['media-size'][0]['y-dimension']==[30000]
    assert len(media_catalog(Config()))==3
    assert len(media_catalog(Config(ipp_long_media=True)))==6


def test_exif_orientation_and_pixel_limit(monkeypatch):
    image=Image.new('RGB',(80,160),'white');exif=image.getexif();exif[274]=6
    b=io.BytesIO();image.save(b,'JPEG',exif=exif)
    _,rows=render(b.getvalue(),Config());assert rows==192
    monkeypatch.setattr('paperang_p1.long_image.MAX_PIXELS',100)
    with pytest.raises(ValueError,match='2000'):render(png(),Config())


def test_cancel_stops_at_bitmap_boundary_without_finish_or_status_query():
    from paperang_p1.device_a5 import A5Device
    from paperang_p1.device import DeviceError
    from test_a5 import FakeTransport
    async def run():
        d=A5Device(FakeTransport(),Config());sent=[]
        async def ack(cmd,*args,**kwargs):sent.append(cmd)
        d.ack=ack
        with pytest.raises(DeviceError,match='用户中止'):
            await d.print_rows(b'\x00'*(48*100),cancel_check=lambda:sent.count(0x051b)>=2)
        assert sent.count(0x051b)==2 and 0x051a not in sent and 0x050d not in sent
    asyncio.run(run())


def test_media_validation_matches_experimental_catalog(tmp_path):
    from paperang_p1.ipp import collection, parse
    from test_ipp import request
    async def run():
        cfg=Config();m=Manager();m.status=lambda:{'connected':False,'last_error':None}
        q=JobQueue(m,db_path=tmp_path/'media.db');app=create_ipp_app(cfg,m,q)
        attrs=collection('media-col',[('media-size',0x34,[('x-dimension',0x21,5700),('y-dimension',0x21,30000)])])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local') as c:
            r=await c.post('/ipp/print',content=request(4,attrs))
            assert int.from_bytes(r.content[2:4],'big')==0x040b
            cfg.ipp_long_media=True
            r=await c.post('/ipp/print',content=request(4,attrs))
            assert int.from_bytes(r.content[2:4],'big')==0
            result=parse((await c.post('/ipp/print',content=request(11))).content)[3]
            assert len(result['media-col-database'])==6
            quantized=collection('media-col',[('media-size',0x34,[('x-dimension',0x21,5715),('y-dimension',0x21,10008)])])
            r=await c.post('/ipp/print',content=request(4,quantized))
            assert int.from_bytes(r.content[2:4],'big')==1
            from paperang_p1.ipp import attribute
            r=await c.post('/ipp/print',content=request(4,attribute('media-col',0x44,'invalid')))
            assert int.from_bytes(r.content[2:4],'big')==0x0400
        await q.stop()
    asyncio.run(run())


def test_http_upload_limit_without_job_creation(tmp_path,monkeypatch):
    monkeypatch.setattr('paperang_p1.long_image.MAX_BYTES',100)
    async def run():
        m=Manager();m.status=lambda:{'dpi':200};q=JobQueue(m,db_path=tmp_path/'limit.db')
        app=create_ipp_app(Config(),m,q)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local') as c:
            r=await c.post('/long-image/preview',content=b'x'*101,headers={'X-P1-Upload':'1'})
            assert r.status_code==413 and not q.list()
        await q.stop()
    asyncio.run(run())
