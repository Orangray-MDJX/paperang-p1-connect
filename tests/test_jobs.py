import asyncio
import sqlite3
import pytest
from paperang_p1.job_queue import JobQueue, PrintJob


class Manager:
    def __init__(self, device=None):
        self.operation_lock = asyncio.Lock(); self.device = device; self.attempts = 0
    async def ensure_connected(self):
        self.attempts += 1
        if self.device is None: raise ConnectionError('off')
        return self.device
    async def disconnect(self): pass


@pytest.mark.parametrize('lid,paper', [(False, True), (True, False)])
def test_media_block_preserves_session_and_requires_explicit_resume(tmp_path, lid, paper):
    class Device:
        count = 0
        async def get_battery(self): return 80
        async def get_media_status(self): return {'lid_closed': self.lid, 'paper_present': self.paper}
        async def print_png(self, *args, **kwargs): self.count += 1
    async def run():
        device = Device(); device.lid = lid; device.paper = paper
        q = JobQueue(Manager(device), db_path=tmp_path/'jobs.db')
        jid = q.submit(PrintJob('media blocked', [b'png']))
        await asyncio.sleep(.02)
        assert q.get(jid)['state'] == 'held' and device.count == 0
        device.lid = device.paper = True
        await asyncio.sleep(.02)
        assert q.get(jid)['state'] == 'held' and device.count == 0
        q.resume(jid)
        await asyncio.sleep(.02)
        assert q.get(jid)['state'] == 'completed' and device.count == 1
        await q.stop()
    asyncio.run(run())


def test_held_jobs_survive_restart_and_can_cancel(tmp_path):
    async def run():
        path = tmp_path / 'jobs.db'; mgr = Manager()
        q = JobQueue(mgr, db_path=path)
        jid = q.submit(PrintJob('label', [b'png']))
        await asyncio.sleep(.02)
        assert q.get(jid)['state'] == 'held'
        assert mgr.attempts == 1
        await q.stop()
        q = JobQueue(Manager(), db_path=path)
        assert q.get(jid)['state'] == 'held'
        assert q.cancel(jid)['state'] == 'cancelled'
        await q.stop()
    asyncio.run(run())


def test_partial_print_unknown_is_not_replayed(tmp_path):
    class Device:
        count = 0
        async def get_battery(self): return 80
        async def print_png(self, *args, **kwargs):
            self.count += 1
            raise ConnectionError('disconnected after bytes sent')
    async def run():
        d = Device(); path = tmp_path / 'jobs.db'
        q = JobQueue(Manager(d), db_path=path)
        jid = q.submit(PrintJob('image', [b'png']))
        await asyncio.sleep(.02)
        assert q.get(jid)['state'] == 'unknown' and d.count == 1
        with pytest.raises(ValueError): q.resume(jid)
        await q.stop()
        q = JobQueue(Manager(d), db_path=path); q.start()
        await asyncio.sleep(.02)
        assert d.count == 1 and q.get(jid)['state'] == 'unknown'
        await q.stop()
    asyncio.run(run())


def test_stale_open_connection_is_held_before_any_print_command(tmp_path):
    class Device:
        count = 0
        async def get_battery(self): raise ConnectionError('powered off with stale handle')
        async def print_png(self, *args, **kwargs): self.count += 1
    async def run():
        device = Device()
        q = JobQueue(Manager(device), db_path=tmp_path/'jobs.db')
        jid = q.submit(PrintJob('not sent', [b'png']))
        await asyncio.sleep(.02)
        assert q.get(jid)['state'] == 'held'
        assert q.get(jid)['pages_done'] == 0 and device.count == 0
        await q.stop()
    asyncio.run(run())


def test_crash_print_marker_becomes_unknown_and_receiving_document_can_cancel(tmp_path):
    async def run():
        path = tmp_path / 'jobs.db'
        q = JobQueue(Manager(), db_path=path)
        jid = q.submit(PrintJob('incoming', []), held=True)
        q._set(jid, 'printing')
        await q.stop()
        q = JobQueue(Manager(), db_path=path)
        assert q.get(jid)['state'] == 'unknown'
        other = q.submit(PrintJob('cancel', []), held=True)
        q.cancel(other)
        with pytest.raises(ValueError): q.attach_pages(other, [b'png'])
        await q.stop()
    asyncio.run(run())


def test_cancel_during_failed_connection_is_not_overwritten_as_held(tmp_path):
    async def run():
        entered = asyncio.Event(); release = asyncio.Event()
        class ConnectingManager(Manager):
            async def ensure_connected(self):
                entered.set(); await release.wait()
                raise ConnectionError('unplugged')
        q = JobQueue(ConnectingManager(), db_path=tmp_path/'jobs.db')
        jid = q.submit(PrintJob('cancel while connecting', [b'png']))
        await entered.wait()
        q.cancel(jid); release.set()
        await asyncio.sleep(.01)
        assert q.get(jid)['state'] == 'cancelled'
        await q.stop()
    asyncio.run(run())
