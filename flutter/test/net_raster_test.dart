/// PWG/URF 解码黄金向量测试（直译自 tests/test_ipp.py 与 test_lan.py）。
library;

import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:paperang_p1/core/net/pwg_raster.dart';
import 'package:paperang_p1/core/net/urf_raster.dart';
import 'package:paperang_p1/core/render/render.dart';

Uint8List raster({
  int width = 16,
  int height = 2,
  int space = 3,
  List<int> body = const [0x01, 0x01, 0x80],
}) {
  final h = Uint8List(1796);
  final hd = ByteData.sublistView(h);
  void field(int off, int v) => hd.setUint32(off, v, Endian.big);

  field(372, width);
  field(376, height);
  field(384, 1);
  field(388, 1);
  field(392, (width + 7) ~/ 8);
  field(396, 0);
  field(400, space);
  field(420, 1);
  return Uint8List.fromList([...'RaS2'.codeUnits, ...h, ...body]);
}

void main() {
  test('PWG 行重复/极性/字面游程', () {
    final image = pwgDecode(raster())[0];
    expect(image.width, 16);
    expect(image.height, 2);
    expect(image.pixels[0], 0); // (0,0) 黑
    expect(image.pixels[1 * 16 + 1], 255); // (1,1) 白
    final literal = pwgDecode(
      raster(height: 1, body: [0x00, 0xff, 0x80, 0x01]),
    )[0];
    expect(literal.pixels[0], 0); // (0,0)
    expect(literal.pixels[15], 0); // (15,0)
  });

  test('PWG 越界与截断报错', () {
    expect(
      () => pwgDecode(raster(body: [0x02, 0x01, 0x80])),
      throwsFormatException,
    );
    expect(
      () => pwgDecode(raster().sublist(0, raster().length - 1)),
      throwsFormatException,
    );
  });

  test('URF 字面/重复/非法尺寸/页数', () {
    Uint8List urf({
      List<int> body = const [0x01, 0xff, 0x00, 0xff],
      int count = 1,
    }) {
      final header = Uint8List(32);
      final hd = ByteData.sublistView(header);
      header[0] = 8;
      hd.setUint32(12, 2, Endian.big);
      hd.setUint32(16, 2, Endian.big);
      hd.setUint32(20, 300, Endian.big);
      return Uint8List.fromList([
        ...'UNIRAST\u0000'.codeUnits,
        ...Uint8List(4)..buffer.asByteData().setUint32(0, count, Endian.big),
        ...header,
        ...body,
      ]);
    }

    final image = urfDecode(urf())[0];
    expect(image.size, (2, 2));
    expect(image.pixels[1 * 2 + 0], 0); // (0,1) 黑
    expect(image.pixels[1 * 2 + 1], 255); // (1,1) 白
    expect(
      () => urfDecode(urf(body: [0x02, 0xff, 0x00, 0xff])),
      throwsFormatException,
    ); // 重复行越过页尾
    expect(
      () => urfDecode(urf().sublist(0, urf().length - 1)),
      throwsFormatException,
    ); // 截断
    final badDims = Uint8List.fromList([
      ...'UNIRAST\u0000'.codeUnits,
      ...List.filled(4, 0),
      ...Uint8List(32)..[0] = 8,
      0x01,
      0xff,
    ]);
    expect(() => urfDecode(badDims), throwsFormatException);
    expect(() => urfDecode(urf(count: 5)), throwsFormatException); // 页数不符
  });
}

extension on MonochromeBitmap {
  (int, int) get size => (width, height);
}
