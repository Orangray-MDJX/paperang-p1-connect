/// PWG Raster v2 解码器（RaS2，大端，单色 1/8 位，RLE 游程）。
/// 直译自 pwg_raster.py；输出灰度位图（0=黑 255=白）。
library;

import 'dart:typed_data';

import '../render/render.dart';

const int maxPixels = 20000000;

class _Reader {
  _Reader(this.data);

  final Uint8List data;
  int pos = 0;

  int read() {
    if (pos >= data.length) {
      throw const FormatException('PWG Raster 数据截断');
    }
    return data[pos++];
  }

  Uint8List readBytes(int n) {
    if (pos + n > data.length) {
      throw const FormatException('PWG Raster 数据截断');
    }
    final out = Uint8List.sublistView(data, pos, pos + n);
    pos += n;
    return out;
  }

  bool get hasMore => pos < data.length;
}

List<MonochromeBitmap> pwgDecode(Uint8List data) {
  final src = _Reader(data);
  if (String.fromCharCodes(src.readBytes(4)) != 'RaS2') {
    throw const FormatException('需要 PWG Raster v2 (RaS2)');
  }
  final pages = <MonochromeBitmap>[];
  var pixels = 0;
  while (src.hasMore) {
    final h = src.readBytes(1796);
    final bd = ByteData.sublistView(h);
    int field(int off) => bd.getUint32(off, Endian.big);

    final width = field(372), height = field(376);
    final bpc = field(384), bpp = field(388), stride = field(392);
    final order = field(396), space = field(400), colors = field(420);
    pixels += width * height;
    if (width == 0 || height == 0 || width > 10000 || pixels > maxPixels) {
      throw const FormatException('PWG Raster 尺寸过大或无效');
    }
    if (order != 0 ||
        colors != 1 ||
        (space != 0 && space != 3 && space != 18) ||
        (bpc != 1 && bpc != 8) ||
        bpp != bpc) {
      throw const FormatException('仅支持 black/sgray 单色 1 或 8 位 PWG Raster');
    }
    final minimum = (width * bpp + 7) ~/ 8;
    if (stride < minimum || stride > minimum + 64) {
      throw const FormatException('PWG Raster 行长无效');
    }
    final raw = BytesBuilder();
    var row = 0;
    // 1/8 位单通道的压缩单位是一个字节。
    while (row < height) {
      final repeat = src.read() + 1;
      final line = BytesBuilder();
      while (line.length < stride) {
        final control = src.read();
        if (control == 128) {
          // CUPS/PWG 行尾按色空间的白填充。
          final white = space == 3 ? 0 : 255;
          final pad = Uint8List(stride - line.length)
            ..fillRange(0, stride - line.length, white);
          line.add(pad);
          break;
        }
        if (control < 128) {
          final b = src.read();
          line.add(Uint8List(control + 1)..fillRange(0, control + 1, b));
        } else {
          line.add(src.readBytes(257 - control));
        }
        if (line.length > stride) {
          throw const FormatException('PWG Raster 游程越过行尾');
        }
      }
      if (row + repeat > height) {
        throw const FormatException('PWG Raster 重复行越过页尾');
      }
      final one = line.toBytes();
      for (var i = 0; i < repeat; i++) {
        raw.add(one);
      }
      row += repeat;
    }
    pages.add(_toBitmap(raw.toBytes(), width, height, bpp, stride, space));
  }
  if (pages.isEmpty) {
    throw const FormatException('PWG Raster 没有页面');
  }
  return pages;
}

MonochromeBitmap _toBitmap(
  Uint8List raw,
  int width,
  int height,
  int bpp,
  int stride,
  int space,
) {
  final out = Uint8List(width * height);
  for (var y = 0; y < height; y++) {
    for (var x = 0; x < width; x++) {
      int g;
      if (bpp == 1) {
        // PIL '1' 语义：位 1=白。
        final bit = (raw[y * stride + (x >> 3)] >> (7 - (x & 7))) & 1;
        g = bit == 1 ? 255 : 0;
      } else {
        g = raw[y * stride + x];
      }
      if (space == 3) g = 255 - g; // K: 0=白；W/SW: 0=黑
      out[y * width + x] = g;
    }
  }
  return MonochromeBitmap(width, height, out);
}
