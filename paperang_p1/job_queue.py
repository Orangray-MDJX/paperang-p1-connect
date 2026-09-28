"""Durable shared queue; never automatically replay a possibly printed page."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
import logging
from pathlib import Path
import sqlite3
import time
from typing import Callable
from .config import APP_DIR

log = logging.getLogger(__name__)
OnEvent = Callable[[str, str], None]
TERMINAL = {'completed', 'cancelled', 'failed', 'unknown'}


class PrintBlockedError(RuntimeError):
    """Reachable printer needs paper or its cover closed; no page was sent."""


@dataclass
class PrintJob:
    title: str
    pages: list[bytes]
    density: int | None = None
    source: str = 'api'
    created_at: float = field(default_factory=time.time)


@dataclass
class JobStats:
    pending: int = 0
    done: int = 0
    failed: int = 0
    last_job: str | None = None
    last_error: str | None = None
    printing: bool = False


class JobQueue:
    def __init__(self, mgr, on_event: OnEvent | None = None, db_path: Path | None = None):
        self.mgr, self.on_event = mgr, on_event
        path = db_path or APP_DIR / 'jobs.sqlite3'
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                source TEXT NOT NULL, density INTEGER, created_at REAL NOT NULL,
                state TEXT NOT NULL, error TEXT, pages_done INTEGER NOT NULL DEFAULT 0,
                cancel_requested INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS pages (
                job_id INTEGER NOT NULL, ordinal INTEGER NOT NULL, png BLOB NOT NULL,
                PRIMARY KEY(job_id,ordinal));
        ''')
        self.db.execute("UPDATE jobs SET state='unknown',error='服务中断，打印结果未知；不会自动重打' WHERE state='printing'")
        self.db.commit()
        self.stats = JobStats()
        self._worker = None
        self._wake = asyncio.Event()
        self._refresh()

    def _refresh(self):
        counts = {r[0]: r[1] for r in self.db.execute('SELECT state,count(*) FROM jobs GROUP BY state')}
        self.stats.pending = counts.get('pending', 0) + counts.get('held', 0)
        self.stats.done = counts.get('completed', 0)
        self.stats.failed = counts.get('failed', 0) + counts.get('unknown', 0)
        self.stats.printing = bool(counts.get('printing', 0))

    def start(self):
        if not self._worker or self._worker.done():
            self._worker = asyncio.create_task(self._run(), name='print-worker')
        self._wake.set()

    async def stop(self):
        if self._worker:
            self._worker.cancel()
            try: await self._worker
            except asyncio.CancelledError: pass
            self._worker = None
        self.db.close()

    def submit(self, job: PrintJob, held=False) -> int:
        if not job.pages and not held: raise ValueError('打印任务没有页面')
        with self.db:
            cur = self.db.execute('INSERT INTO jobs(title,source,density,created_at,state) VALUES(?,?,?,?,?)',
                                  (job.title, job.source, job.density, job.created_at, 'receiving' if held else 'pending'))
            job_id = cur.lastrowid
            self.db.executemany('INSERT INTO pages VALUES(?,?,?)', [(job_id,i,p) for i,p in enumerate(job.pages)])
        self._refresh(); self.start()
        return job_id

    def attach_pages(self, job_id, pages):
        if self.get(job_id)['state'] != 'receiving' or not pages:
            raise ValueError('任务不在接收文档状态或文档为空')
        with self.db:
            self.db.executemany('INSERT INTO pages VALUES(?,?,?)', [(job_id,i,p) for i,p in enumerate(pages)])
            self.db.execute("UPDATE jobs SET state='pending' WHERE id=?", (job_id,))
        self._refresh(); self._wake.set()

    def get(self, job_id):
        row = self.db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None: raise KeyError(job_id)
        result = dict(row)
        result['page_count'] = self.db.execute('SELECT count(*) FROM pages WHERE job_id=?', (job_id,)).fetchone()[0]
        return result

    def list(self, limit=100):
        return [self.get(r[0]) for r in self.db.execute('SELECT id FROM jobs ORDER BY id DESC LIMIT ?', (limit,)).fetchall()]

    def cancel(self, job_id):
        job = self.get(job_id)
        if job['state'] in TERMINAL: return job
        with self.db:
            self.db.execute("UPDATE jobs SET cancel_requested=1,state=CASE WHEN state='printing' THEN state ELSE 'cancelled' END WHERE id=?", (job_id,))
        self._refresh(); self._wake.set()
        return self.get(job_id)

    def resume(self, job_id):
        if self.get(job_id)['state'] != 'held': raise ValueError('仅可恢复尚未发送的暂停任务')
        self._set(job_id, 'pending'); self._wake.set()
        return self.get(job_id)

    def _set(self, job_id, state, error=None):
        with self.db:
            self.db.execute('UPDATE jobs SET state=?,error=? WHERE id=?', (state, error, job_id))
        if error: self.stats.last_error = error
        self._refresh()

    def _emit(self, level, msg):
        log.log({'info': logging.INFO, 'warn': logging.WARNING}.get(level, logging.ERROR), '%s', msg)
        if self.on_event:
            try: self.on_event(level, msg)
            except Exception: log.exception('事件回调失败')

    async def _run(self):
        while True:
            row = self.db.execute("SELECT id FROM jobs WHERE state='pending' ORDER BY id LIMIT 1").fetchone()
            if row is None:
                self._wake.clear(); await self._wake.wait(); continue
            job_id = row[0]; job = self.get(job_id)
            try:
                async with self.mgr.operation_lock:
                    try:
                        dev = await self.mgr.ensure_connected()
                        # An open Bluetooth handle may outlive a powered-off printer.
                        # Probe before marking any page as possibly sent.
                        if await dev.get_battery() is None:
                            raise ConnectionError('打印前状态查询没有有效应答')
                        self.mgr.last_seen = time.monotonic()
                        check_media = getattr(dev, 'get_media_status', None)
                        media = await check_media() if check_media else {}
                        if media.get('lid_closed') is False:
                            raise PrintBlockedError('纸仓盖未合好，请合盖后手动恢复任务')
                        if media.get('paper_present') is False:
                            raise PrintBlockedError('打印机缺纸，请装纸后手动恢复任务')
                    except PrintBlockedError as e:
                        if self.get(job_id)['cancel_requested']:
                            self._set(job_id, 'cancelled'); continue
                        self._set(job_id, 'held', str(e))
                        self._emit('warn', f'任务 {job_id} 暂停：{e}')
                        continue
                    except Exception as e:
                        await self.mgr.disconnect()
                        if self.get(job_id)['cancel_requested']:
                            self._set(job_id, 'cancelled'); continue
                        self._set(job_id, 'held', f'请开机/唤醒并恢复任务: {e}')
                        self._emit('warn', f'任务 {job_id} 暂停：请开机后恢复'); continue
                    if self.get(job_id)['cancel_requested']:
                        self._set(job_id, 'cancelled'); continue
                    pages = self.db.execute('SELECT png FROM pages WHERE job_id=? ORDER BY ordinal', (job_id,)).fetchall()
                    for i, page in enumerate(pages[job['pages_done']:], job['pages_done']):
                        if self.get(job_id)['cancel_requested']:
                            self._set(job_id, 'cancelled'); break
                        self._set(job_id, 'printing')
                        options = {'density':job['density']}
                        if getattr(dev, 'protocol', None) == 'a5':
                            options['cancel_check'] = lambda: bool(self.get(job_id)['cancel_requested'])
                        await dev.print_png(bytes(page[0]), **options)
                        with self.db:
                            self.db.execute('UPDATE jobs SET pages_done=? WHERE id=?', (i + 1, job_id))
                    else:
                        self._set(job_id, 'completed')
                        self.stats.last_job = job['title']
                        self._emit('info', f'任务 {job_id}：设备已确认接收全部页面')
            except asyncio.CancelledError:
                if self.get(job_id)['state'] == 'printing':
                    self._set(job_id, 'unknown', '服务停止，打印结果未知；不会自动重打')
                raise
            except Exception as e:
                self._set(job_id, 'unknown' if self.get(job_id)['state'] == 'printing' else 'failed', str(e))
                self._emit('error', f'任务 {job_id} 结果未知/失败: {e}')
                await self.mgr.disconnect()
