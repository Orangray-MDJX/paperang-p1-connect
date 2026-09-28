/// Apple Raster (UNIRAST) W8 解码器（对齐 libcups raster-stream.c）。
/// 直译自 urf_raster.py；输出灰度位图，RLE 单位为像素。
library;

import 'dart:typed_data';

import '../render/render.dart';
import 'pwg_raster.dart' show maxPixels;

class _Reader {
  _Reader(this.data);

  final Uint8List data;
  int pos = 0;

  int read() {
    if (pos >= data.length) {
      throw const FormatException('URF data truncated');
    }
    return data[pos++];
  }

  Uint8List readBytes(int n) {
    if (pos + n > data.length) {
      throw const FormatException('URF data truncated');
    }
    final out = Uint8List.sublistView(data, pos, pos + n);
    pos += n;
    return out;
  }

  bool get hasMore => pos < data.length;
}

List<MonochromeBitmap> urfDecode(Uint8List data) {
  final src = _Reader(data);
  if (String.fromCharCodes(src.readBytes(8)) != 'UNIRAST\u0000') {
    throw const FormatException('Invalid Apple Raster signature');
  }
  final count = ByteData.sublistView(src.readBytes(4)).getUint32(0, Endian.big);
  final pages = <MonochromeBitmap>[];
  var pixels = 0;
  while (src.hasMore) {
    final header = src.readBytes(32);
    final hd = ByteData.sublistView(header);
    final width = hd.getUint32(12, Endian.big);
    final height = hd.getUint32(16, Endian.big);
    final dpi = hd.getUint32(20, Endian.big);
    pixels += width * height;
    if (header[0] != 8 || (header[1] != 0 && header[1] != 4)) {
      throw const FormatException(
        'Only W8 grayscale Apple Raster is supported',
      );
    }
    if (width == 0 ||
        height == 0 ||
        width > 10000 ||
        pixels > maxPixels ||
        dpi == 0) {
      throw const FormatException(
        'Invalid or oversized Apple Raster dimensions',
      );
    }
    final raw = BytesBuilder();
    var row = 0;
    while (row < height) {
      final repeat = src.read() + 1;
      final line = BytesBuilder();
      while (line.length < width) {
        final control = src.read();
        if (control == 128) {
          final pad = Uint8List(width - line.length)
            ..fillRange(0, width - line.length, 255);
          line.add(pad);
          break;
        }
        if (control < 128) {
          final b = src.read();
          line.add(Uint8List(control + 1)..fillRange(0, control + 1, b));
        } else {
          line.add(src.readBytes(257 - control));
        }
        if (line.length > width) {
          throw const FormatException('URF run exceeds row');
        }
      }
      if (row + repeat > height) {
        throw const FormatException('URF row repeat exceeds page');
      }
      final one = line.toBytes();
      for (var i = 0; i < repeat; i++) {
        raw.add(one);
      }
      row += repeat;
    }
    final bytes = raw.toBytes();
    pages.add(MonochromeBitmap(width, height, bytes));
  }
  if (pages.isEmpty ||
      (count != 0 && count != 0xffffffff && count != pages.length)) {
    throw const FormatException('URF page count mismatch');
  }
  return pages;
}
