import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:paperang_p1/core/config/config.dart';
import 'package:paperang_p1/core/connection/connection_manager.dart';
import 'package:paperang_p1/core/queue/job_queue.dart';
import 'package:paperang_p1/platform/android_transports.dart';
import 'package:paperang_p1/services/pdf_service.dart';

/// 真机端到端打印验证：连接（BLE 敲门→RFCOMM）→ 渲染 PDF → 入队 →
/// 等 completed。completed 语义要求电量/纸仓门控与 0511/051B/051A 全部
/// 被设备 ACK——即出纸的协议级证据。运行：
///   flutter test integration_test/print_check_test.dart -d [serial]
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('print pdf end to end over bluetooth', (tester) async {
    final data = await rootBundle.load('integration_test/test.pdf');
    final pages = await PdfService.renderForPrint(
      data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes),
    );
    expect(pages.length, 3);

    final cfg = AppConfig()..transportPref = 'auto';
    String? resolved;
    for (final d in await RfcommTransport.listBonded()) {
      final name = d['name'] as String? ?? '';
      if (cfg.bleNamePrefixes.any(
        (p) => name.toLowerCase().startsWith(p.toLowerCase()),
      )) {
        resolved = d['address'] as String;
      }
    }
    expect(resolved, isNotNull, reason: '未找到已配对的 Paperang 设备');

    final mgr = DeviceManager(
      cfg,
      createTransport: (name) => switch (name) {
        'spp' => resolved == null ? null : RfcommTransport(resolved),
        'ble' => BleTransport(resolved ?? ''),
        _ => null,
      },
    );
    final dir = await Directory.systemTemp.createTemp('p1print');
    final queue = await JobQueue.open(mgr, dbPath: '${dir.path}/jobs.db');

    final id = await queue.submit(
      PrintJob(title: 'integration-print.pdf', pages: pages.take(1).toList()),
    );
    String state = 'pending';
    for (var i = 0; i < 40; i++) {
      await Future<void>.delayed(const Duration(seconds: 2));
      state = (await queue.get(id)).state;
      if (state == 'completed' || state == 'failed' || state == 'unknown') {
        break;
      }
    }
    final job = await queue.get(id);
    final st = job.state;
    final done = job.pagesDone;
    final err = job.error;
    // ignore: avoid_print
    print('JOB_RESULT=$st pages_done=$done err=$err');
    await queue.stop();
    await mgr.stop();
    expect(state, 'completed', reason: 'print not completed: \$state');
  });
}
