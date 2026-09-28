/// 十六进制编解码（帧调试日志与测试向量共用）。
library;

import 'dart:typed_data';

Uint8List hexDecode(String s) {
  final clean = s.replaceAll(RegExp(r'[\s]'), '');
  if (clean.length.isOdd) {
    throw FormatException('hex string length must be even', s);
  }
  final out = Uint8List(clean.length ~/ 2);
  for (var i = 0; i < out.length; i++) {
    final byte = int.tryParse(clean.substring(2 * i, 2 * i + 2), radix: 16);
    if (byte == null) {
      throw FormatException('invalid hex byte at ${2 * i}', s);
    }
    out[i] = byte;
  }
  return out;
}

String hexEncode(List<int> data) =>
    data.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
