/// 测试助手：FakePrinter 固件模拟器与哑传输（直译自 pytest 同名设施）。
///
/// FakePrinter 按 P1 01.03.18 抓包行为逐条回 type2 应答帧，并记录主机
/// 下发的全部命令，供"字节精确到 0x0511/命令序列"类断言使用。
library;

import 'dart:typed_data';

import 'package:paperang_p1/core/protocol/a5.dart';
import 'package:paperang_p1/core/transport/transport.dart';

class FakeTransport implements Transport {
  @override
  String get name => 'usb';

  @override
  int maxPayload = 480;

  @override
  void Function(Uint8List data)? onBytes;

  @override
  void Function()? onDisconnected;

  @override
  bool isOpen = true;

  int writes = 0;

  @override
  Future<void> open() async {}

  @override
  Future<void> close() async {
    isOpen = false;
  }

  @override
  Future<void> write(Uint8List data) async {
    writes++;
  }
}

class FakePrinter implements Transport {
  FakePrinter() : _parser = A5Parser();

  @override
  String get name => 'usb';

  @override
  int maxPayload = 1024;

  @override
  void Function(Uint8List data)? onBytes;

  @override
  void Function()? onDisconnected;

  @override
  bool isOpen = true;

  final A5Parser _parser;

  /// 主机→打印机全部命令 (command, content)。
  final List<(int, Uint8List)> commands = [];

  final Map<int, Uint8List> values = {
    0x0115: Uint8List.fromList('01.03.18'.codeUnits),
    0x0102: Uint8List.fromList('P1FAKE0000000001'.codeUnits),
    0x0114: _le16(1024),
    0x0504: _le16(200),
    0x0502: Uint8List.fromList([0x01, 0x02, 0x00, 0x39, 0x00]),
    0x050c: Uint8List.fromList([0x01]),
    0x050d: Uint8List.fromList([0x01]),
    0x010b: _le16(990),
    0x0109: _le16(0),
  };

  static Uint8List _le16(int v) =>
      Uint8List.fromList([v & 0xFF, (v >> 8) & 0xFF]);

  @override
  Future<void> open() async {}

  @override
  Future<void> close() async {
    isOpen = false;
    onDisconnected?.call();
  }

  @override
  Future<void> write(Uint8List data) async {
    for (final frame in _parser.feed(data)) {
      commands.add((frame.command, frame.content));
      final value = values[frame.command];
      onBytes?.call(a5Build(frame.command, a5Tlv(1, value ?? Uint8List(0)), 2));
    }
  }
}
