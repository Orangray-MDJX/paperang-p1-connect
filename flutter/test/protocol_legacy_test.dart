/// 老款 gen1/gen2 帧协议黄金向量测试（向量来自官方 App 抓包与开源实现，
/// 直译自 tests/test_protocol.py）。
library;

import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:paperang_p1/core/crc32.dart';
import 'package:paperang_p1/core/hex.dart';
import 'package:paperang_p1/core/protocol/legacy.dart';

/// 官方 App 抓包会话密钥（已复算验证）。
const sessionKey = 0x4E048354;

final vHandshakeIhciah = hexDecode('02 18 00 04 00 78 7A CE 33 2C 89 80 F0 03');
final vHandshakeZero = hexDecode('02 18 00 04 00 21 95 76 35 1C DF 44 21 03');
final vHandshakeOfficial = hexDecode(
  '02 18 00 04 00 5E 5A C4 72 A2 A6 A0 B6 03',
);
final vAckStd = hexDecode('02 00 00 01 00 00 46 89 5E 9E 03');
final vPaperType = hexDecode('02 2C 00 01 00 00 E3 7E 4A BE 03');
final vFeed10 = hexDecode('02 1A 00 02 00 0A 00 BB FE 50 11 03');
final vPrint432ff = Uint8List.fromList([
  ...hexDecode('02 00 00 B0 01'),
  ...List.filled(432, 0xFF),
  ...hexDecode('43 E1 2E 36 03'),
]);

void main() {
  test('三组握手向量', () {
    expect(handshakeBytes(0x06B8EF59), vHandshakeIhciah);
    expect(handshakeBytes(0), vHandshakeZero);
    expect(handshakeBytes(0x47B2CF7F), vHandshakeOfficial);
  });

  test('官方抓包帧构建逐字节复现', () {
    expect(
      legacyBuild(
        Cmd.setPaperType,
        payload: Uint8List.fromList([0x00]),
        sessionKey: sessionKey,
      ),
      vPaperType,
    );
    expect(
      legacyBuild(
        Cmd.feedLine,
        payload: Uint8List.fromList([0x0A, 0x00]),
        sessionKey: sessionKey,
      ),
      vFeed10,
    );
    expect(
      legacyBuild(
        Cmd.printData,
        payload: Uint8List.fromList(List.filled(432, 0xFF)),
        index: 0,
        sessionKey: sessionKey,
      ),
      vPrint432ff,
    );
  });

  test('解析官方帧序列', () {
    final parser = LegacyFrameParser(seeds: [standardKey, sessionKey]);
    final frames = parser.feed(vHandshakeOfficial + vPaperType + vFeed10);
    expect(frames.map((f) => f.cmd), [
      Cmd.setCrcKey,
      Cmd.setPaperType,
      Cmd.feedLine,
    ]);
  });

  test('噪声与任意分块喂入', () {
    final data = Uint8List.fromList([
      ...utf8Bytes('\x00\xff garbage'),
      ...vAckStd,
      ...vFeed10,
    ]);
    for (var cut = 1; cut < data.length; cut++) {
      final parser = LegacyFrameParser(seeds: [standardKey, sessionKey]);
      final out = [
        ...parser.feed(data.sublist(0, cut)),
        ...parser.feed(data.sublist(cut)),
      ];
      expect(
        out.map((f) => '${f.cmd}:${f.payload.length}:${hexEncode(f.payload)}'),
        [
          '${Cmd.printData}:1:00', // ACK(cmd=0, payload=0)
          '${Cmd.feedLine}:2:0a00',
        ],
        reason: 'cut at $cut',
      );
    }
  });

  test('isAck 语义', () {
    final f = LegacyFrameParser(seeds: [standardKey]).feed(vAckStd).single;
    expect(isAck(f, Cmd.printData), isTrue);
    expect(isAck(f, Cmd.setCrcKey), isFalse);
  });

  test('CRC 与 zlib 语义一致', () {
    expect(crc32([0x00], standardKey), 0x9E5E8946); // 由 vAckStd 尾部反推
  });

  test('gen2 固定握手包常量', () {
    expect(gen2Handshake, hasLength(14));
    // 与 Python GEN2_HANDSHAKE 逐字节一致
    expect(hexEncode(gen2Handshake), '0218000400219576351cdf442103');
  });
}

Uint8List utf8Bytes(String s) => Uint8List.fromList(s.codeUnits);
