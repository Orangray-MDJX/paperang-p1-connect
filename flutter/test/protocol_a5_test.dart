/// A5 协议黄金向量测试（向量来自 P1 01.03.18 真机抓包，直译自
/// tests/test_a5.py 的协议层用例）。
library;

import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:paperang_p1/core/hex.dart';
import 'package:paperang_p1/core/protocol/a5.dart';

import 'helpers/rfcomm_frame.dart';

final version = hexDecode('a50110000115020b0001080030312e30332e3138b4204a405a');
final ack = hexDecode('a5010800051b020300010000ac4a277f5a');

void main() {
  test('真机 media 帧与 TLV 值', () {
    final frames = <(String, int, Uint8List)>[
      (
        'a5010900050c02040001010000b945a4675a',
        0x050c,
        Uint8List.fromList([0x00]),
      ),
      (
        'a5010900050d0204000101000027450eab5a',
        0x050d,
        Uint8List.fromList([0x00]),
      ),
      (
        'a5010a000504020500010200c800e41be16c5a',
        0x0504,
        Uint8List.fromList([0xc8, 0x00]),
      ),
      (
        'a5010d000502020800010500010200390033677db05a',
        0x0502,
        Uint8List.fromList([0x01, 0x02, 0x00, 0x39, 0x00]),
      ),
    ];
    for (final (raw, cmd, value) in frames) {
      final frame = A5Parser().feed(hexDecode(raw)).single;
      expect(frame.command, cmd);
      expect(parseTlv(frame.content)[1], value);
    }
  });

  test('每个切分点分块喂入都能完整解析', () {
    for (var split = 0; split <= version.length; split++) {
      final p = A5Parser();
      final frames = [
        ...p.feed(version.sublist(0, split)),
        ...p.feed(version.sublist(split) + ack),
      ];
      expect(frames.map((f) => f.command), [
        0x115,
        0x51b,
      ], reason: 'split at $split');
      expect(frames[0].messageType, 2);
      expect(
        parseTlv(frames[0].content)[1],
        Uint8List.fromList('01.03.18'.codeUnits),
      );
      expect(parseTlv(frames[1].content), {1: Uint8List(0)});
    }
  });

  test('CRC 损坏/噪声/内层长度错误时滑窗重同步', () {
    final bad = Uint8List.fromList(version);
    bad[12] ^= 1;
    final p = A5Parser();
    final out = p.feed(utf8Bytes('noise') + bad + ack);
    expect(out.length, 1);
    expect(out[0].command, 0x51b);
    expect(p.badFrames, greaterThan(0));
    expect(
      () => parseTlv(
        hexDecode(
          '010400'
          '78',
        ),
      ),
      throwsFormatException,
    );
  });

  test('位图块头与真机抓包一致', () {
    final content = bitmapContent(
      Uint8List.fromList(List.filled(960, 0xFF)),
      1,
    );
    expect(hexEncode(content.sublist(0, 12)), '0100c803013000000000c003');
    expect(content.length, 972);
    final frame = A5Parser().feed(a5Build(0x51b, content)).single;
    expect(frame.content, content);
  });

  test('RFCOMM credit 字节不截断 A5 帧尾', () {
    final query = a5Build(0x115);
    final packet = Uint8List.fromList([
      (2 << 2) | 3,
      0xFF,
      (query.length << 1) | 1,
      7,
      ...query,
      0x99,
    ]);
    final (dlci, ftype, credit, user) = parseRfcomm(packet);
    expect(dlci, 2);
    expect(ftype, 0xEF);
    expect(credit, 7);
    expect(user, query);
    expect(
      () => parseRfcomm(packet.sublist(0, packet.length - 2)),
      throwsFormatException,
    );
  });
}

Uint8List utf8Bytes(String s) => Uint8List.fromList(s.codeUnits);
