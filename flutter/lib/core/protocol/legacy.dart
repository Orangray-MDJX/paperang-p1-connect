/// 老款机型帧协议（gen1/gen2）：封包、CRC 会话密钥、流式解析。
///
/// 帧格式：`0x02 | cmd(1B) | index(1B) | len(u16 LE) | payload |
/// crc32(payload, seed)(u32 LE) | 0x03`。gen1 握手协商会话密钥，
/// gen2 发送固定 magic 后全程种子 0。
library;

import 'dart:typed_data';

import '../crc32.dart';

const int stx = 0x02;
const int etx = 0x03;
const int headerLen = 5; // stx + cmd + index + len(2)
const int tailLen = 5; // crc(4) + etx
const int standardKey = 0x35769521;

/// 命令表（0x00-0x31）。查询类指令的应答 cmd = 请求 cmd + 1（SENT_*）。
abstract final class Cmd {
  static const int printData = 0x00;
  static const int printDataCompress = 0x01;
  static const int firmwareData = 0x02;
  static const int usbUpdateFirmware = 0x03;
  static const int getVersion = 0x04;
  static const int sentVersion = 0x05;
  static const int getModel = 0x06;
  static const int sentModel = 0x07;
  static const int getBtMac = 0x08;
  static const int sentBtMac = 0x09;
  static const int getSn = 0x0A;
  static const int sentSn = 0x0B;
  static const int getStatus = 0x0C;
  static const int sentStatus = 0x0D;
  static const int getVoltage = 0x0E;
  static const int sentVoltage = 0x0F;
  static const int getBatStatus = 0x10;
  static const int sentBatStatus = 0x11;
  static const int getTemp = 0x12;
  static const int sentTemp = 0x13;
  static const int setFactoryStatus = 0x14;
  static const int getFactoryStatus = 0x15;
  static const int sentFactoryStatus = 0x16;
  static const int sentBtStatus = 0x17;
  static const int setCrcKey = 0x18;
  static const int setHeatDensity = 0x19;
  static const int feedLine = 0x1A;
  static const int printTestPage = 0x1B;
  static const int getHeatDensity = 0x1C;
  static const int sentHeatDensity = 0x1D;
  static const int setPowerDownTime = 0x1E;
  static const int getPowerDownTime = 0x1F;
  static const int sentPowerDownTime = 0x20;
  static const int feedToHeadLine = 0x21;
  static const int printDefaultPara = 0x22;
  static const int getBoardVersion = 0x23;
  static const int sentBoardVersion = 0x24;
  static const int getHwInfo = 0x25;
  static const int sentHwInfo = 0x26;
  static const int setMaxGapLength = 0x27;
  static const int getMaxGapLength = 0x28;
  static const int sentMaxGapLength = 0x29;
  static const int getGapLength = 0x2A;
  static const int sentGapLength = 0x2B;
  static const int setPaperType = 0x2C;
  static const int getCountryName = 0x2D;
  static const int sentCountryName = 0x2E;
  static const int disconnectBt = 0x2F;
  static const int getDevName = 0x30;
  static const int sentDevName = 0x31;
}

class LegacyFrame {
  LegacyFrame({required this.cmd, this.index = 0, Uint8List? payload})
    : payload = payload ?? Uint8List(0);

  final int cmd;
  final int index;
  final Uint8List payload;

  Uint8List encode(int sessionKey) {
    final out = Uint8List(headerLen + payload.length + tailLen);
    final bd = ByteData.sublistView(out);
    out[0] = stx;
    out[1] = cmd & 0xFF;
    out[2] = index & 0xFF;
    bd.setUint16(3, payload.length, Endian.little);
    out.setAll(headerLen, payload);
    bd.setUint32(
      headerLen + payload.length,
      crc32(payload, sessionKey),
      Endian.little,
    );
    out[out.length - 1] = etx;
    return out;
  }

  @override
  String toString() =>
      'LegacyFrame(cmd=0x${cmd.toRadixString(16).padLeft(2, '0')}, '
      'index=0x${index.toRadixString(16).padLeft(2, '0')}, len=${payload.length})';
}

Uint8List legacyBuild(
  int cmd, {
  Uint8List? payload,
  int index = 0,
  int sessionKey = standardKey,
}) {
  return LegacyFrame(
    cmd: cmd,
    index: index,
    payload: payload,
  ).encode(sessionKey);
}

/// gen1 握手：payload = LE32(newKey ^ standardKey)，帧本身用固定种子。
Uint8List handshakeBytes(int newKey) {
  final payload = Uint8List(4);
  ByteData.sublistView(payload)
      .setUint32(0, newKey ^ standardKey, Endian.little);
  return legacyBuild(Cmd.setCrcKey, payload: payload, sessionKey: standardKey);
}

/// gen2 固件固定握手包：CRC 以种子 0 计算，此后会话种子保持 0。
final Uint8List gen2Handshake = Uint8List.fromList([
  0x02, 0x18, 0x00, 0x04, 0x00, 0x21, 0x95, 0x76, //
  0x35, 0x1C, 0xDF, 0x44, 0x21, 0x03,
]);

/// 设备对指令的即时应答：cmd 同值、payload 为单字节 0。
bool isAck(LegacyFrame frame, int ofCmd) =>
    frame.cmd == ofCmd && frame.payload.length == 1 && frame.payload[0] == 0;

/// 流式解析器。CRC 按候选种子逐个尝试（处理握手 ACK 新旧 key 二义性）；
/// 全部失败时跳 1 字节重新同步。
class LegacyFrameParser {
  LegacyFrameParser({List<int>? seeds}) : seeds = seeds ?? [standardKey];

  final List<int> seeds;
  final List<int> _buf = <int>[];

  List<LegacyFrame> feed(List<int> data) {
    _buf.addAll(data);
    final frames = <LegacyFrame>[];
    while (true) {
      final result = _tryParseOne();
      if (result.frame != null) frames.add(result.frame!);
      if (result.consumed <= 0) break;
      _buf.removeRange(0, result.consumed);
    }
    return frames;
  }

  _ParseResult _tryParseOne() {
    var start = 0;
    while (true) {
      // 找 STX
      var found = -1;
      for (var i = start; i < _buf.length; i++) {
        if (_buf[i] == stx) {
          found = i;
          break;
        }
      }
      if (found < 0) {
        // 无帧头：清掉全部（保留末尾 1 字节以防 STX 被拆开）
        return _ParseResult(null, _buf.length - 1);
      }
      start = found;
      if (_buf.length - start < headerLen) {
        return _ParseResult(null, start); // 帧头不完整，丢弃前面的噪声
      }
      final cmd = _buf[start + 1];
      final index = _buf[start + 2];
      final plen = _buf[start + 3] | (_buf[start + 4] << 8);
      final total = headerLen + plen + tailLen;
      if (_buf.length - start < total) {
        return _ParseResult(null, start);
      }
      final payload = Uint8List.fromList(
        _buf.sublist(start + headerLen, start + headerLen + plen),
      );
      final crc =
          _buf[start + headerLen + plen] |
          (_buf[start + headerLen + plen + 1] << 8) |
          (_buf[start + headerLen + plen + 2] << 16) |
          (_buf[start + headerLen + plen + 3] << 24);
      if (_buf[start + total - 1] != etx ||
          !seeds.any((s) => crc == crc32(payload, s))) {
        return _ParseResult(null, start + 1); // 校验失败，跳 1 字节重同步
      }
      return _ParseResult(
        LegacyFrame(cmd: cmd, index: index, payload: payload),
        total,
      );
    }
  }
}

class _ParseResult {
  _ParseResult(this.frame, this.consumed);

  final LegacyFrame? frame;
  final int consumed;
}
