/// A5 帧协议（P1 新固件，实测于 01.03.18）。
///
/// 线上格式：`A5 01 | len(LE16) | payload | crc32(payload, seed)(LE32) | 5A`；
/// payload = `command(BE16) | msgType(1B) | contentLen(LE16) | content`。
/// 第三字节是消息类型（1=请求/推送，2=响应），不是事务计数——命令必须
/// 串行，超时会毒化会话（迟到响应无法与新请求区分）。
library;

import 'dart:typed_data';

import '../crc32.dart';

const int a5Seed = 0x35769521;
const int a5MaxFrame = 65535;

class A5Frame {
  A5Frame({
    required this.command,
    required this.messageType,
    required this.content,
    this.sync = 1,
  });

  final int command;
  final int messageType;
  final Uint8List content;
  final int sync;

  @override
  String toString() =>
      'A5Frame(cmd=0x${command.toRadixString(16)}, type=$messageType, '
      'len=${content.length})';
}

Uint8List a5Tlv(int key, Uint8List value) {
  final out = Uint8List(3 + value.length);
  out[0] = key;
  final bd = ByteData.sublistView(out);
  bd.setUint16(1, value.length, Endian.little);
  out.setAll(3, value);
  return out;
}

Map<int, Uint8List> parseTlv(Uint8List data) {
  final result = <int, Uint8List>{};
  var offset = 0;
  while (offset < data.length) {
    if (data.length - offset < 3) {
      throw const FormatException('truncated TLV header');
    }
    final key = data[offset];
    final size = data[offset + 1] | (data[offset + 2] << 8);
    if (size > data.length - offset - 3 || result.containsKey(key)) {
      throw const FormatException('invalid/duplicate TLV');
    }
    result[key] = Uint8List.fromList(
      data.sublist(offset + 3, offset + 3 + size),
    );
    offset += 3 + size;
  }
  return result;
}

Uint8List a5Build(int command, [Uint8List? content, int messageType = 1]) {
  final data = content ?? Uint8List(0);
  final payload = Uint8List(5 + data.length);
  final bd = ByteData.sublistView(payload);
  bd.setUint16(0, command, Endian.big);
  payload[2] = messageType;
  bd.setUint16(3, data.length, Endian.little);
  payload.setAll(5, data);
  if (payload.length > a5MaxFrame) {
    throw ArgumentError('A5 payload too large');
  }
  final out = Uint8List(4 + payload.length + 5);
  final od = ByteData.sublistView(out);
  out[0] = 0xA5;
  out[1] = 0x01;
  od.setUint16(2, payload.length, Endian.little);
  out.setAll(4, payload);
  od.setUint32(4 + payload.length, crc32(payload, a5Seed), Endian.little);
  out[out.length - 1] = 0x5A;
  return out;
}

/// 位图数据块 content：`LE16(order) | LE16(innerLen) | inner`，
/// inner = `01 | LE16(rowBytes) | LE16(offset) | 00 | LE16(rowByteCount) | rows`。
Uint8List bitmapContent(
  Uint8List rows,
  int order, {
  int rowBytes = 48,
  int offset = 0,
}) {
  if (rows.isEmpty ||
      rows.length % rowBytes != 0 ||
      order < 1 ||
      order > 65535) {
    throw ArgumentError('invalid A5 bitmap chunk');
  }
  final inner = Uint8List(8 + rows.length);
  final id = ByteData.sublistView(inner);
  inner[0] = 1;
  id.setUint16(1, rowBytes, Endian.little);
  id.setUint16(3, offset, Endian.little);
  inner[5] = 0;
  id.setUint16(6, rows.length, Endian.little);
  inner.setAll(8, rows);
  final out = Uint8List(4 + inner.length);
  final od = ByteData.sublistView(out);
  od.setUint16(0, order, Endian.little);
  od.setUint16(2, inner.length, Endian.little);
  out.setAll(4, inner);
  return out;
}

/// 流式解析器：同步字节/CRC/内层长度任一失败都滑窗 1 字节重试并计入坏帧。
class A5Parser {
  final List<int> _buf = <int>[];
  int badFrames = 0;

  List<A5Frame> feed(List<int> data) {
    _buf.addAll(data);
    final frames = <A5Frame>[];
    while (_buf.length >= 4) {
      if (_buf[0] != 0xA5 || (_buf[1] != 0 && _buf[1] != 1)) {
        _buf.removeAt(0);
        continue;
      }
      final size = _buf[2] | (_buf[3] << 8);
      if (size < 5) {
        badFrames++;
        _buf.removeAt(0);
        continue;
      }
      final total = size + 9;
      if (_buf.length < total) break;
      final payload = Uint8List.fromList(_buf.sublist(4, 4 + size));
      final crc =
          _buf[4 + size] |
          (_buf[5 + size] << 8) |
          (_buf[6 + size] << 16) |
          (_buf[7 + size] << 24);
      final innerLen = payload[3] | (payload[4] << 8);
      if (_buf[total - 1] != 0x5A ||
          crc != crc32(payload, a5Seed) ||
          innerLen != size - 5) {
        badFrames++;
        _buf.removeAt(0);
        continue;
      }
      final command = (payload[0] << 8) | payload[1];
      frames.add(
        A5Frame(
          command: command,
          messageType: payload[2],
          content: Uint8List.fromList(payload.sublist(5)),
          sync: _buf[1],
        ),
      );
      _buf.removeRange(0, total);
    }
    return frames;
  }
}
