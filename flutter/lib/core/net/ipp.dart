/// IPP 编解码与打印服务逻辑（对齐桌面版 ipp.py）。
///
/// 支持 Print-Job/Validate-Job/Create-Job/Send-Document/Cancel-Job/
/// Get-Job-Attributes/Get-Jobs/Get-Printer-Attributes；文档格式
/// image/pwg-raster、image/urf、image/jpeg。Android 版暂不支持 PDF
/// （无 Ghostscript，系统渲染器留待后续版本）。
library;

import 'dart:typed_data';
import 'dart:convert';

import '../config/config.dart';
import '../queue/job_queue.dart';
import '../render/render.dart';
import 'pwg_raster.dart';
import 'urf_raster.dart';

import 'package:image/image.dart' as img;

/// 带 IPP 状态码的业务异常（0x0406 job 不存在 / 0x040a 格式不支持等）。
class IppError implements Exception {
  const IppError(this.status, this.message);

  final int status;
  final String message;
}

class IppRequest {
  IppRequest({
    required this.major,
    required this.operation,
    required this.requestId,
    required this.attributes,
    required this.document,
  });

  final int major;
  final int operation;
  final int requestId;

  /// 属性组（operation-attributes tag 0x01 + job-attributes 0x02）：
  /// name → 值列表（int/String/bool/Map）。
  final Map<String, List<Object>> attributes;
  final Uint8List document;
}

class IppCodec {
  static const int maxAttributeBytes = 128 * 1024;

  /// 解析 IPP 请求（collection 嵌套深度 ≤8）。
  static IppRequest parse(Uint8List data) {
    if (data.length < 8) {
      throw const FormatException('IPP 请求过短');
    }
    final bd = ByteData.sublistView(data);
    final major = data[0];
    final operation = bd.getUint16(2, Endian.big);
    final requestId = bd.getUint32(4, Endian.big);
    var pos = 8;
    final attrs = <String, List<Object>>{};
    var attrBytes = 0;
    while (pos < data.length) {
      final tag = data[pos];
      if (tag == 0x03) {
        pos += 1;
        break; // end-of-attributes
      }
      if (tag == 0x01 || tag == 0x02) {
        pos += 1;
        continue; // 属性组分隔
      }
      attrBytes += 1;
      if (attrBytes > maxAttributeBytes) {
        throw const FormatException('IPP 属性区过大');
      }
      final nameLen = bd.getUint16(pos + 1, Endian.big);
      final name = utf8.decode(data.sublist(pos + 3, pos + 3 + nameLen));
      pos += 3 + nameLen;
      final value = _readValue(bd, data, tag, pos, 0);
      pos = value.next;
      (attrs[name] ??= []).add(value.value);
    }
    return IppRequest(
      major: major,
      operation: operation,
      requestId: requestId,
      attributes: attrs,
      document: Uint8List.sublistView(data, pos),
    );
  }

  static _ValueRead _readValue(
    ByteData bd,
    Uint8List data,
    int tag,
    int pos,
    int depth,
  ) {
    if (tag == 0x34) {
      // begCollection：读取成员直到 endCollection
      final members = <String, Object>{};
      var p = pos;
      if (depth >= 8) {
        throw const FormatException('IPP collection 嵌套过深');
      }
      while (true) {
        final memberTag = data[p];
        if (memberTag == 0x37) {
          final len = bd.getUint16(p + 1, Endian.big);
          p += 3 + len;
          break;
        }
        // memberAttrName (0x4a) 后跟成员值
        final nameLen = bd.getUint16(p + 1, Endian.big);
        final name = utf8.decode(data.sublist(p + 3, p + 3 + nameLen));
        p += 3 + nameLen;
        final inner = _readValue(bd, data, memberTag, p, depth + 1);
        p = inner.next;
        members[name] = inner.value;
      }
      return _ValueRead(Map<String, Object>.from(members), p);
    }
    final len = bd.getUint16(pos, Endian.big);
    final raw = Uint8List.sublistView(data, pos + 2, pos + 2 + len);
    final next = pos + 2 + len;
    final Object value;
    switch (tag) {
      case 0x21: // integer
      case 0x23: // enum
        value = ByteData.sublistView(raw).getUint32(0, Endian.big);
      case 0x22: // boolean
        value = raw.isNotEmpty && raw[0] != 0;
      case 0x44: // keyword/uri 大多按 string
      default:
        value = utf8.decode(raw);
    }
    return _ValueRead(value, next);
  }

  static Uint8List _value(int tag, Object v) {
    if (v is int) {
      final out = Uint8List(4);
      ByteData.sublistView(out).setUint32(0, v, Endian.big);
      return out;
    }
    if (v is bool) {
      return Uint8List.fromList([v ? 1 : 0]);
    }
    if (v is String) {
      return Uint8List.fromList(utf8.encode(v));
    }
    throw ArgumentError('unsupported IPP value: ${v.runtimeType}');
  }

  /// 编码一个属性（单值）。
  static Uint8List attribute(String name, int tag, Object v) {
    final n = utf8.encode(name);
    final value = _value(tag, v);
    final out = BytesBuilder();
    out.add(Uint8List.fromList([tag, n.length >> 8, n.length & 0xFF]));
    out.add(Uint8List.fromList(n));
    out.add(Uint8List.fromList([value.length >> 8, value.length & 0xFF]));
    out.add(value);
    return out.toBytes();
  }

  /// 编码响应：0x01 组 + groups(map name→(tag,values)) + 0x03。
  static Uint8List response(
    int major,
    int requestId,
    int status,
    Map<String, List<Object>> groups, [
    String message = '',
  ]) {
    final out = BytesBuilder();
    final head = Uint8List(8);
    final hd = ByteData.sublistView(head);
    head[0] = major;
    head[1] = 0;
    hd.setUint16(2, status, Endian.big);
    hd.setUint32(4, requestId, Endian.big);
    out.add(head);
    out.add(Uint8List.fromList([0x01]));
    out.add(attribute('attributes-charset', 0x47, 'utf-8'));
    out.add(attribute('attributes-natural-language', 0x48, 'en'));
    for (final e in groups.entries) {
      for (final v in e.value) {
        out.add(attribute(e.key, _tagFor(e.key, v), v));
      }
    }
    if (message.isNotEmpty) {
      out.add(attribute('status-message', 0x41, message));
    }
    out.add(Uint8List.fromList([0x03]));
    return out.toBytes();
  }

  static int _tagFor(String name, Object v) {
    if (v is int) {
      return name == 'print-quality' ? 0x23 : 0x21;
    }
    if (v is bool) return 0x22;
    if (name == 'job-id' || name == 'job-state') return 0x21;
    if (name == 'attributes-charset') return 0x47;
    if (name == 'attributes-natural-language') return 0x48;
    return switch (name) {
      'printer-uri' || 'job-uri' || 'job-printer-uri' => 0x45,
      'job-name' || 'printer-name' || 'requesting-user-name' => 0x42,
      'which-jobs' || 'printer-state-reasons' => 0x44,
      _ => 0x42,
    };
  }
}

class _ValueRead {
  _ValueRead(this.value, this.next);

  final Object value;
  final int next;
}

/// 媒体尺寸（1/100 英寸，与桌面一致）。
class MediaSize {
  const MediaSize(this.name, this.width, this.height);

  final String name;
  final int width;
  final int height;
}

const List<MediaSize> baseMedia = [
  MediaSize('custom_57x100mm_203dpi', 5700, 10000),
  MediaSize('na_index-4x6_203dpi', 14400, 21600),
  MediaSize('iso_a4_203dpi', 21000, 29700),
];

/// print-quality(3/4/5) → 浓度系数（3 草稿 0.625 / 4 正常 1 / 5 高 1.25）。
int qualityDensity(int quality, int base) {
  switch (quality) {
    case 3:
      return (base * 0.625).round();
    case 5:
      return (base * 1.25).round().clamp(0, 100);
    default:
      return base;
  }
}

/// 卷纸不吃整页：裁掉尾部空白（内容底 +8 行，空页保 16 行）。
MonochromeBitmap trimTrailingBlank(MonochromeBitmap page) {
  var lastDark = -1;
  for (var y = page.height - 1; y >= 0 && lastDark < 0; y--) {
    for (var x = 0; x < page.width; x++) {
      if (page.pixels[y * page.width + x] != 255) {
        lastDark = y;
        break;
      }
    }
  }
  final newHeight = lastDark < 0 ? 16 : (lastDark + 9).clamp(16, page.height);
  if (newHeight >= page.height) return page;
  return MonochromeBitmap(
    page.width,
    newHeight,
    Uint8List.sublistView(page.pixels, 0, page.width * newHeight),
  );
}

/// PDF 渲染器由 App 层注入（core 保持平台无关）；null 表示本实例不支持 PDF。
typedef PdfPrintRenderer = Future<List<Uint8List>> Function(Uint8List pdf);

class IppService {
  IppService(this.cfg, this.mgr, this.jobs, {this.pdfRenderer});

  final AppConfig cfg;
  final DeviceStatusProvider mgr;
  final JobQueue jobs;
  final PdfPrintRenderer? pdfRenderer;

  static const rasterFormats = ['image/pwg-raster', 'image/urf', 'image/jpeg'];

  List<String> get supportedFormats => [
    ...rasterFormats,
    if (pdfRenderer != null) 'application/pdf',
  ];

  Future<Uint8List> handle(Uint8List body, {String? jobUriBase}) async {
    final IppRequest req;
    try {
      req = IppCodec.parse(body);
    } catch (_) {
      return IppCodec.response(2, 0, 0x0400, const {}, '无法解析 IPP 请求');
    }
    try {
      return await _dispatch(req, jobUriBase ?? 'ipp://127.0.0.1:8631');
    } on IppError catch (e) {
      return IppCodec.response(
        req.major,
        req.requestId,
        e.status,
        const {},
        e.message,
      );
    } on FormatException catch (e) {
      return IppCodec.response(
        req.major,
        req.requestId,
        0x0400,
        const {},
        e.message,
      );
    } on Exception catch (e) {
      if (e.toString().contains('not found')) {
        return IppCodec.response(
          req.major,
          req.requestId,
          0x0406,
          const {},
          'client-error-not-found',
        );
      }
      return IppCodec.response(
        req.major,
        req.requestId,
        0x0500,
        const {},
        'internal-error',
      );
    }
  }

  Future<Uint8List> _dispatch(IppRequest req, String jobUriBase) async {
    final status = mgr.status();
    switch (req.operation) {
      case 11:
        return _printerAttributes(req, status);
      case 4:
        _validateDocument(req);
        return IppCodec.response(req.major, req.requestId, 0, const {});
      case 5:
        final jid = await jobs.submit(
          PrintJob(
            title: _str(req, 'job-name') ?? 'ipp',
            pages: const [],
            source: 'ipp',
          ),
          held: true,
        );
        return IppCodec.response(req.major, req.requestId, 0, {
          'job-id': [jid],
          'job-state': [4],
        });
      case 2:
      case 6:
        return await _printOrSend(req, jobUriBase);
      case 8:
        final jid = _int(req, 'job-id');
        await jobs.cancel(jid);
        return IppCodec.response(req.major, req.requestId, 0, {
          'job-state': [7],
        });
      case 9:
        final jid = _int(req, 'job-id');
        final job = await jobs.get(jid);
        return IppCodec.response(
          req.major,
          req.requestId,
          0,
          _jobAttrs(job, jobUriBase),
        );
      case 10:
        final list = await jobs.list(limit: 50);
        final groups = <String, List<Object>>{};
        for (final job in list) {
          for (final e in _jobAttrs(job, jobUriBase).entries) {
            groups[e.key] = [...(groups[e.key] ?? []), ...e.value];
          }
        }
        return IppCodec.response(req.major, req.requestId, 0, groups);
      default:
        return IppCodec.response(
          req.major,
          req.requestId,
          0x0403,
          const {},
          'server-error-operation-not-supported',
        );
    }
  }

  Map<String, List<Object>> _jobAttrs(JobRow job, String jobUriBase) => {
    'job-id': [job.id],
    'job-uri': ['$jobUriBase/jobs/${job.id}'],
    'job-state': [_jobState(job.state)],
    'job-state-reasons': [_jobReason(job.state)],
    'job-name': [job.title],
  };

  static int _jobState(String s) => switch (s) {
    'receiving' || 'pending' || 'held' => 4,
    'printing' => 5,
    'cancelled' => 7,
    'failed' || 'unknown' => 8,
    _ => 9,
  };

  static String _jobReason(String s) => switch (s) {
    'receiving' => 'job-incoming',
    'pending' => 'none',
    'held' => 'job-hold-until-specified',
    'printing' => 'job-printing',
    'cancelled' => 'job-canceled-by-user',
    'failed' || 'unknown' => 'aborted-by-system',
    _ => 'job-completed-successfully',
  };

  Future<Uint8List> _printOrSend(IppRequest req, String jobUriBase) async {
    _validateDocument(req);
    final quality = _intOrNull(req, 'print-quality');
    final density = quality == null
        ? null
        : qualityDensity(quality, cfg.density);
    final pages = await _renderDocument(req.document, _format(req));
    if (req.operation == 6) {
      final jid = _int(req, 'job-id');
      await jobs.attachPages(jid, pages);
      return IppCodec.response(
        req.major,
        req.requestId,
        0,
        _jobAttrs(await jobs.get(jid), jobUriBase),
      );
    }
    final jid = await jobs.submit(
      PrintJob(
        title: _str(req, 'job-name') ?? 'ipp',
        pages: pages,
        density: density,
        source: 'ipp',
      ),
    );
    return IppCodec.response(
      req.major,
      req.requestId,
      0,
      _jobAttrs(await jobs.get(jid), jobUriBase),
    );
  }

  String _format(IppRequest req) =>
      _str(req, 'document-format') ?? _sniff(req.document);

  /// 未声明格式时按 magic 嗅探（客户端常省略 document-format）。
  static String _sniff(Uint8List doc) {
    if (doc.length >= 4 &&
        doc[0] == 0x52 &&
        doc[1] == 0x61 &&
        doc[2] == 0x53 &&
        doc[3] == 0x32) {
      return 'image/pwg-raster';
    }
    if (doc.length >= 8 &&
        String.fromCharCodes(doc.sublist(0, 8)) == 'UNIRAST ') {
      return 'image/urf';
    }
    if (doc.length >= 2 && doc[0] == 0xFF && doc[1] == 0xD8) {
      return 'image/jpeg';
    }
    return 'application/octet-stream';
  }

  void _validateDocument(IppRequest req) {
    final format = _format(req);
    if (!supportedFormats.contains(format)) {
      throw const IppError(0x040a, 'document-format-error');
    }
  }

  Future<List<Uint8List>> _renderDocument(
    Uint8List document,
    String format,
  ) async {
    if (format == 'application/pdf') {
      if (pdfRenderer == null) {
        throw const IppError(0x040a, 'document-format-error');
      }
      // PDF 页已是 PNG（App 层按 384 点渲染），原样交给队列。
      return pdfRenderer!(document);
    }
    List<MonochromeBitmap> pages;
    if (format == 'image/pwg-raster') {
      pages = pwgDecode(document);
    } else if (format == 'image/urf') {
      pages = urfDecode(document);
    } else {
      pages = [
        prepare(
          loadImage(document),
          dither: cfg.dither,
          threshold: cfg.threshold,
        ),
      ];
    }
    if (pages.isEmpty) {
      throw const FormatException('empty-document');
    }
    return [
      for (final page in pages)
        img.encodePng(
          img.Image.fromBytes(
            width: page.width,
            height: page.height,
            bytes: page.pixels.buffer,
            numChannels: 1,
          ),
        ),
    ];
  }

  Uint8List _printerAttributes(IppRequest req, Map<String, Object?> status) {
    final stopped = status['connected'] == true && status['printable'] == false;
    final printerState = stopped ? 5 : (status['connected'] == true ? 3 : 4);
    final reasons = stopped
        ? [(status['lidClosed'] == false ? 'cover-open' : 'media-empty')]
        : (status['connected'] == true
              ? <Object>['none']
              : <Object>['connecting-to-device']);
    final media = [...baseMedia, if (cfg.ippLongMedia) ..._longMedia];
    return IppCodec.response(req.major, req.requestId, 0, {
      'printer-state': [printerState],
      'printer-state-reasons': reasons,
      'printer-name': [cfg.lanName],
      'printer-up': [true],
      'printer-is-accepting-jobs': [true],
      'queued-job-count': [jobs.stats.pending],
      'pdl-override-supported': ['attempted'],
      'copies-supported': [1],
      'sides-supported': ['one-sided'],
      'document-format-supported': supportedFormats,
      'print-quality-supported': [3, 4, 5],
      'media-default': ['custom_57x100mm_203dpi'],
      'media-supported': [for (final m in media) m.name],
      'media-source-supported': ['auto'],
      'printer-resolution-supported': [203, 300],
      'printer-resolution-default': [203],
      'urf-supported': ['W8,RS300,DM1,IS1,V1.4'],
      'color-supported': [false],
      'duplex-supported': [false],
      'printer-device-id': ['MFG:Paperang;MDL:P1;'],
      'printer-more-info': [
        'https://github.com/Orangray-MDJX/paperang-p1-connect',
      ],
    });
  }

  static const _longMedia = [
    MediaSize('custom_57x200mm_203dpi', 5700, 20000),
    MediaSize('custom_57x300mm_203dpi', 5700, 30000),
    MediaSize('custom_57x500mm_203dpi', 5700, 50000),
  ];

  static String? _str(IppRequest req, String name) {
    final v = req.attributes[name];
    return v == null || v.isEmpty ? null : v.first as String?;
  }

  static int? _intOrNull(IppRequest req, String name) {
    final v = req.attributes[name];
    return v == null || v.isEmpty ? null : v.first as int?;
  }

  static int _int(IppRequest req, String name) {
    final v = _intOrNull(req, name);
    if (v == null) {
      throw const FormatException('client-error-bad-request');
    }
    return v;
  }
}

/// 状态提供者（DeviceManager.status 的形状）。
abstract class DeviceStatusProvider {
  Map<String, Object?> status();
}
