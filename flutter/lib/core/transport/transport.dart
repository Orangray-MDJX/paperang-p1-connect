/// 传输层契约（对应 Python 版 transport.py）。
///
/// 一帧一 write；收数与断连通过回调上报。Android 实现见
/// platform/ 下的平台通道（经典蓝牙 RFCOMM、USB bulk），调试回环见
/// core/transport/loopback.dart。
library;

import 'dart:typed_data';

abstract class Transport {
  String get name;

  /// 单次 write 建议的最大载荷（设备/通道相关，协议层用于分块）。
  int maxPayload = 480;

  void Function(Uint8List data)? onBytes;
  void Function()? onDisconnected;

  Future<void> open();
  Future<void> close();
  Future<void> write(Uint8List data);
  bool get isOpen;
}
