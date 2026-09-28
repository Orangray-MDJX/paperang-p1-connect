/// 可持久化共享队列；绝不自动重放可能已出纸的页面（直译自 job_queue.py）。
library;

import 'dart:async';
import 'dart:typed_data';

import 'package:meta/meta.dart';
import 'package:sqflite/sqflite.dart';

import '../device/printer_device.dart';
import '../errors.dart';
import '../util/async_lock.dart';

typedef OnEvent = void Function(String level, String message);

const Set<String> terminalStates = {
  'completed',
  'cancelled',
  'failed',
  'unknown',
};

class PrintJob {
  PrintJob({
    required this.title,
    required this.pages,
    this.density,
    this.source = 'api',
    double? createdAt,
  }) : createdAt = createdAt ?? DateTime.now().millisecondsSinceEpoch / 1000.0;

  final String title;
  final List<Uint8List> pages;
  final int? density;
  final String source;
  final double createdAt;
}

class JobStats {
  int pending = 0;
  int done = 0;
  int failed = 0;
  String? lastJob;
  String? lastError;
  bool printing = false;
}

/// 队列对连接管理器的最小要求。
abstract class QueueManager {
  AsyncLock get operationLock;
  Future<PrinterDevice> ensureConnected();
  Future<void> disconnect();
}

class JobRow {
  JobRow({
    required this.id,
    required this.title,
    required this.source,
    this.density,
    required this.createdAt,
    required this.state,
    this.error,
    required this.pagesDone,
    required this.cancelRequested,
    required this.pageCount,
  });

  final int id;
  final String title;
  final String source;
  final int? density;
  final double createdAt;
  String state;
  String? error;
  final int pagesDone;
  final bool cancelRequested;
  final int pageCount;
}

class JobQueue {
  JobQueue._(this.mgr, this.onEvent, this._factoryOverride);

  /// 打开数据库并执行崩溃恢复（printing→unknown）后返回。
  static Future<JobQueue> open(
    QueueManager mgr, {
    OnEvent? onEvent,
    required String dbPath,
    DatabaseFactory? factory,
  }) async {
    final q = JobQueue._(mgr, onEvent, factory);
    await q._open(dbPath);
    return q;
  }

  final QueueManager mgr;
  final OnEvent? onEvent;
  final DatabaseFactory? _factoryOverride;

  late final Database db;
  final JobStats stats = JobStats();
  Future<void>? _worker;
  Completer<void>? _wake;
  bool _running = false;

  Future<void> _open(String dbPath) async {
    final factory = _factoryOverride ?? databaseFactory;
    db = await factory.openDatabase(
      dbPath,
      options: OpenDatabaseOptions(
        version: 1,
        onCreate: (db, _) async {
          await db.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                    source TEXT NOT NULL, density INTEGER, created_at REAL NOT NULL,
                    state TEXT NOT NULL, error TEXT, pages_done INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0)''');
          await db.execute('''
                CREATE TABLE IF NOT EXISTS pages (
                    job_id INTEGER NOT NULL, ordinal INTEGER NOT NULL, png BLOB NOT NULL,
                    PRIMARY KEY(job_id,ordinal))''');
        },
      ),
    );
    await db.rawQuery('PRAGMA journal_mode=WAL');
    // 上次运行中断时正在打印的任务：结果未知，永不自动重放。
    await db.execute(
      "UPDATE jobs SET state='unknown',error='服务中断，打印结果未知；不会自动重打' WHERE state='printing'",
    );
    await _refresh();
  }

  Future<void> _refresh() async {
    final counts = await db.rawQuery(
      'SELECT state,count(*) AS n FROM jobs GROUP BY state',
    );
    final byState = {
      for (final r in counts) r['state'] as String: r['n'] as int,
    };
    stats.pending = (byState['pending'] ?? 0) + (byState['held'] ?? 0);
    stats.done = byState['completed'] ?? 0;
    stats.failed = (byState['failed'] ?? 0) + (byState['unknown'] ?? 0);
    stats.printing = (byState['printing'] ?? 0) > 0;
  }

  void start() {
    _running = true;
    _pokeWake();
    _worker ??= _run();
  }

  /// 唤醒 worker；Completer 可能已被等待超时消费，重复 complete 会抛错。
  void _pokeWake() {
    final w = _wake;
    _wake = null;
    if (w != null && !w.isCompleted) w.complete();
  }

  Future<void> stop() async {
    _running = false;
    _pokeWake();
    final w = _worker;
    if (w != null) {
      await w;
      _worker = null;
    }
    await db.close();
  }

  Future<int> submit(PrintJob job, {bool held = false}) async {
    if (job.pages.isEmpty && !held) {
      throw const FormatException('打印任务没有页面');
    }
    final jobId = await db.transaction((txn) async {
      final id = await txn.insert('jobs', {
        'title': job.title,
        'source': job.source,
        'density': job.density,
        'created_at': job.createdAt,
        'state': held ? 'receiving' : 'pending',
      });
      for (var i = 0; i < job.pages.length; i++) {
        await txn.insert('pages', {
          'job_id': id,
          'ordinal': i,
          'png': job.pages[i],
        });
      }
      return id;
    });
    await _refresh();
    start();
    return jobId;
  }

  Future<void> attachPages(int jobId, List<Uint8List> pages) async {
    if ((await get(jobId)).state != 'receiving' || pages.isEmpty) {
      throw const FormatException('任务不在接收文档状态或文档为空');
    }
    await db.transaction((txn) async {
      for (var i = 0; i < pages.length; i++) {
        await txn.insert('pages', {
          'job_id': jobId,
          'ordinal': i,
          'png': pages[i],
        });
      }
      await txn.update(
        'jobs',
        {'state': 'pending'},
        where: 'id=?',
        whereArgs: [jobId],
      );
    });
    await _refresh();
    _pokeWake();
  }

  Future<JobRow> get(int jobId) async {
    final rows = await db.query('jobs', where: 'id=?', whereArgs: [jobId]);
    if (rows.isEmpty) throw Exception('job $jobId not found');
    final count = Sqflite.firstIntValue(
      await db.query(
        'pages',
        columns: ['count(*)'],
        where: 'job_id=?',
        whereArgs: [jobId],
      ),
    )!;
    final r = rows.first;
    return JobRow(
      id: r['id'] as int,
      title: r['title'] as String,
      source: r['source'] as String,
      density: r['density'] as int?,
      createdAt: r['created_at'] as double,
      state: r['state'] as String,
      error: r['error'] as String?,
      pagesDone: r['pages_done'] as int,
      cancelRequested: (r['cancel_requested'] as int) == 1,
      pageCount: count,
    );
  }

  Future<List<JobRow>> list({int limit = 100}) async {
    final rows = await db.query(
      'jobs',
      columns: ['id'],
      orderBy: 'id DESC',
      limit: limit,
    );
    final out = <JobRow>[];
    for (final r in rows) {
      out.add(await get(r['id'] as int));
    }
    return out;
  }

  Future<JobRow> cancel(int jobId) async {
    final job = await get(jobId);
    if (terminalStates.contains(job.state)) return job;
    await db.transaction((txn) async {
      await txn.rawUpdate(
        "UPDATE jobs SET cancel_requested=1,state=CASE WHEN state='printing' THEN state ELSE 'cancelled' END WHERE id=?",
        [jobId],
      );
    });
    await _refresh();
    _pokeWake();
    return get(jobId);
  }

  Future<JobRow> resume(int jobId) async {
    if ((await get(jobId)).state != 'held') {
      throw const FormatException('仅可恢复尚未发送的暂停任务');
    }
    await _set(jobId, 'pending');
    _pokeWake();
    return get(jobId);
  }

  Future<void> _set(int jobId, String state, [String? error]) async {
    await db.update(
      'jobs',
      {'state': state, 'error': error},
      where: 'id=?',
      whereArgs: [jobId],
    );
    if (error != null) stats.lastError = error;
    await _refresh();
  }

  void _emit(String level, String msg) => onEvent?.call(level, msg);

  /// 仅供测试：直接置状态（模拟崩溃残留）。
  @visibleForTesting
  Future<void> debugSetState(int jobId, String state) => _set(jobId, state);

  Future<void> _run() async {
    while (_running) {
      final rows = await db.query(
        'jobs',
        columns: ['id'],
        where: "state='pending'",
        orderBy: 'id',
        limit: 1,
      );
      if (rows.isEmpty) {
        // 周期超时轮询 _running：stop() 可能在创建 Completer 之前已跑过，
        // 纯事件等待会让 worker 永远醒不来。
        final wake = _wake = Completer<void>();
        await wake.future.timeout(
          const Duration(milliseconds: 250),
          onTimeout: () {},
        );
        _wake = null;
        continue;
      }
      final jobId = rows.first['id'] as int;
      await _process(jobId);
    }
  }

  Future<void> _process(int jobId) async {
    var job = await get(jobId);
    try {
      await mgr.operationLock.synchronize(() async {
        try {
          final dev = await mgr.ensureConnected();
          // 蓝牙句柄可能比已关机的打印机活得久：标记任何页面为
          // "可能已发送"之前先探测。
          await dev.getBattery();
          final media = await dev.getMediaStatus();
          if (media['lidClosed'] == false) {
            throw PrintBlockedError('纸仓盖未合好，请合盖后手动恢复任务');
          }
          if (media['paperPresent'] == false) {
            throw PrintBlockedError('打印机缺纸，请装纸后手动恢复任务');
          }
        } on PrintBlockedError catch (e) {
          if ((await get(jobId)).cancelRequested) {
            await _set(jobId, 'cancelled');
            return;
          }
          await _set(jobId, 'held', e.message);
          _emit('warn', '任务 $jobId 暂停：${e.message}');
          return;
        } catch (e) {
          await mgr.disconnect();
          if ((await get(jobId)).cancelRequested) {
            await _set(jobId, 'cancelled');
            return;
          }
          await _set(jobId, 'held', '请开机/唤醒并恢复任务: $e');
          _emit('warn', '任务 $jobId 暂停：请开机后恢复');
          return;
        }
        if ((await get(jobId)).cancelRequested) {
          await _set(jobId, 'cancelled');
          return;
        }
        final pages = await db.query(
          'pages',
          columns: ['png'],
          where: 'job_id=?',
          whereArgs: [jobId],
          orderBy: 'ordinal',
        );
        var cancelled = false;
        final dev = await mgr.ensureConnected();
        for (var i = job.pagesDone; i < pages.length && !cancelled; i++) {
          if ((await get(jobId)).cancelRequested || !_running) {
            await _set(jobId, 'cancelled');
            cancelled = true;
            break;
          }
          await _set(jobId, 'printing');
          final png = pages[i]['png'] as Uint8List;
          await dev.printPng(
            png,
            density: job.density,
            cancelCheck: dev.protocol == 'a5'
                ? () async => !_running || (await get(jobId)).cancelRequested
                : null,
          );
          await db.update(
            'jobs',
            {'pages_done': i + 1},
            where: 'id=?',
            whereArgs: [jobId],
          );
        }
        if (!cancelled) {
          await _set(jobId, 'completed');
          stats.lastJob = job.title;
          _emit('info', '任务 $jobId：设备已确认接收全部页面');
        }
      });
    } catch (e) {
      final state = (await get(jobId)).state;
      await _set(jobId, state == 'printing' ? 'unknown' : 'failed', '$e');
      _emit('error', '任务 $jobId 结果未知/失败: $e');
      await mgr.disconnect();
    }
  }
}
