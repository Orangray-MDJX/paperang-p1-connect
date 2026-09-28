"""LAN image preview capabilities; confirmation and job creation are atomic."""
import asyncio
import hashlib
import io
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageOps
from .render import prepare

MAX_BYTES = 40 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_ROWS = 16000
TTL = 1800


def render(data, cfg, trim=False):
    with Image.open(io.BytesIO(data)) as original:
        if original.format not in ('PNG', 'JPEG') or getattr(original, 'n_frames', 1) != 1:
            raise ValueError('仅支持单帧 PNG/JPEG')
        if original.width * original.height > MAX_PIXELS:
            raise ValueError('图片超过2000万像素')
        image = ImageOps.exif_transpose(original).convert('RGBA')
        gray = Image.new('L', image.size, 255)
        gray.paste(image.convert('L'), mask=image.getchannel('A'))
        if trim:
            from PIL import ImageChops
            box = ImageChops.difference(gray, Image.new('L', gray.size, 255)).getbbox()
            if box: gray = gray.crop(box)
        rows = max(1, round(gray.height * 384 / gray.width))
        if rows > MAX_ROWS: raise ValueError('预计纸长超过约2米（16000行），请先分割图片')
        result = prepare(gray, dither=cfg.dither, threshold=cfg.threshold)
        buf = io.BytesIO(); result.convert('L').save(buf, 'PNG')
        return buf.getvalue(), rows


def install_routes(app, cfg, mgr, jobs):
    render_lock = asyncio.Semaphore(1)
    jobs.db.execute('''CREATE TABLE IF NOT EXISTS image_previews (
        token_hash TEXT PRIMARY KEY, created REAL NOT NULL, png BLOB,
        rows INTEGER NOT NULL, job_id INTEGER)''')
    jobs.db.commit()

    def authorize(request):
        token = request.headers.get('X-P1-Token', '')
        if len(token) < 32: raise HTTPException(404, '预览或任务不存在')
        key = hashlib.sha256(token.encode()).hexdigest()
        row = jobs.db.execute('SELECT * FROM image_previews WHERE token_hash=?', (key,)).fetchone()
        if row is None: raise HTTPException(404, '预览或任务不存在')
        if row['job_id'] is None and time.time() - row['created'] > TTL:
            raise HTTPException(410, '预览已过期，请重新上传')
        return key, row

    def same_origin(request):
        if request.headers.get('X-P1-Upload') != '1': raise HTTPException(403, '缺少上传请求标识')
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc != request.url.netloc:
            raise HTTPException(403, '跨站请求被拒绝')

    @app.get('/long-image', include_in_schema=False)
    async def page():
        return FileResponse(Path(__file__).parent/'static'/'long-image.html', headers={'Cache-Control':'no-store'})

    @app.get('/long-image/sample.png', include_in_schema=False)
    async def sample():
        return FileResponse(Path(__file__).parent/'static'/'long-image-sample.png', media_type='image/png')

    @app.post('/long-image/preview')
    async def upload(request: Request, trim: bool = False):
        same_origin(request)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_BYTES: raise HTTPException(413, '图片超过40MB')
        if not data: raise HTTPException(400, '请选择图片')
        try:
            async with render_lock:
                png, rows = await asyncio.to_thread(render, bytes(data), cfg, trim)
        except (ValueError, OSError, Image.DecompressionBombError) as e:
            raise HTTPException(400, str(e)) from e
        now = time.time()
        with jobs.db:
            jobs.db.execute('DELETE FROM image_previews WHERE job_id IS NULL AND created<?', (now-TTL,))
            usage = jobs.db.execute('SELECT count(*),coalesce(sum(length(png)),0) FROM image_previews WHERE job_id IS NULL').fetchone()
            if usage[0] >= 8 or usage[1] + len(png) > 64*1024*1024:
                raise HTTPException(503, '预览缓存已满，请稍后再试')
            token = secrets.token_urlsafe(32)
            key = hashlib.sha256(token.encode()).hexdigest()
            jobs.db.execute('INSERT INTO image_previews VALUES(?,?,?,?,NULL)', (key, now, png, rows))
        dpi = mgr.status().get('dpi') or 200
        return {'token':token, 'rows':rows, 'width_dots':384,
                'length_mm':round((rows+cfg.post_feed_lines)*25.4/dpi,1), 'expires_in':TTL}

    @app.get('/long-image/preview.png')
    async def preview(request: Request):
        _, row = authorize(request)
        if row['png'] is None: raise HTTPException(410, '图片已提交，请查询任务')
        return Response(bytes(row['png']), media_type='image/png', headers={'Cache-Control':'no-store'})

    @app.post('/long-image/submit')
    async def submit(request: Request):
        same_origin(request)
        key, row = authorize(request)
        if row['job_id'] is not None: return {'job_id':row['job_id']}
        with jobs.db:
            cur = jobs.db.execute("INSERT INTO jobs(title,source,density,created_at,state) VALUES(?,?,?,?,?)",
                                  ('长图上传', 'lan-image', None, time.time(), 'pending'))
            jid = cur.lastrowid
            jobs.db.execute('INSERT INTO pages VALUES(?,?,?)', (jid,0,row['png']))
            jobs.db.execute('UPDATE image_previews SET job_id=?,png=NULL WHERE token_hash=?', (jid,key))
        jobs._refresh(); jobs.start()
        return {'job_id':jid}

    @app.get('/long-image/job')
    async def status(request: Request):
        _, row = authorize(request)
        if row['job_id'] is None: raise HTTPException(409, '尚未提交')
        return jobs.get(row['job_id'])

    @app.post('/long-image/cancel')
    async def cancel(request: Request):
        same_origin(request)
        _, row = authorize(request)
        if row['job_id'] is None: raise HTTPException(409, '尚未提交')
        return jobs.cancel(row['job_id'])
