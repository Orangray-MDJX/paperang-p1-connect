/// PDF 服务：系统 PdfRenderer 平台通道封装。
///
/// 打印管线：renderForPrint 每页按 384 点（57mm/203dpi）矢量渲染成 PNG
/// 交给队列；预览走 768px 宽懒加载。LAN IPP 的 application/pdf 也走同一
/// 渲染器（由 App 层注入到 core 的 IppService）。
library;

import 'package:flutter/services.dart';

import '../core/constants.dart' show lineDots;

class PdfException implements Exception {
  const PdfException(this.message);

  final String message;

  @override
  String toString() => 'PdfException: $message';
}

typedef PdfPageRenderer = Future<List<Uint8List>> Function(Uint8List pdf);

class PdfService {
  static const _pdf = MethodChannel('p1/pdf');
  static const _intent = MethodChannel('p1/intent');

  static int pageCount = 0;

  /// 打开缓存的 PDF（选择器返回的路径或网络字节），返回页数。
  static Future<int> openPath(String path) async {
    try {
      final info = await _pdf.invokeMapMethod<String, Object?>('openPath', {
        'path': path,
      });
      pageCount = (info?['pageCount'] as num?)?.toInt() ?? 0;
      return pageCount;
    } on PlatformException catch (e) {
      throw PdfException(e.message ?? '无法打开 PDF');
    }
  }

  /// 渲染单页为 PNG（width 为目标像素宽；打印用 384，预览用 768）。
  static Future<Uint8List> renderPage(int index, {int width = 768}) async {
    try {
      final out = await _pdf.invokeMethod<Uint8List>('renderPage', {
        'index': index,
        'width': width,
      });
      if (out == null) throw const PdfException('渲染返回空');
      return out;
    } on PlatformException catch (e) {
      throw PdfException(e.message ?? '渲染失败');
    }
  }

  static Future<void> close() async {
    try {
      await _pdf.invokeMethod('close');
    } on PlatformException {
      // 通道侧已关闭
    }
    pageCount = 0;
  }

  /// 系统文件选择器选一个 PDF，返回缓存路径（取消返回 null）。
  static Future<String?> pickPdf() async {
    try {
      return await _intent.invokeMethod<String>('pickPdf');
    } on PlatformException {
      return null;
    }
  }

  /// 保存 PNG 到系统下载目录，返回 content Uri（失败抛异常）。
  static Future<String> saveToDownloads(Uint8List png, String name) async {
    try {
      final uri = await _intent.invokeMethod<String>('saveImageToDownloads', {
        'data': png,
        'name': name,
      });
      if (uri == null) throw const PdfException('保存失败');
      return uri;
    } on PlatformException catch (e) {
      throw PdfException(e.message ?? '保存失败');
    }
  }

  /// 打印渲染器：整份 PDF → 384 点宽 PNG 页列表（供 IppService 注入）。
  static Future<List<Uint8List>> renderForPrint(Uint8List pdfBytes) async {
    // IppService 拿到的是字节，落盘后打开（PdfRenderer 需要文件描述符）。
    try {
      final info = await _pdf.invokeMapMethod<String, Object?>('open', {
        'data': pdfBytes,
      });
      final pages = (info?['pageCount'] as num?)?.toInt() ?? 0;
      if (pages == 0) throw const PdfException('PDF 没有页面');
      final out = <Uint8List>[];
      for (var i = 0; i < pages; i++) {
        out.add(await renderPage(i, width: lineDots));
      }
      await close();
      return out;
    } on PlatformException catch (e) {
      await close();
      throw PdfException(e.message ?? 'PDF 渲染失败');
    }
  }
}
