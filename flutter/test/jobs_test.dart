/// 任务队列状态机测试（直译自 tests/test_jobs.py，SQLite 走 FFI）。
library;

import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:paperang_p1/core/device/printer_device.dart';
import 'package:paperang_p1/core/queue/job_queue.dart';
import 'package:paperang_p1/core/util/async_lock.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

class FakeManager implements QueueManager {
  FakeManager([this.device]);

  final AsyncLock _lock = AsyncLock();

  @override
  AsyncLock get operationLock => _lock;

  PrinterDevice? device;
  int attempts = 0;

  @override
  Future<PrinterDevice> ensureConnected() async {
    attempts++;
    final d = device;
    if (d == null) throw Exception('off');
    return d;
  }

  @override
  Future<void> disconnect() async {}
}

class MediaDevice implements PrinterDevice {
  MediaDevice(this.lid, this.paper);

  bool lid;
  bool paper;
  int count = 0;

  @override
  String get protocol => 'a5';

  @override
  Future<double> getBattery() async => 80;

  @override
  Future<Map<String, bool>> getMediaStatus() async => {
    'lidClosed': lid,
    'paperPresent': paper,
  };

  @override
  Future<void> printPng(
    Uint8List png, {
    int? density,
    Future<bool> Function()? cancelCheck,
  }) async {
    count++;
  }
}

class PrintOnceThenDropDevice implements PrinterDevice {
  int count = 0;

  @override
  String get protocol => 'a5';

  @override
  Future<double> getBattery() async => 80;

  @override
  Future<Map<String, bool>> getMediaStatus() async => {};

  @override
  Future<void> printPng(
    Uint8List png, {
    int? density,
    Future<bool> Function()? cancelCheck,
  }) async {
    count++;
    throw Exception('disconnected after bytes sent');
  }
}

class StaleHandleDevice implements PrinterDevice {
  int count = 0;

  @override
  String get protocol => 'a5';

  @override
  Future<double> getBattery() async =>
      throw Exception('powered off with stale handle');

  @override
  Future<Map<String, bool>> getMediaStatus() async => {};

  @override
  Future<void> printPng(
    Uint8List png, {
    int? density,
    Future<bool> Function()? cancelCheck,
  }) async {
    count++;
  }
}

Future<Directory> tempDir() => Directory.systemTemp.createTemp('p1-jobs-test');

/// 轮询直到条件成立（替代 Python 测试中的固定 sleep）。
Future<void> until(
  Future<bool> Function() predicate, {
  Duration timeout = const Duration(seconds: 3),
}) async {
  final deadline = DateTime.now().add(timeout);
  while (!await predicate()) {
    if (DateTime.now().isAfter(deadline)) {
      fail('until() 超时');
    }
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
}

Future<JobQueue> openQueue(
  QueueManager mgr,
  Directory dir, [
  String name = 'jobs.db',
]) => JobQueue.open(
  mgr,
  dbPath: '${dir.path}${Platform.pathSeparator}$name',
  factory: databaseFactoryFfi,
);

void main() {
  setUpAll(() {
    sqfliteFfiInit();
  });

  test('media 阻塞保持会话且必须显式恢复', () async {
    final dir = await tempDir();
    final device = MediaDevice(false, true);
    final q = await openQueue(FakeManager(device), dir);
    final jid = await q.submit(
      PrintJob(title: 'media blocked', pages: [png()]),
    );
    await until(() async => (await q.get(jid)).state == 'held');
    expect(device.count, 0);
    device.lid = true;
    device.paper = true;
    await Future<void>.delayed(const Duration(milliseconds: 30));
    expect((await q.get(jid)).state, 'held'); // 不自动恢复
    expect(device.count, 0);
    await q.resume(jid);
    await until(() async => (await q.get(jid)).state == 'completed');
    expect(device.count, 1);
    await q.stop();
  });

  test('held 跨重启存活且可取消', () async {
    final dir = await tempDir();
    final mgr = FakeManager();
    var q = await openQueue(mgr, dir);
    final jid = await q.submit(PrintJob(title: 'label', pages: [png()]));
    await until(() async => (await q.get(jid)).state == 'held');
    expect(mgr.attempts, 1);
    await q.stop();
    q = await openQueue(FakeManager(), dir);
    expect((await q.get(jid)).state, 'held');
    expect((await q.cancel(jid)).state, 'cancelled');
    await q.stop();
  });

  test('部分打印后 unknown 且绝不重放', () async {
    final dir = await tempDir();
    final d = PrintOnceThenDropDevice();
    var q = await openQueue(FakeManager(d), dir);
    final jid = await q.submit(PrintJob(title: 'image', pages: [png()]));
    await until(() async => (await q.get(jid)).state == 'unknown');
    expect(d.count, 1);
    await expectLater(q.resume(jid), throwsA(isA<FormatException>()));
    await q.stop();
    q = await openQueue(FakeManager(d), dir);
    q.start();
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(d.count, 1); // 没有重打
    expect((await q.get(jid)).state, 'unknown');
    await q.stop();
  });

  test('陈旧连接在任何打印命令前先转 held', () async {
    final dir = await tempDir();
    final device = StaleHandleDevice();
    final q = await openQueue(FakeManager(device), dir);
    final jid = await q.submit(PrintJob(title: 'not sent', pages: [png()]));
    await until(() async => (await q.get(jid)).state == 'held');
    final job = await q.get(jid);
    expect(job.pagesDone, 0);
    expect(device.count, 0);
    await q.stop();
  });

  test('崩溃 printing 残留转 unknown；接收中文档可取消', () async {
    final dir = await tempDir();
    var q = await openQueue(FakeManager(), dir);
    final jid = await q.submit(
      PrintJob(title: 'incoming', pages: []),
      held: true,
    );
    await q.debugSetState(jid, 'printing');
    await q.stop();
    q = await openQueue(FakeManager(), dir);
    expect((await q.get(jid)).state, 'unknown');
    final other = await q.submit(
      PrintJob(title: 'cancel', pages: []),
      held: true,
    );
    await q.cancel(other);
    await expectLater(
      q.attachPages(other, [png()]),
      throwsA(isA<FormatException>()),
    );
    await q.stop();
  });

  test('连接失败期间取消不会被 held 覆盖', () async {
    final dir = await tempDir();
    final entered = Completer<void>();
    final release = Completer<void>();
    final mgr = _BlockingManager(entered, release);
    final q = await openQueue(mgr, dir);
    final jid = await q.submit(
      PrintJob(title: 'cancel while connecting', pages: [png()]),
    );
    await entered.future;
    await q.cancel(jid);
    release.complete();
    await until(() async => (await q.get(jid)).state == 'cancelled');
    await q.stop();
  });
}

class _BlockingManager extends FakeManager {
  _BlockingManager(this.entered, this.release);

  final Completer<void> entered;
  final Completer<void> release;

  @override
  Future<PrinterDevice> ensureConnected() async {
    entered.complete();
    await release.future;
    throw Exception('unplugged');
  }
}

Uint8List png() => Uint8List.fromList([0x89, 0x50, 0x4E, 0x47]); // 占位 PNG
