/// A5 设备会话测试（直译自 tests/test_a5.py 的设备用例；
/// 超时毒化/取消语义为 Dart 侧的等价实现）。
library;

import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:paperang_p1/core/config/config.dart';
import 'package:paperang_p1/core/device/device_a5.dart';
import 'package:paperang_p1/core/errors.dart';
import 'package:paperang_p1/core/hex.dart';
import 'package:paperang_p1/core/protocol/a5.dart';

import 'helpers/fakes.dart';

final versionFrame = hexDecode(
  'a50110000115020b0001080030312e30332e3138b4204a405a',
);
final ackFrame = hexDecode('a5010800051b020300010000ac4a277f5a');

class _MediaPolarityDevice extends A5Device {
  _MediaPolarityDevice(super.transport, super.cfg);

  @override
  Future<Uint8List> query(int cmd) async =>
      Uint8List.fromList([cmd == 0x050c ? 1 : 0]);
}

void main() {
  test('传感器极性：1=合盖/有纸', () async {
    final device = _MediaPolarityDevice(FakeTransport(), AppConfig());
    device.mediaSupported = true;
    expect(await device.getMediaStatus(), {
      'lidClosed': true,
      'paperPresent': false,
    });
  });

  test('media 查询不穿插位图会话且缺纸阻断走纸', () async {
    final device = _RecordingDevice(FakeTransport(), AppConfig());
    device.mediaSupported = true;
    await expectLater(
      device.printRows(Uint8List.fromList(List.filled(48 * 120, 0))),
      throwsA(
        isA<DeviceError>().having(
          (e) => e.message,
          'message',
          contains('打印结束后'),
        ),
      ),
    );
    expect(device.commands.where((c) => c == 0x051b).length, 6);
    expect(device.commands, contains(0x051a));
    expect(device.commands, isNot(contains(0x0516)));
  });

  test('无关响应不满足等待者，超时关闭会话', () async {
    final t = FakeTransport();
    final d = A5Device(t, AppConfig());
    d.state = A5State.ready;
    final task = d.command(0x115, timeout: const Duration(milliseconds: 40));
    await Future<void>.delayed(Duration.zero); // 让 write 先发生
    t.onBytes?.call(ackFrame); // 0x51b 响应：命令不匹配
    t.onBytes?.call(a5Build(0x115)); // 请求类型 type=1：不是响应
    await expectLater(task, throwsA(isA<DeviceError>()));
    expect(t.isOpen, isFalse);
    expect(d.state, A5State.fault);
    await expectLater(d.command(0x115), throwsA(isA<DeviceError>()));
    expect(t.writes, 1);
  });

  test('中止在途命令会关闭会话，迟到响应不会误满足新请求', () async {
    final t = FakeTransport();
    final d = A5Device(t, AppConfig());
    d.state = A5State.ready;
    final task = d.command(0x115);
    await Future<void>.delayed(Duration.zero);
    d.abortPending();
    await expectLater(task, throwsA(isA<DeviceError>()));
    t.onBytes?.call(versionFrame); // 迟到的响应
    expect(t.isOpen, isFalse);
    expect(d.state, A5State.fault);
    expect(d.pendingForTest, isNull);
    await expectLater(d.command(0x115), throwsA(isA<DeviceError>()));
  });
}

class _RecordingDevice extends A5Device {
  _RecordingDevice(super.transport, super.cfg);

  final List<int> commands = [];

  @override
  Future<void> ack(
    int cmd, {
    Uint8List? content,
    Duration timeout = const Duration(seconds: 5),
  }) async {
    commands.add(cmd);
  }

  @override
  Future<Map<String, bool>> getMediaStatus() async {
    assert(commands.last == 0x051a, 'media 查询必须出现在打印结束之后');
    return {'lidClosed': true, 'paperPresent': false};
  }
}
