import asyncio
import io
import struct
import httpx
import pytest
from PIL import Image
from fastapi import FastAPI
from paperang_p1.config import Config
from paperang_p1.ipp import attribute, install_routes, parse, png_pages
from paperang_p1.pwg_raster import decode
from paperang_p1.job_queue import JobQueue


def test_ipp_reports_connected_printer_with_empty_media_as_stopped(tmp_path):
    async def run():
        mgr = Manager()
        mgr.status = lambda: {'connected':True, 'printable':False, 'lid_closed':True, 'paper_present':False, 'last_error':None}
        jobs = JobQueue(mgr, db_path=tmp_path/'media.db')
        app = FastAPI(); install_routes(app,Config(),mgr,jobs)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local') as client:
            result = await client.post('/ipp/print', content=request(11))
            attrs = parse(result.content)[3]
            assert attrs['printer-state'] == [5]
            assert attrs['printer-state-reasons'] == ['media-empty']
        await jobs.stop()
    asyncio.run(run())
from test_jobs import Manager


def raster(width=16, height=2, space=3, body=b'\x01\x01\x80'):
    h = bytearray(1796)
    for off, value in [(372,width),(376,height),(384,1),(388,1),(392,(width+7)//8),(396,0),(400,space),(420,1)]:
        struct.pack_into('>I',h,off,value)
    return b'RaS2' + h + body


def test_pwg_row_repeat_polarity_and_literal():
    image = decode(raster())[0]
    assert image.size == (16, 2)
    assert image.getpixel((0,0)) == 0 and image.getpixel((1,1)) == 255
    literal = decode(raster(height=1,body=b'\x00\xff\x80\x01'))[0]
    assert literal.getpixel((0,0)) == 0 and literal.getpixel((15,0)) == 0
    with pytest.raises(ValueError): decode(raster(body=b'\x02\x01\x80'))
    with pytest.raises(ValueError): decode(raster()[:-1])


def test_roll_page_trims_trailing_blank():
    image = Image.new('L',(384,800),255); image.putpixel((10,20),0)
    page = png_pages([image],Config())[0]
    assert Image.open(io.BytesIO(page)).height == 29


def request(op, attrs=b'', doc=b''):
    return struct.pack('>BBHI',2,0,op,123) + b'\x01' + attribute('attributes-charset',0x47,'utf-8') + attribute('attributes-natural-language',0x48,'en') + attrs + b'\x03' + doc


def test_ipp_windows_create_send_get_cancel(tmp_path):
    async def run():
        mgr = Manager(); mgr.status = lambda: {'connected':False,'last_error':None}
        jobs = JobQueue(mgr,db_path=tmp_path/'jobs.db')
        app=FastAPI(); install_routes(app,Config(),mgr,jobs)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local') as client:
            async def send(op,attrs=b'',doc=b''):
                r=await client.post('/ipp/print',content=request(op,attrs,doc))
                assert r.status_code==200
                return parse(r.content)
            _,status,rid,attrs,_=await send(11)
            assert status==0 and rid==123
            assert 'image/pwg-raster' in attrs['document-format-supported']
            _,status,_,attrs,_=await send(5,attribute('job-name',0x42,'native'))
            jid=attrs['job-id'][0]; assert status==0
            job_attr=attribute('job-id',0x21,jid)
            assert (await send(6,job_attr+attribute('last-document',0x22,True),raster()))[1]==0
            await asyncio.sleep(.01)
            assert (await send(9,job_attr))[3]['job-state']==[4]  # held, no hardware
            assert (await send(8,job_attr))[3]['job-state']==[7]
            assert (await send(9,attribute('job-id',0x21,999)))[1]==0x406
            assert (await send(2,attribute('document-format',0x49,'application/evil'),b'junk'))[1]==0x40a
        await jobs.stop()
    asyncio.run(run())
