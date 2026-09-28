/// 文本渲染：TextPainter → 384 点宽 PNG（系统字体；对应桌面版
/// render.text_image，支持 CJK 自动换行）。
library;

import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/painting.dart';

import '../core/constants.dart';

Future<Uint8List> textToPng(
  String text, {
  int fontSize = 24,
  int padding = 8,
}) async {
  final painter = TextPainter(
    text: TextSpan(
      text: text,
      style: TextStyle(
        color: const Color(0xFF000000),
        fontSize: fontSize.toDouble(),
      ),
    ),
    textDirection: TextDirection.ltr,
  )..layout(maxWidth: (lineDots - 2 * padding).toDouble());
  final height = (2 * padding + painter.height).ceil().clamp(1, 768000);
  final recorder = ui.PictureRecorder();
  final canvas = Canvas(recorder);
  canvas.drawRect(
    Rect.fromLTWH(0, 0, lineDots.toDouble(), height.toDouble()),
    Paint()..color = const Color(0xFFFFFFFF),
  );
  painter.paint(canvas, Offset(padding.toDouble(), padding.toDouble()));
  final image = await recorder.endRecording().toImage(lineDots, height);
  final data = await image.toByteData(format: ui.ImageByteFormat.png);
  return data!.buffer.asUint8List();
}

/// 任意图片字节 → PNG（统一交给渲染管线按 384 宽处理）。
Future<Uint8List> normalizeToPng(List<int> bytes) async {
  final codec = await ui.instantiateImageCodec(Uint8List.fromList(bytes));
  final frame = await codec.getNextFrame();
  final data = await frame.image.toByteData(format: ui.ImageByteFormat.png);
  return data!.buffer.asUint8List();
}
