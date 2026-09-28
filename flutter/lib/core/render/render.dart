/// 渲染管线：图像 → 384 点宽 1-bit 位图 → 行字节流（对应 render.py）。
///
/// 约定与桌面版一致：灰度 0=黑 255=白；协议行字节 1=黑、MSB 在前，
/// 因此打包时黑(0)映为 1。文本与自检图依赖系统字体，在 services/ 层
/// 用 TextPainter 渲染（不进纯 Dart 核心）。
library;

import 'dart:typed_data';

import 'package:image/image.dart' as img;

import '../constants.dart';
import '../errors.dart';

/// 1-bit 位（像素值 0 或 255）。
class MonochromeBitmap {
  MonochromeBitmap(this.width, this.height, this.pixels)
    : assert(pixels.length == width * height);

  final int width;
  final int height;
  final Uint8List pixels; // 0=黑 255=白
}

img.Image loadImage(Uint8List bytes) {
  final decoded = img.decodeImage(bytes);
  if (decoded == null) {
    throw DeviceError('无法解码图片');
  }
  return decoded;
}

/// 缩放到指定宽度、透明贴白、可选反转、抖动成 1-bit。
MonochromeBitmap prepare(
  img.Image source, {
  int width = lineDots,
  String dither = 'floyd-steinberg',
  int threshold = 128,
  bool invert = false,
}) {
  var image = source;
  if (width != image.width) {
    final h = (image.height * width / image.width).round().clamp(1, 1 << 24);
    image = img.copyResize(
      image,
      width: width,
      height: h,
      interpolation: img.Interpolation.cubic,
    );
  }
  final w = image.width, h = image.height;
  // 灰度化 + 透明贴白 + 可选反转，一次性收敛成 0..255 灰度缓冲。
  final gray = Uint8List(w * h);
  for (var y = 0; y < h; y++) {
    for (var x = 0; x < w; x++) {
      final p = image.getPixel(x, y);
      var g = (0.299 * p.r + 0.587 * p.g + 0.114 * p.b).round();
      if (p.a < 255) {
        // 透明像素按白纸处理
        g = (g * p.a / 255 + 255 * (255 - p.a) / 255).round();
      }
      gray[y * w + x] = invert ? 255 - g.clamp(0, 255) : g.clamp(0, 255);
    }
  }
  switch (dither) {
    case 'threshold':
      return _threshold(gray, w, h, threshold);
    case 'atkinson':
      return _atkinson(gray, w, h);
    default:
      return _floydSteinberg(gray, w, h);
  }
}

MonochromeBitmap _threshold(Uint8List gray, int w, int h, int threshold) {
  final out = Uint8List(w * h);
  for (var i = 0; i < gray.length; i++) {
    out[i] = gray[i] >= threshold ? 255 : 0;
  }
  return MonochromeBitmap(w, h, out);
}

MonochromeBitmap _atkinson(Uint8List gray, int w, int h) {
  // Atkinson：err//8 扩散到 6 个邻居（与桌面版逐字节一致）。
  final px = Uint8List.fromList(gray);
  const neighbors = [(1, 0), (2, 0), (-1, 1), (0, 1), (1, 1), (0, 2)];
  for (var y = 0; y < h; y++) {
    for (var x = 0; x < w; x++) {
      final old = px[y * w + x];
      final newV = old >= 128 ? 255 : 0;
      final err = (old - newV) ~/ 8;
      px[y * w + x] = newV;
      for (final (dx, dy) in neighbors) {
        final nx = x + dx, ny = y + dy;
        if (nx >= 0 && nx < w && ny >= 0 && ny < h) {
          final idx = ny * w + nx;
          px[idx] = (px[idx] + err).clamp(0, 255);
        }
      }
    }
  }
  return MonochromeBitmap(w, h, px);
}

MonochromeBitmap _floydSteinberg(Uint8List gray, int w, int h) {
  // 标准 FS 核：右 7/16、左下 3/16、下 5/16、右下 1/16。
  final px = Int16List.fromList(gray);
  for (var y = 0; y < h; y++) {
    for (var x = 0; x < w; x++) {
      final old = px[y * w + x];
      final newV = old >= 128 ? 255 : 0;
      final err = old - newV;
      px[y * w + x] = newV;
      void push(int nx, int ny, int factor) {
        if (nx >= 0 && nx < w && ny >= 0 && ny < h) {
          final idx = ny * w + nx;
          px[idx] = (px[idx] + err * factor ~/ 16).clamp(0, 255);
        }
      }

      push(x + 1, y, 7);
      push(x - 1, y + 1, 3);
      push(x, y + 1, 5);
      push(x + 1, y + 1, 1);
    }
  }
  return MonochromeBitmap(w, h, Uint8List.fromList(px));
}

/// 1-bit 图 → 行字节流（1=黑、MSB 在前）。
Uint8List rowsFromImage(MonochromeBitmap bitmap) {
  if (bitmap.width != lineDots) {
    throw DeviceError('图像宽度应为 $lineDots，实际 ${bitmap.width}');
  }
  final out = Uint8List(lineBytes * bitmap.height);
  for (var y = 0; y < bitmap.height; y++) {
    for (var x = 0; x < lineDots; x++) {
      if (bitmap.pixels[y * lineDots + x] == 0) {
        out[y * lineBytes + (x >> 3)] |= 0x80 >> (x & 7);
      }
    }
  }
  return out;
}

/// PNG → 行字节流（device_a5.printPng 的入口，抖动固定 threshold）。
Uint8List rowsFromPng(Uint8List png, {int threshold = 128}) => rowsFromImage(
  prepare(loadImage(png), dither: 'threshold', threshold: threshold),
);

/// 行字节流总行数。
int rowsToLineCount(int byteLength) {
  if (byteLength % lineBytes != 0) {
    throw DeviceError('位图长度必须是 $lineBytes 的倍数');
  }
  return byteLength ~/ lineBytes;
}
