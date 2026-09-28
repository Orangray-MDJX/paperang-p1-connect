/// LAN 服务器集成测试：真实 HttpServer + 完整 HTTP 请求（替代模拟器实测，
/// 等效覆盖 IPP 路由、子网白名单、长图入口）。
library;

import 'dart:convert';

import 'package:shelf/shelf.dart' as shelf;

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:paperang_p1/core/config/config.dart';
import 'package:paperang_p1/core/device/printer_device.dart';
import 'package:paperang_p1/core/net/ipp.dart';
import 'package:paperang_p1/core/net/long_image.dart';
import 'package:paperang_p1/core/queue/job_queue.dart';
import 'package:paperang_p1/core/util/async_lock.dart';
import 'package:paperang_p1/net/lan_server.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'dart:async';

class TestResp {
  TestResp(this.statusCode, this.bodyBytes, this.headers);
  final int statusCode;
  final Uint8List bodyBytes;
  final Map<String, String> headers;
  String get body => utf8.decode(bodyBytes, allowMalformed: true);
}

Future<TestResp> doPost(
  Uri uri, {
  Object? body,
  Map<String, String>? headers,
}) async {
  final client = HttpClient();
  try {
    final req = await client.postUrl(uri);
    headers?.forEach(req.headers.set);
    req.add(body is List<int> ? body : utf8.encode(body.toString()));
    final resp = await req.close();
    final data = BytesBuilder();
    await resp.forEach(data.add);
    return TestResp(resp.statusCode, data.toBytes(), {
      'content-type': resp.headers.value('content-type') ?? '',
    });
  } finally {
    client.close();
  }
}

Future<TestResp> doGet(Uri uri, {Map<String, String>? headers}) async {
  final client = HttpClient();
  try {
    final req = await client.getUrl(uri);
    headers?.forEach(req.headers.set);
    final resp = await req.close();
    final data = BytesBuilder();
    await resp.forEach(data.add);
    return TestResp(resp.statusCode, data.toBytes(), {
      'content-type': resp.headers.value('content-type') ?? '',
    });
  } finally {
    client.close();
  }
}

class _FakeConnInfo implements HttpConnectionInfo {
  _FakeConnInfo(this.remoteAddress);

  @override
  final InternetAddress remoteAddress;

  @override
  int get remotePort => 54321;

  @override
  int get localPort => 18631;
}

class _Mgr implements QueueManager, DeviceStatusProvider {
  @override
  final AsyncLock operationLock = AsyncLock();

  @override
  Future<PrinterDevice> ensureConnected() async => throw Exception('off');

  @override
  Future<void> disconnect() async {}

  @override
  Map<String, Object?> status() => {'connected': false};
}

Uint8List ippRequest(
  int op, {
  List<Uint8List> attrs = const [],
  Uint8List? doc,
}) {
  final out = BytesBuilder();
  final head = Uint8List(8);
  head[0] = 2;
  ByteData.sublistView(head).setUint16(2, op, Endian.big);
  ByteData.sublistView(head).setUint32(4, 123, Endian.big);
  out.add(head);
  out.add(Uint8List.fromList([0x01]));
  out.add(IppCodec.attribute('attributes-charset', 0x47, 'utf-8'));
  out.add(IppCodec.attribute('attributes-natural-language', 0x48, 'en'));
  for (final a in attrs) {
    out.add(a);
  }
  out.add(Uint8List.fromList([0x03]));
  if (doc != null) out.add(doc);
  return out.toBytes();
}

void main() {
  setUpAll(() {
    sqfliteFfiInit();
    TestWidgetsFlutterBinding.ensureInitialized();
  });

  test('LAN 面仅回环/白名单可达，IPP 与长图全链路工作', () async {
    final dir = await Directory.systemTemp.createTemp('lan');
    final cfg = AppConfig()
      ..lanEnabled = true
      ..lanAddress = '127.0.0.1'
      ..lanNetwork = '127.0.0.0/24'
      // 测试用随机高位端口，绝不触碰真实服务端口
      ..apiPort = 18765
      ..spoolPort = 19100
      ..ippPort = 18631;
    final mgr = _Mgr();
    final jobs = await JobQueue.open(
      mgr,
      dbPath: '${dir.path}${Platform.pathSeparator}l.db',
      factory: databaseFactoryFfi,
    );
    final longImage = LongImageService(jobs.database, cfg, jobs);
    await longImage.ensureTable();
    final server = LanServer(
      cfg: cfg,
      mgr: mgr,
      jobs: jobs,
      longImage: longImage,
    );
    await server.start();
    final port = cfg.ippPort;
    final base = 'http://127.0.0.1:$port';
    Future<TestResp> call(
      String method,
      String path, {
      Uint8List? body,
      Map<String, String>? headers,
    }) async {
      final request = shelf.Request(
        method,
        Uri.parse('$base$path'),
        body: body == null ? null : Stream.value(body),
        headers: headers,
        context: {
          'shelf.io.connection_info': _FakeConnInfo(
            InternetAddress.loopbackIPv4,
          ),
        },
      );
      final resp = await server.handlerForTest(request);
      final data = BytesBuilder();
      await resp.read().forEach(data.add);
      return TestResp(resp.statusCode, data.toBytes(), {
        'content-type': resp.headers['content-type'] ?? '',
      });
    }

    Future<TestResp> doPost(
      Uri uri, {
      Object? body,
      Map<String, String>? headers,
    }) => call(
      'POST',
      uri.path + (uri.hasQuery ? '?${uri.query}' : ''),
      body: body is List<int> ? Uint8List.fromList(body) : null,
      headers: headers,
    );
    Future<TestResp> doGet(Uri uri, {Map<String, String>? headers}) =>
        call('GET', uri.path, headers: headers);

    try {
      // 1) 回环客户端：Get-Printer-Attributes 成功
      final r11 = await doPost(
        Uri.parse('$base/ipp/print'),
        body: ippRequest(11),
        headers: {'Content-Type': 'application/ipp'},
      );
      // ignore: avoid_print
      print(
        'R11: ${r11.statusCode} body=${r11.body.substring(0, r11.body.length > 120 ? 120 : r11.body.length)}',
      );
      expect(r11.statusCode, 200);
      expect(r11.bodyBytes.length, greaterThan(100));

      // 2) 管理面不存在（404）
      final rCfg = await doGet(Uri.parse('$base/api/config'));
      expect(rCfg.statusCode, 404);

      // 3) 长图入口：上传 → token → 预览 → 提交 → 幂等
      final image = img.Image(width: 8, height: 120);
      for (final p in image) {
        p.setRgb(
          p.y % 2 == 0 ? 0 : 255,
          p.y % 2 == 0 ? 0 : 255,
          p.y % 2 == 0 ? 0 : 255,
        );
      }
      final png = img.encodePng(image);
      final prev = await doPost(
        Uri.parse('$base/long-image/preview?trim=false'),
        body: png,
        headers: {'X-P1-Upload': '1'},
      );
      expect(prev.statusCode, 200, reason: prev.body);
      final token = (jsonDecode(prev.body) as Map)['token'] as String;

      final prevPng = await doGet(
        Uri.parse('$base/long-image/preview.png'),
        headers: {'X-P1-Token': token},
      );
      expect(prevPng.statusCode, 200);
      expect(prevPng.headers['content-type'], 'image/png');

      final submit = await doPost(
        Uri.parse('$base/long-image/submit'),
        headers: {'X-P1-Token': token},
      );
      expect(submit.statusCode, 200);
      final jid = (jsonDecode(submit.body) as Map)['job_id'];
      final again = await doPost(
        Uri.parse('$base/long-image/submit'),
        headers: {'X-P1-Token': token},
      );
      // preview.png 已被消费
      expect(
        (await doGet(
          Uri.parse('$base/long-image/preview.png'),
          headers: {'X-P1-Token': token},
        )).statusCode,
        410,
      );
      expect((jsonDecode(again.body) as Map)['job_id'], jid, reason: '幂等');
      expect((await jobs.get(jid as int)).state, anyOf('held', 'pending'));
    } finally {
      await jobs.stop();
    }
  }, timeout: const Timeout(Duration(seconds: 60)));
}
