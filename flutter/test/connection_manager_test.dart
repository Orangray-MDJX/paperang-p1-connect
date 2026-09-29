/// 连接管理测试：usb-only 断线恢复不回落蓝牙（对齐
/// tests/test_connection_manager.py 的核心语义）。
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:paperang_p1/core/config/config.dart';
import 'package:paperang_p1/core/connection/connection_manager.dart';
import 'package:paperang_p1/core/transport/simulated.dart';

void main() {
  test('usb-only：断线后重连永远优先 USB，不回落蓝牙', () async {
    final calls = <String>[];
    SimulatedPrinter? current;
    final mgr = DeviceManager(
      AppConfig()..transportPref = 'usb',
      createTransport: (name) {
        calls.add(name);
        current = SimulatedPrinter(name: name);
        return current;
      },
    );
    final d1 = await mgr.ensureConnected();
    expect(d1, isNotNull);
    expect(calls, ['usb']);
    // 断线（EOF → fault）后再次请求，仍应走 usb
    await current!.close();
    await mgr.ensureConnected();
    expect(calls, ['usb', 'usb']);
    await current!.close();
    await mgr.ensureConnected();
    expect(calls, ['usb', 'usb', 'usb']);
    await mgr.stop();
  });

  test('auto：USB 不可用时回落 BLE/经典蓝牙（BLE 优先）', () async {
    final calls = <String>[];
    final mgr = DeviceManager(
      AppConfig()..transportPref = 'auto',
      createTransport: (name) {
        calls.add(name);
        if (name == 'usb') return null;
        return SimulatedPrinter(name: 'ble');
      },
    );
    final d = await mgr.ensureConnected();
    expect(d, isNotNull);
    expect(calls, ['usb', 'ble']);
    expect(mgr.status()['transport'], 'ble');
    await mgr.stop();
  });

  test('连接失败记录错误并保持 fault 状态', () async {
    final mgr = DeviceManager(
      AppConfig()..transportPref = 'usb',
      createTransport: (name) => null, // 无任何可用通道
    );
    await expectLater(mgr.ensureConnected(), throwsStateError);
    final s = mgr.status();
    expect(s['connected'], false);
    expect(s['state'], 'fault');
    expect((s['lastError'] as String).contains('无法连接'), isTrue);
  });
}
