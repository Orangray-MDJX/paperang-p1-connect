/// 测试助手：哑传输（直译自 pytest FakeTransport）。
library;

import 'dart:typed_data';

import 'package:paperang_p1/core/transport/transport.dart';

class FakeTransport implements Transport {
  @override
  String get name => 'usb';

  @override
  int maxPayload = 480;

  @override
  String? lastError;

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
