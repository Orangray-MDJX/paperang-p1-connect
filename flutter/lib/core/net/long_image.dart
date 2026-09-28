/// 长图打印入口（对齐桌面版 long_image.py 的凭证与限额语义）。
///
/// 预览只存 token 的 SHA-256；确认幂等（同 token 重复提交返回同一任务）；
/// 上限 40MB / 2000 万像素 / 16000 行（约 2 米）。
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;
import 'package:image/image.dart' as img;
import 'package:sqflite/sqflite.dart';

import '../config/config.dart';
import '../queue/job_queue.dart';
import '../render/render.dart';

const int maxBytes = 40 * 1024 * 1024;
const int maxPixels = 20000000;
const int maxRows = 16000;
const int previewTtlSeconds = 1800;

class LongImageException implements Exception {
  const LongImageException(this.status, this.message);

  final int status;
  final String message;
}

class LongImageService {
  LongImageService(this.db, this.cfg, this.jobs);

  final Database db;
  final AppConfig cfg;
  final JobQueue jobs;

  Future<void> ensureTable() async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS image_previews (
        token_hash TEXT PRIMARY KEY, created REAL NOT NULL, png BLOB, rows INTEGER NOT NULL, job_id INTEGER)
    ''');
  }

  Future<Map<String, Object>> preview(Uint8List bytes, bool trim) async {
    if (bytes.length > maxBytes) {
      throw const LongImageException(413, '图片超过 40MB');
    }
    final image = img.decodeImage(bytes);
    if (image == null) {
      throw const LongImageException(400, '仅支持 PNG/JPEG 图片');
    }
    if (image.width * image.height > maxPixels) {
      throw const LongImageException(413, '图片超过 2000 万像素');
    }
    var source = image;
    if (trim) {
      final cropped = _trimWhitespace(image);
      if (cropped != null) source = cropped;
    }
    final bitmap = prepare(
      source,
      dither: cfg.dither,
      threshold: cfg.threshold,
    );
    final rows = bitmap.height;
    if (rows > maxRows) {
      throw const LongImageException(413, '预计行数超过 16000 行（约 2 米）');
    }
    final png = img.encodePng(
      img.Image.fromBytes(
        width: bitmap.width,
        height: bitmap.height,
        bytes: bitmap.pixels.buffer,
        numChannels: 1,
      ),
    );
    final now = DateTime.now().millisecondsSinceEpoch / 1000.0;
    await db.execute('DELETE FROM image_previews WHERE created < ?', [
      now - previewTtlSeconds,
    ]);
    final count = Sqflite.firstIntValue(
      await db.rawQuery('SELECT count(*) FROM image_previews'),
    )!;
    if (count >= 8) {
      throw const LongImageException(503, '预览缓存已满，请稍后再试');
    }
    // token 只下发给客户端；库里仅存 SHA-256。
    final token = _randomToken();
    final tokenHash = _hash(token);
    await db.insert('image_previews', {
      'token_hash': tokenHash,
      'created': now,
      'png': png,
      'rows': rows,
      'job_id': null,
    });
    return {
      'token': token,
      'rows': rows,
      'length_mm': (rows * 25.4 / 203).toStringAsFixed(1),
      'expires_in': previewTtlSeconds,
    };
  }

  Future<Uint8List> previewPng(String token) async {
    final row = await _row(token, requirePending: true);
    final png = row['png'];
    if (png == null) {
      throw const LongImageException(410, '预览已提交或过期');
    }
    return png as Uint8List;
  }

  /// 幂等确认：同一 token 重复提交返回同一个任务 ID。
  Future<int> submit(String token) async {
    final row = await _row(token, requirePending: true);
    final existing = row['job_id'] as int?;
    if (existing != null) return existing;
    final png = row['png'] as Uint8List?;
    if (png == null) {
      throw const LongImageException(410, '预览已提交或过期');
    }
    final jid = await jobs.submit(
      PrintJob(
        title: '长图 ${row['rows']} 行',
        pages: [png],
        source: 'long-image',
      ),
    );
    await db.update(
      'image_previews',
      {'job_id': jid, 'png': null},
      where: 'token_hash=?',
      whereArgs: [row['token_hash']],
    );
    return jid;
  }

  Future<Map<String, Object>> job(String token) async {
    final row = await _row(token, requirePending: false);
    final jid = row['job_id'] as int?;
    if (jid == null) {
      throw const LongImageException(409, '预览尚未确认打印');
    }
    final job = await jobs.get(jid);
    return {'job_id': jid, 'state': job.state, 'pages_done': job.pagesDone};
  }

  Future<void> cancel(String token) async {
    final row = await _row(token, requirePending: false);
    final jid = row['job_id'] as int?;
    if (jid != null) await jobs.cancel(jid);
  }

  Future<Map<String, Object?>> _row(
    String token, {
    required bool requirePending,
  }) async {
    if (token.length < 32) {
      throw const LongImageException(404, '预览或任务不存在');
    }
    final rows = await db.query(
      'image_previews',
      where: 'token_hash=?',
      whereArgs: [_hash(token)],
      limit: 1,
    );
    if (rows.isEmpty) {
      throw const LongImageException(404, '预览或任务不存在');
    }
    final row = rows.first;
    if (requirePending) {
      final created = row['created'] as double;
      final age = DateTime.now().millisecondsSinceEpoch / 1000.0 - created;
      if (age > previewTtlSeconds) {
        throw const LongImageException(410, '预览已过期');
      }
    }
    return row;
  }

  static String _hash(String token) =>
      crypto.sha256.convert(utf8.encode(token)).toString();

  static String _randomToken() {
    final rand =
        DateTime.now().microsecondsSinceEpoch ^ DateTime.now().hashCode;
    final seed = '$rand${identityHashCode(LongImageService)}';
    return crypto.sha256
        .convert(utf8.encode(seed + rand.toString()))
        .toString()
        .substring(0, 43);
  }

  static img.Image? _trimWhitespace(img.Image source) {
    int left = source.width, top = source.height, right = -1, bottom = -1;
    for (final p in source) {
      final lum = (0.299 * p.r + 0.587 * p.g + 0.114 * p.b).round();
      final opaque = p.a >= 128;
      final dark = opaque && lum < 250;
      if (dark) {
        if (p.x < left) left = p.x;
        if (p.y < top) top = p.y;
        if (p.x > right) right = p.x;
        if (p.y > bottom) bottom = p.y;
      }
    }
    if (right < left || bottom < top) return null;
    return img.copyCrop(
      source,
      x: left,
      y: top,
      width: right - left + 1,
      height: bottom - top + 1,
    );
  }
}
