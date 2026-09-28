/// 复现模拟器上 IPP 任务卡在 printing 的问题：
/// URF 文档 → _renderDocument → 队列 worker → SimulatedPrinter 打印。
library;

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:paperang_p1/core/config/config.dart';
import 'package:paperang_p1/core/connection/connection_manager.dart';
import 'package:paperang_p1/core/device/printer_device.dart';
import 'package:paperang_p1/core/net/ipp.dart';
import 'package:paperang_p1/core/queue/job_queue.dart';
import 'package:paperang_p1/core/transport/simulated.dart';
import 'package:paperang_p1/core/util/async_lock.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

class _Mgr implements QueueManager, DeviceStatusProvider {
  _Mgr(this.inner, this.device);

  final DeviceManager inner;
  final PrinterDevice device;

  @override
  AsyncLock get operationLock => inner.operationLock;

  @override
  Future<PrinterDevice> ensureConnected() => inner.ensureConnected();

  @override
  Future<void> disconnect() => inner.disconnect();

  @override
  Map<String, Object?> status() => inner.status();
}

void main() {
  setUpAll(() => sqfliteFfiInit());

  test('URF 2x2 经 IPP 渲染与队列在模拟打印机上完成', () async {
    final dir = await Directory.systemTemp.createTemp('e2e');
    final cfg = AppConfig()
      ..transportPref = 'simulated'
      ..dither = 'floyd-steinberg';
    final mgr = DeviceManager(
      cfg,
      createTransport: (name) {
        if (name == 'simulated') return SimulatedPrinter(name: 'simulated');
        return null;
      },
    );
    final queue = await JobQueue.open(
      mgr,
      dbPath: '${dir.path}${Platform.pathSeparator}e2e.db',
      factory: databaseFactoryFfi,
    );
    final svc = IppService(cfg, _Mgr(mgr, await mgr.ensureConnected()), queue);

    // 构造 URF 2x2 300dpi
    final header = Uint8List(32);
    header[0] = 8;
    final hd = ByteData.sublistView(header);
    hd.setUint32(12, 2, Endian.big);
    hd.setUint32(16, 2, Endian.big);
    hd.setUint32(20, 300, Endian.big);
    final urf = Uint8List.fromList([
      ...'UNIRAST\u0000'.codeUnits,
      ...Uint8List(4)..buffer.asByteData().setUint32(0, 1, Endian.big),
      ...header,
      0x01,
      0xff,
      0x00,
      0xff,
    ]);

    final out = BytesBuilder();
    final head = Uint8List(8);
    head[0] = 2;
    ByteData.sublistView(head).setUint16(2, 2, Endian.big);
    ByteData.sublistView(head).setUint32(4, 123, Endian.big);
    out.add(head);
    out.add(Uint8List.fromList([0x01]));
    out.add(IppCodec.attribute('attributes-charset', 0x47, 'utf-8'));
    out.add(IppCodec.attribute('attributes-natural-language', 0x48, 'en'));
    out.add(IppCodec.attribute('document-format', 0x49, 'image/urf'));
    out.add(Uint8List.fromList([0x03]));
    out.add(urf);

    final resp = await svc
        .handle(out.toBytes())
        .timeout(
          const Duration(seconds: 20),
          onTimeout: () => throw 'handle 超时',
        );
    final parsed = IppCodec.parse(resp);
    expect(parsed.operation, 0, reason: 'Print-Job 应成功受理');

    final deadline = DateTime.now().add(const Duration(seconds: 15));
    var state = '';
    while (DateTime.now().isBefore(deadline)) {
      // 找到最新任务
      final list = await queue.list(limit: 1);
      state = list.isEmpty ? '' : list.first.state;
      if (state == 'completed' || state == 'unknown' || state == 'failed') {
        break;
      }
      await Future<void>.delayed(const Duration(milliseconds: 200));
    }
    expect(state, 'completed', reason: '任务应在模拟打印机上完成（实际 $state）');
    await queue.stop();
    await mgr.stop();
  }, timeout: const Timeout(Duration(minutes: 1)));
}

// image 包前缀避免未用导入
