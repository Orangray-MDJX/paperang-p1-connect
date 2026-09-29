/// IPP 服务流程测试（直译自 tests/test_ipp.py 的核心用例）。
library;

import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:paperang_p1/core/config/config.dart';
import 'package:paperang_p1/core/net/ipp.dart';
import 'package:paperang_p1/core/queue/job_queue.dart';
import 'package:paperang_p1/core/util/async_lock.dart';
import 'package:paperang_p1/core/device/printer_device.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'dart:io';

import 'package:image/image.dart' as img;

class _Manager implements QueueManager, DeviceStatusProvider {
  _Manager(this.statusValue);

  final Map<String, Object?> statusValue;

  @override
  final AsyncLock operationLock = AsyncLock();

  @override
  Future<PrinterDevice> ensureConnected() async => throw Exception('off');

  @override
  Future<void> disconnect() async {}

  @override
  Map<String, Object?> status() => statusValue;
}

Uint8List raster({
  int width = 16,
  int height = 2,
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
  field(400, 3);
  field(420, 1);
  return Uint8List.fromList([...'RaS2'.codeUnits, ...h, ...body]);
}

Uint8List request(
  int op, {
  List<Uint8List> extraAttrs = const [],
  Uint8List? doc,
}) {
  final out = BytesBuilder();
  final head = Uint8List(8);
  final hd = ByteData.sublistView(head);
  head[0] = 2;
  hd.setUint16(2, op, Endian.big);
  hd.setUint32(4, 123, Endian.big);
  out.add(head);
  out.add(Uint8List.fromList([0x01]));
  out.add(IppCodec.attribute('attributes-charset', 0x47, 'utf-8'));
  out.add(IppCodec.attribute('attributes-natural-language', 0x48, 'en'));
  for (final a in extraAttrs) {
    out.add(a);
  }
  out.add(Uint8List.fromList([0x03]));
  if (doc != null) out.add(doc);
  return out.toBytes();
}

void main() {
  setUpAll(() => sqfliteFfiInit());

  test('缺纸时 printer-state=stopped + media-empty', () async {
    final dir = await Directory.systemTemp.createTemp('ipp');
    final mgr = _Manager({
      'connected': true,
      'printable': false,
      'lidClosed': true,
      'paperPresent': false,
    });
    final jobs = await JobQueue.open(
      mgr,
      dbPath: '${dir.path}${Platform.pathSeparator}m.db',
      factory: databaseFactoryFfi,
    );
    final svc = IppService(AppConfig(), mgr, jobs);
    final resp = await svc.handle(request(11));
    final parsed = IppCodec.parse(resp);
    expect(parsed.attributes['printer-state'], [5]);
    expect(parsed.attributes['printer-state-reasons'], ['media-empty']);
    await jobs.stop();
  });

  test('Create/Send/Get/Cancel 全流程 + 0x0406/0x040a', () async {
    final dir = await Directory.systemTemp.createTemp('ipp');
    final mgr = _Manager({'connected': false});
    final jobs = await JobQueue.open(
      mgr,
      dbPath: '${dir.path}${Platform.pathSeparator}j.db',
      factory: databaseFactoryFfi,
    );
    final svc = IppService(AppConfig(), mgr, jobs);

    Future<IppRequest> send(
      int op, {
      List<Uint8List> attrs = const [],
      Uint8List? doc,
    }) async {
      final r = await svc.handle(request(op, extraAttrs: attrs, doc: doc));
      return IppCodec.parse(r);
    }

    final attrs11 = await send(11);
    expect(
      attrs11.attributes['document-format-supported']!.contains(
        'image/pwg-raster',
      ),
      isTrue,
    );

    final created = await send(
      5,
      attrs: [IppCodec.attribute('job-name', 0x42, 'native')],
    );
    final jid = created.attributes['job-id']![0] as int;
    final jobAttr = IppCodec.attribute('job-id', 0x21, jid);
    final sent = await send(
      6,
      attrs: [jobAttr, IppCodec.attribute('last-document', 0x22, true)],
      doc: raster(),
    );
    expect(sent.operation, 0);

    await Future<void>.delayed(const Duration(milliseconds: 40));
    final got = await send(9, attrs: [jobAttr]);
    expect(got.attributes['job-state'], [4]); // held（无硬件）

    final cancelled = await send(8, attrs: [jobAttr]);
    expect(cancelled.attributes['job-state'], [7]);

    final notFound = await send(
      9,
      attrs: [IppCodec.attribute('job-id', 0x21, 999)],
    );
    expect(notFound.operation, 0x406);

    final badFormat = await send(
      2,
      attrs: [IppCodec.attribute('document-format', 0x49, 'application/evil')],
      doc: Uint8List.fromList([1, 2]),
    );
    expect(badFormat.operation, 0x40a);
    await jobs.stop();
  });

  test('注入 PDF 渲染器后 application/pdf 受理并建任务', () async {
    final dir = await Directory.systemTemp.createTemp('ippdf');
    final mgr = _Manager({'connected': false});
    final jobs = await JobQueue.open(
      mgr,
      dbPath: '${dir.path}${Platform.pathSeparator}p.db',
      factory: databaseFactoryFfi,
    );
    final tinyPng = Uint8List.fromList(
      img.encodePng(img.Image(width: 2, height: 2)),
    );
    final svc = IppService(
      AppConfig(),
      mgr,
      jobs,
      pdfRenderer: (pdf) async => [tinyPng],
    );
    expect(svc.supportedFormats.contains('application/pdf'), isTrue);

    // 无注入的实例仍拒绝 PDF（0x040a）
    final bare = IppService(AppConfig(), mgr, jobs);
    expect(bare.supportedFormats.contains('application/pdf'), isFalse);

    final out = BytesBuilder();
    final head = Uint8List(8);
    head[0] = 2;
    ByteData.sublistView(head).setUint16(2, 2, Endian.big);
    ByteData.sublistView(head).setUint32(4, 123, Endian.big);
    out.add(head);
    out.add(Uint8List.fromList([0x01]));
    out.add(IppCodec.attribute('attributes-charset', 0x47, 'utf-8'));
    out.add(IppCodec.attribute('attributes-natural-language', 0x48, 'en'));
    out.add(IppCodec.attribute('document-format', 0x49, 'application/pdf'));
    out.add(Uint8List.fromList([0x03]));
    out.add(Uint8List.fromList([0x25, 0x50, 0x44, 0x46])); // %PDF
    final resp = await svc.handle(out.toBytes());
    expect(IppCodec.parse(resp).operation, 0);
    final list = await jobs.list(limit: 1);
    expect(list.first.pageCount, 1);
    await jobs.stop();
  });

  test('print-quality 3/4/5 → 0.625/1/1.25 系数', () {
    expect(qualityDensity(3, 80), 50);
    expect(qualityDensity(4, 80), 80);
    expect(qualityDensity(5, 80), 100);
    expect(qualityDensity(5, 60), 75);
  });
}
