/// 模拟打印机传输层：按 P1 01.03.18 抓包行为逐条应答 type2 帧。
///
/// 用途：①单元/端到端测试（无真机）；②App 演示模式（模拟器上完整体验
/// 打印流程）。记录主机下发的全部命令，供字节级断言。
library;

import 'dart:typed_data';

import '../protocol/a5.dart';
import 'transport.dart';

class SimulatedPrinter extends Transport {
  SimulatedPrinter({this.name = 'usb'}) {
    maxPayload = 1024;
  }

  @override
  final String name;

  @override
  bool isOpen = true;

  final A5Parser _parser = A5Parser();

  /// 主机→打印机全部命令 (command, content)。
  final List<(int, Uint8List)> commands = [];

  final Map<int, Uint8List> values = {
    0x0115: _ascii('01.03.18'),
    0x0102: _ascii('P1FAKE0000000001'),
    0x0114: _le16(1024),
    0x0504: _le16(200),
    0x0502: Uint8List.fromList([0x01, 0x02, 0x00, 0x39, 0x00]),
    0x050c: Uint8List.fromList([0x01]),
    0x050d: Uint8List.fromList([0x01]),
    0x010b: _le16(990),
    0x0109: _le16(0),
  };

  static Uint8List _ascii(String s) => Uint8List.fromList(s.codeUnits);

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
