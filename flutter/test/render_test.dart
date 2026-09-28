/// 渲染管线测试（直译自 tests/test_render.py 的位打包/缩放/反转用例）。
library;

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:paperang_p1/core/constants.dart';
import 'package:paperang_p1/core/render/render.dart';

void main() {
  test('位打包约定：1=黑 MSB 在前，全黑打包后每字节 0xFF', () {
    final black = img.Image(width: lineDots, height: 4);
    for (final p in black) {
      p.setRgb(0, 0, 0);
    }
    final rows = rowsFromImage(prepare(black, dither: 'threshold'));
    expect(rows.length, lineBytes * 4);
    expect(rows.every((b) => b == 0xFF), isTrue);

    final white = img.Image(width: lineDots, height: 4);
    for (final p in white) {
      p.setRgb(255, 255, 255);
    }
    final rowsW = rowsFromImage(prepare(white, dither: 'threshold'));
    expect(rowsW.every((b) => b == 0x00), isTrue);
  });

  test('接受编码字节（PNG 解码）', () {
    final image = img.Image(width: 384, height: 8);
    for (final p in image) {
      p.setRgb(0, 0, 0);
    }
    final loaded = loadImage(img.encodePng(image));
    expect(loaded.width, image.width);
    expect(loaded.height, image.height);
    expect(loaded.getPixel(0, 0).r, 0);
  });

  test('左半黑右半白：每行前 24 字节 FF、后 24 字节 00', () {
    final image = img.Image(width: lineDots, height: 2);
    for (final p in image) {
      final black = p.x < lineDots ~/ 2;
      p.setRgb(black ? 0 : 255, black ? 0 : 255, black ? 0 : 255);
    }
    final rows = rowsFromImage(prepare(image, dither: 'threshold'));
    for (var y = 0; y < 2; y++) {
      expect(rows.sublist(y * 48, y * 48 + 24).every((b) => b == 0xFF), isTrue);
      expect(
        rows.sublist(y * 48 + 24, y * 48 + 48).every((b) => b == 0x00),
        isTrue,
      );
    }
  });

  test('等比缩放到 384 宽', () {
    final image = img.Image(width: 768, height: 100);
    for (final p in image) {
      p.setRgb(128, 128, 128);
    }
    final p = prepare(image, dither: 'threshold');
    expect(p.width, lineDots);
    expect(p.height, 50);
  });

  test('反转：黑底转白', () {
    final image = img.Image(width: lineDots, height: 2);
    for (final p in image) {
      p.setRgb(0, 0, 0);
    }
    final rows = rowsFromImage(
      prepare(image, dither: 'threshold', invert: true),
    );
    expect(rows.every((b) => b == 0x00), isTrue);
  });

  test('floyd-steinberg 在纯灰图上产生黑白混合', () {
    final image = img.Image(width: lineDots, height: 40);
    for (final p in image) {
      p.setRgb(128, 128, 128);
    }
    final bitmap = prepare(image, dither: 'floyd-steinberg');
    expect(bitmap.pixels.contains(0), isTrue);
    expect(bitmap.pixels.contains(255), isTrue);
  });

  test('透明像素按白纸处理', () {
    final image = img.Image(width: lineDots, height: 4, numChannels: 4);
    for (final p in image) {
      p
        ..r = 0
        ..g = 0
        ..b = 0
        ..a = 0; // 全透明
    }
    final rows = rowsFromImage(prepare(image, dither: 'threshold'));
    expect(rows.every((b) => b == 0x00), isTrue);
  });

  test('rowsFromPng 端到端：PNG → 行字节', () async {
    final image = img.Image(width: 384, height: 3);
    for (final p in image) {
      p.setRgb(0, 0, 0);
    }
    final png = Uint8List.fromList(img.encodePng(image));
    final rows = rowsFromPng(png);
    expect(rows.length, lineBytes * 3);
    expect(rows.every((b) => b == 0xFF), isTrue);
    expect(Directory.systemTemp.existsSync(), isTrue); // io 可用性冒烟
  });
}
