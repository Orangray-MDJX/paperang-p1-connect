/// 局域网打印服务（shelf）：IPP 端点 + 长图入口 + 静态页。
/// 管理面仅回环；LAN 入口按配置子网白名单（对齐桌面版 restrict_network）。
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/services.dart' show rootBundle;
import 'package:meta/meta.dart';
import 'package:shelf/shelf.dart' as shelf;
import 'package:shelf/shelf_io.dart' as shelf_io;

import '../core/config/config.dart';
import '../core/net/ipp.dart';
import '../core/net/long_image.dart';
import '../core/queue/job_queue.dart';

class LanServer {
  LanServer({
    required this.cfg,
    required this.mgr,
    required this.jobs,
    required this.longImage,
    this.jobUriHost,
    this.pdfRenderer,
  });

  final AppConfig cfg;
  final DeviceStatusProvider mgr;
  final JobQueue jobs;
  final LongImageService longImage;
  final String? jobUriHost;
  final PdfPrintRenderer? pdfRenderer;

  HttpServer? _server;

  shelf.Handler get _pipeline => const shelf.Pipeline()
      .addMiddleware(_restrictNetwork)
      .addHandler(_router);

  /// 仅供测试：直接以 shelf Request 调用完整管线。
  @visibleForTesting
  Future<shelf.Response> handlerForTest(shelf.Request request) async =>
      await _pipeline(request);

  Future<void> start() async {
    if (_server != null) return;
    _server = await shelf_io.serve(
      _pipeline,
      InternetAddress.anyIPv4,
      cfg.ippPort,
    );
  }

  Future<void> stop() async {
    await _server?.close(force: true);
    _server = null;
  }

  bool get isRunning => _server != null;

  Future<shelf.Response> _router(shelf.Request req) async {
    try {
      return await _route(req);
    } on LongImageException catch (e) {
      return shelf.Response(e.status, body: e.message);
    }
  }

  Future<shelf.Response> _route(shelf.Request req) async {
    final path = req.url.path;
    if (path == 'ipp/print' && req.method == 'POST') {
      return _ipp(req);
    }
    if (path.startsWith('ipp/print/jobs/') && req.method == 'POST') {
      return _ipp(req);
    }
    if (path == 'long-image' && req.method == 'GET') {
      return _asset('assets/web/long-image.html', 'text/html; charset=utf-8');
    }
    if (path == 'test-page' && req.method == 'GET') {
      return _asset('assets/web/test-page.html', 'text/html; charset=utf-8');
    }
    if (path == 'long-image/preview' && req.method == 'POST') {
      _requireUpload(req);
      final trim = req.url.queryParameters['trim'] == 'true';
      final body = await _readBody(req, maxBytes);
      final result = await longImage.preview(body, trim);
      return _json(result);
    }
    if (path == 'long-image/preview.png' && req.method == 'GET') {
      return shelf.Response.ok(
        await longImage.previewPng(_token(req)),
        headers: {'Content-Type': 'image/png'},
      );
    }
    if (path == 'long-image/submit' && req.method == 'POST') {
      return _json({'job_id': await longImage.submit(_token(req))});
    }
    if (path == 'long-image/job' && req.method == 'GET') {
      return _json(await longImage.job(_token(req)));
    }
    if (path == 'long-image/cancel' && req.method == 'POST') {
      await longImage.cancel(_token(req));
      return _json({'ok': true});
    }
    return shelf.Response.notFound('not found');
  }

  Future<shelf.Response> _ipp(shelf.Request req) async {
    final body = await _readBody(req, 40 * 1024 * 1024);
    final out = await IppService(cfg, mgr, jobs, pdfRenderer: pdfRenderer)
        .handle(
          body,
          jobUriBase: 'ipp://${jobUriHost ?? '127.0.0.1'}:${cfg.ippPort}',
        );
    return shelf.Response.ok(out, headers: {'Content-Type': 'application/ipp'});
  }

  /// LAN 上只暴露 IPP 与长图；回环放行，其余按子网白名单。
  shelf.Middleware get _restrictNetwork =>
      (inner) => (req) async {
        final info = req.context['shelf.io.connection_info'];
        var ip = '';
        if (info is HttpConnectionInfo) {
          ip = info.remoteAddress.address;
        }
        final loopback = ip == '127.0.0.1' || ip == '::1';
        if (loopback) return inner(req);
        if (!cfg.lanEnabled || cfg.lanNetwork.isEmpty) {
          return shelf.Response(403, body: 'forbidden');
        }
        if (!_ipInNetwork(ip, cfg.lanNetwork)) {
          return shelf.Response(403, body: 'forbidden');
        }
        return inner(req);
      };

  static bool _ipInNetwork(String ip, String cidr) {
    final parts = cidr.split('/');
    if (parts.length != 2) return false;
    final prefix = int.tryParse(parts[1]);
    final netAddr = InternetAddress.tryParse(parts[0]);
    final ipAddr = InternetAddress.tryParse(ip);
    if (prefix == null || netAddr == null || ipAddr == null) return false;
    if (netAddr.type != ipAddr.type) return false;
    final a = netAddr.rawAddress, b = ipAddr.rawAddress;
    var remaining = prefix;
    for (var i = 0; i < a.length && remaining > 0; i++) {
      final bits = remaining >= 8 ? 8 : remaining;
      final mask = (0xFF << (8 - bits)) & 0xFF;
      if ((a[i] & mask) != (b[i] & mask)) return false;
      remaining -= 8;
    }
    return true;
  }

  void _requireUpload(shelf.Request req) {
    if (req.headers['x-p1-upload'] != '1') {
      throw const LongImageException(403, '缺少 X-P1-Upload 头');
    }
  }

  String _token(shelf.Request req) => req.headers['x-p1-token'] ?? '';

  Future<Uint8List> _readBody(shelf.Request req, int limit) async {
    final data = BytesBuilder(copy: false);
    await for (final chunk in req.read()) {
      data.add(chunk);
      if (data.length > limit) {
        throw const LongImageException(413, '上传超过大小限制');
      }
    }
    return data.toBytes();
  }

  Future<shelf.Response> _asset(String key, String contentType) async {
    try {
      final data = await rootBundle.load(key);
      return shelf.Response.ok(
        data.buffer.asUint8List(),
        headers: {'Content-Type': contentType},
      );
    } catch (_) {
      return shelf.Response.notFound('asset missing');
    }
  }

  shelf.Response _json(Object data) => shelf.Response.ok(
    jsonEncode(data),
    headers: {'Content-Type': 'application/json'},
  );
}
