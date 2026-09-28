"""Local IPP/2.0 endpoint backed by the same durable queue as API/MCP."""
import asyncio
import io
import logging
import struct
import time
import uuid
from fastapi import Request
from fastapi.responses import Response
from PIL import Image, ImageChops
from .config import find_ghostscript
from .job_queue import PrintJob
from .render import prepare, rasterize_document
from .pwg_raster import decode as decode_pwg
from .urf_raster import decode as decode_urf
from .lan_discovery import printer_uuid

log = logging.getLogger(__name__)
MAX_DOCUMENT = 40 * 1024 * 1024
OPS = [2, 4, 5, 6, 8, 9, 10, 11]
BASE_MEDIA = [('custom_57x100mm_57x100mm',5700,10000),
              ('na_index-4x6_4x6in',10160,15240), ('iso_a4_210x297mm',21000,29700)]


def media_catalog(cfg):
    return BASE_MEDIA + ([(f'custom_57x{n}mm_57x{n}mm',5700,n*100) for n in (200,300,500)]
                         if cfg.ipp_long_media else [])
STATE = {'receiving': 4, 'pending': 3, 'held': 4, 'printing': 5,
         'cancelled': 7, 'failed': 8, 'unknown': 8, 'completed': 9}


def value_bytes(tag, value):
    if isinstance(value, bytes): return value
    if tag in (0x21, 0x23): return struct.pack('>i', value)
    if tag == 0x22: return bytes([bool(value)])
    if tag == 0x32: return struct.pack('>iiB', *value)
    if tag == 0x33: return struct.pack('>ii', *value)
    return str(value).encode('utf-8')


def attribute(name, tag, values):
    if not isinstance(values, list): values = [values]
    out = bytearray()
    for i, value in enumerate(values):
        n = name.encode('utf-8') if i == 0 else b''
        v = value_bytes(tag, value)
        out += bytes([tag]) + struct.pack('>H', len(n)) + n + struct.pack('>H', len(v)) + v
    return bytes(out)


def collection(name, members):
    out = attribute(name, 0x34, b'')
    for key, tag, value in members:
        out += attribute('', 0x4a, key)
        if tag == 0x34: out += collection('', value)
        else: out += attribute('', tag, value)
    return out + attribute('', 0x37, b'')


def parse(data):
    if len(data) < 9: raise ValueError('IPP header truncated')
    major, minor, operation, request_id = struct.unpack_from('>BBHI', data)
    if (major, minor) not in ((1, 1), (2, 0)): raise ValueError('IPP version unsupported')
    attrs = {}; pos = 8; name = None; stack = [attrs]
    while pos < len(data):
        tag = data[pos]; pos += 1
        if tag == 3:
            if len(stack) != 1: raise ValueError('IPP collection truncated')
            return (major, minor), operation, request_id, attrs, data[pos:]
        if tag < 0x10:
            if tag not in (1, 2, 4, 5): raise ValueError('IPP group invalid')
            name = None; continue
        if pos + 2 > len(data): raise ValueError('IPP name truncated')
        size = struct.unpack_from('>H', data, pos)[0]; pos += 2
        if pos + size + 2 > len(data): raise ValueError('IPP attribute truncated')
        if size: name = data[pos:pos + size].decode('utf-8')
        pos += size; size = struct.unpack_from('>H', data, pos)[0]; pos += 2
        if pos + size > len(data): raise ValueError('IPP value truncated')
        value = data[pos:pos + size]; pos += size
        if tag in (0x21, 0x23) and len(value) == 4: value = struct.unpack('>i', value)[0]
        elif tag == 0x22 and len(value) == 1: value = bool(value[0])
        elif tag in (0x41, 0x42, 0x44, 0x45, 0x47, 0x48, 0x49): value = value.decode('utf-8')
        if tag == 0x4a:
            if len(stack) == 1: raise ValueError('IPP member outside collection')
            name = value.decode('utf-8')
        elif tag == 0x37:
            if len(stack) == 1: raise ValueError('IPP collection end invalid')
            stack.pop(); name = None
        elif tag == 0x34:
            if not name or len(stack) >= 8: raise ValueError('IPP collection invalid')
            child = {}; stack[-1].setdefault(name, []).append(child); stack.append(child); name = None
        elif name: stack[-1].setdefault(name, []).append(value)
        if pos > 128 * 1024: raise ValueError('IPP attributes too large')
    raise ValueError('IPP end-of-attributes missing')


def response(version, request_id, status=0, groups=b'', message=None):
    body = struct.pack('>BBHI', *version, status, request_id) + b'\x01'
    body += attribute('attributes-charset', 0x47, 'utf-8')
    body += attribute('attributes-natural-language', 0x48, 'en')
    if message: body += attribute('status-message', 0x41, message)
    return body + groups + b'\x03'


def png_pages(images, cfg):
    result = []
    for image in images:
        image = image.convert('L')
        # Roll paper must not consume a whole 100mm form for a one-line label.
        box = ImageChops.difference(image, Image.new('L', image.size, 255)).getbbox()
        if box: image = image.crop((0, 0, image.width, min(image.height, box[3] + 8)))
        else: image = image.crop((0, 0, image.width, min(image.height, 16)))
        image = prepare(image, dither=cfg.dither, threshold=cfg.threshold)
        buf = io.BytesIO(); image.convert('L').save(buf, 'PNG'); result.append(buf.getvalue())
    return result


def render_document(data, mime, cfg):
    if mime == 'image/pwg-raster': images = decode_pwg(data)
    elif mime == 'image/urf': images = decode_urf(data)
    elif mime == 'image/jpeg':
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > 20_000_000: raise ValueError('Image too large')
        images = [image.convert('L')]
    elif mime == 'application/pdf':
        gs = find_ghostscript(cfg)
        if not gs: raise ValueError('Ghostscript unavailable')
        images = rasterize_document(data, gs)
    else: raise ValueError('unsupported document-format')
    log.info('IPP source pages=%s dimensions=%s', len(images), [image.size for image in images])
    return png_pages(images, cfg)


def quality_density(cfg, quality):
    """IPP print-quality 档位（3=草稿 4=正常 5=高）映射为浓度 0-100。

    正常档等于服务全局默认浓度，草稿/高档按比例缩放，保持用户全局设置的意义。
    """
    if quality == 3: return max(0, round(cfg.density * 0.625))
    if quality == 5: return min(100, round(cfg.density * 1.25))
    return cfg.density


def job_attributes(job, uri):
    reason = {'held': 'printer-stopped', 'unknown': 'job-completed-with-errors', 'failed': 'document-format-error',
              'cancelled': 'job-canceled-by-user', 'receiving': 'job-incoming'}.get(job['state'], 'none')
    out = b'\x02'
    for name, tag, value in [
        ('job-id', 0x21, job['id']), ('job-uri', 0x45, uri + '/jobs/' + str(job['id'])),
        ('job-printer-uri', 0x45, uri), ('job-name', 0x42, job['title']),
        ('job-state', 0x23, STATE[job['state']]), ('job-state-reasons', 0x44, reason),
        ('job-state-message', 0x41, job['error'] or job['state']),
        ('job-impressions', 0x21, job['page_count']), ('job-impressions-completed', 0x21, job['pages_done']),
        ('job-k-octets', 0x21, 0), ('job-originating-user-name', 0x42, 'local'),
    ]: out += attribute(name, tag, value)
    return out


def printer_attributes(cfg, mgr, jobs, uri, started):
    st = mgr.status(); ready = st.get('printable', st['connected'])
    reasons = []
    if not st['connected']: reasons.append('connecting-to-device')
    if st.get('lid_closed') is False: reasons.append('cover-open')
    if st.get('paper_present') is False: reasons.append('media-empty')
    message = ('请合好纸仓盖' if st.get('lid_closed') is False else
               '请装纸后手动恢复任务' if st.get('paper_present') is False else
               st['last_error'] or ('ready' if ready else '请开机/唤醒 P1'))
    media = 'custom_57x100mm_57x100mm'
    attrs = [
        ('printer-uri-supported', 0x45, uri), ('uri-authentication-supported', 0x44, 'none'),
        ('uri-security-supported', 0x44, 'none'), ('printer-name', 0x42, 'Paperang P1 (服务)'),
        ('printer-info', 0x41, 'Paperang P1 local USB/Bluetooth bridge'),
        ('printer-location', 0x41, 'Local computer'), ('printer-make-and-model', 0x41, 'Paperang P1'),
        ('printer-uuid', 0x45, 'urn:uuid:' + printer_uuid()),
        ('printer-state', 0x23, 4 if jobs.stats.printing else (3 if ready else 5)),
        ('printer-state-reasons', 0x44, reasons or ['none']),
        ('printer-state-message', 0x41, message),
        ('printer-is-accepting-jobs', 0x22, True), ('queued-job-count', 0x21, jobs.stats.pending),
        ('printer-up-time', 0x21, int(time.monotonic() - started)), ('printer-config-change-time', 0x21, 0),
        ('printer-state-change-time', 0x21, 0), ('ipp-versions-supported', 0x44, ['1.1', '2.0']),
        ('operations-supported', 0x23, OPS), ('charset-configured', 0x47, 'utf-8'),
        ('charset-supported', 0x47, 'utf-8'), ('natural-language-configured', 0x48, 'en'),
        ('generated-natural-language-supported', 0x48, ['en', 'zh-cn']),
        ('document-format-default', 0x49, 'image/pwg-raster'),
        ('document-format-supported', 0x49, ['image/pwg-raster', 'image/urf', 'image/jpeg'] + (['application/pdf'] if find_ghostscript(cfg) else [])),
        ('urf-supported', 0x44, ['W8','RS300','DM1','IS1','V1.4']),
        ('compression-supported', 0x44, 'none'), ('color-supported', 0x22, False),
        ('print-color-mode-default', 0x44, 'monochrome'), ('print-color-mode-supported', 0x44, 'monochrome'),
        ('copies-default', 0x21, 1), ('copies-supported', 0x33, (1, 1)),
        ('sides-default', 0x44, 'one-sided'), ('sides-supported', 0x44, 'one-sided'),
        ('printer-resolution-default', 0x32, (203, 203, 3)), ('printer-resolution-supported', 0x32, [(203,203,3),(300,300,3)]),
        ('pwg-raster-document-resolution-supported', 0x32, (203, 203, 3)),
        ('pwg-raster-document-type-supported', 0x44, ['black_1', 'black_8', 'sgray_1', 'sgray_8']),
        ('pwg-raster-document-sheet-back', 0x44, 'normal'),
        ('media-default', 0x44, media), ('media-supported', 0x44, [m[0] for m in media_catalog(cfg)]),
        ('media-ready', 0x44, media), ('media-source-supported', 0x44, 'main-roll'),
        ('media-type-supported', 0x44, 'stationery'), ('media-col-supported', 0x44,
         ['media-size', 'media-source', 'media-type', 'media-left-margin', 'media-right-margin', 'media-top-margin', 'media-bottom-margin']),
        ('media-left-margin-supported', 0x21, 450), ('media-right-margin-supported', 0x21, 450),
        ('media-top-margin-supported', 0x21, 0), ('media-bottom-margin-supported', 0x21, 0),
        ('orientation-requested-default', 0x23, 3), ('orientation-requested-supported', 0x23, [3, 4]),
        ('print-quality-default', 0x23, 4), ('print-quality-supported', 0x23, [3, 4, 5]),
        ('job-creation-attributes-supported', 0x44, ['job-name', 'document-format', 'media', 'media-col', 'copies', 'sides', 'print-color-mode', 'printer-resolution', 'print-quality']),
        ('multiple-document-jobs-supported', 0x22, False), ('multiple-document-handling-default', 0x44, 'single-document'),
        ('multiple-document-handling-supported', 0x44, 'single-document'), ('job-hold-until-supported', 0x44, 'no-hold'),
        ('job-hold-until-default', 0x44, 'no-hold'), ('job-priority-default', 0x21, 50), ('job-priority-supported', 0x21, 1),
        ('job-cancel-after-supported', 0x33, (0, 0)), ('job-settable-attributes-supported', 0x44, 'none'),
        ('pages-per-minute', 0x21, 1), ('number-up-default', 0x21, 1), ('number-up-supported', 0x21, 1),
    ]
    out = b'\x04' + b''.join(attribute(*a) for a in attrs)
    members = [('media-size', 0x34, [('x-dimension', 0x21, 5700), ('y-dimension', 0x21, 10000)]),
               ('media-source', 0x44, 'main-roll'), ('media-type', 0x44, 'stationery'),
               ('media-left-margin', 0x21, 450), ('media-right-margin', 0x21, 450),
               ('media-top-margin', 0x21, 0), ('media-bottom-margin', 0x21, 0)]
    for name in ('media-col-default', 'media-col-ready'): out += collection(name, members)
    for keyword, width, height in media_catalog(cfg):
        size = [('x-dimension',0x21,width),('y-dimension',0x21,height)]
        out += collection('media-col-database', [('media-size',0x34,size),
                            ('media-size-name',0x44,keyword)] + members[1:])
        out += collection('media-size-supported', size)
    return out


def install_routes(app, cfg, mgr, jobs):
    started = time.monotonic()


    @app.post('/ipp/print')
    @app.post('/ipp/print/jobs/{path_job_id}')
    async def ipp(request: Request, path_job_id: int | None = None):
        host = request.url.hostname or '127.0.0.1'
        uri = f'ipp://{host}:{cfg.ipp_port}/ipp/print'
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_DOCUMENT: return Response(status_code=413)
        version, request_id = (2, 0), 1
        try:
            version, op, request_id, attrs, document = parse(bytes(data))
            get = lambda name, default=None: attrs.get(name, [default])[0]
            groups = b''; status = 0
            if op == 11:
                groups = printer_attributes(cfg, mgr, jobs, uri, started)
            elif op in (2, 4, 5, 6):
                sizes = media_catalog(cfg)
                media_col = get('media-col')
                log.info('IPP request op=%04x media=%s media_col=%s format=%s', op, get('media'), media_col, get('document-format'))
                dimensions = None
                if media_col:
                    if not isinstance(media_col, dict): raise ValueError('media-col must be a collection')
                    size = media_col.get('media-size', [{}])[0]
                    if not isinstance(size, dict): raise ValueError('media-size must be a collection')
                    dimensions = (size.get('x-dimension',[None])[0], size.get('y-dimension',[None])[0])
                # Windows GDI sizes are quantized to 1/100 inch (0.254 mm).
                matching = [m for m in sizes if dimensions and all(isinstance(v,int) for v in dimensions)
                            and abs(dimensions[0]-m[1])<=25 and abs(dimensions[1]-m[2])<=25]
                if get('media') and get('media') not in [m[0] for m in sizes] and not matching:
                    return Response(response(version, request_id, 0x040b, message='Unsupported media'), media_type='application/ipp')
                if media_col:
                    if not matching:
                        return Response(response(version, request_id, 0x040b, message='Unsupported media-size'), media_type='application/ipp')
                    if dimensions != (matching[0][1],matching[0][2]) or get('media') and get('media') != matching[0][0]:
                        status = 0x0001
                mime = get('document-format', 'image/pwg-raster')
                log.info('IPP layout media=%s media_col=%s format=%s', get('media'), media_col, mime)
                if mime not in ('image/pwg-raster', 'image/urf', 'image/jpeg', 'application/pdf') or (mime == 'application/pdf' and not find_ghostscript(cfg)):
                    return Response(response(version, request_id, 0x040a), media_type='application/ipp')
                if get('copies', 1) != 1 or get('sides', 'one-sided') != 'one-sided' or get('compression', 'none') != 'none':
                    return Response(response(version, request_id, 0x040b), media_type='application/ipp')
                quality = get('print-quality')
                density = None
                if quality is not None:
                    if quality not in (3, 4, 5):
                        log.warning('IPP 忽略不支持的 print-quality=%s，使用默认浓度', quality)
                    else:
                        density = quality_density(cfg, quality)
                        log.info('IPP print-quality=%s 映射浓度档 %s', quality, density)
                if op == 5:
                    jid = jobs.submit(PrintJob(get('job-name', 'Windows IPP'), [], density=density, source='ipp'), held=True)
                    groups = job_attributes(jobs.get(jid), uri)
                elif op in (2, 6):
                    if op == 6 and not get('last-document', True): raise ValueError('仅支持一个文档')
                    pages = await asyncio.to_thread(render_document, document, mime, cfg)
                    log.info('IPP rendered pages=%s dimensions=%s', len(pages),
                             [Image.open(io.BytesIO(p)).size for p in pages])
                    if op == 2: jid = jobs.submit(PrintJob(get('job-name', 'Windows IPP'), pages, density=density, source='ipp'))
                    else:
                        jid = get('job-id', path_job_id)
                        jobs.attach_pages(jid, pages)
                    groups = job_attributes(jobs.get(jid), uri)
            elif op in (8, 9):
                jid = get('job-id', path_job_id)
                if jid is None and get('job-uri'):
                    jid = int(get('job-uri').rstrip('/').rsplit('/', 1)[-1])
                job = jobs.cancel(jid) if op == 8 else jobs.get(jid)
                groups = job_attributes(job, uri)
            elif op == 10:
                which = get('which-jobs', 'not-completed')
                selected = [j for j in jobs.list() if which == 'all' or
                            (which == 'completed' and j['state'] in ('completed', 'cancelled', 'failed', 'unknown')) or
                            (which == 'not-completed' and j['state'] not in ('completed', 'cancelled', 'failed', 'unknown'))]
                limit = get('limit', 100)
                groups = b''.join(job_attributes(j, uri) for j in selected[:max(0, min(limit, 100))])
            else: status = 0x0501
            log.info('IPP op=%04x request=%s status=%04x', op, request_id, status)
            return Response(response(version, request_id, status, groups), media_type='application/ipp')
        except KeyError:
            return Response(response(version, request_id, 0x0406), media_type='application/ipp')
        except (ValueError, TypeError, UnicodeError, struct.error) as e:
            log.warning('IPP invalid request: %s', e)
            return Response(response(version, request_id, 0x0400, message=str(e)), media_type='application/ipp')
        except Exception:
            log.exception('IPP request failed')
            return Response(response(version, request_id, 0x0500), media_type='application/ipp')
