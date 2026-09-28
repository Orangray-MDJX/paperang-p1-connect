/// A5 设备会话（P1 01.03.18 契约，直译自 device_a5.py）。
///
/// 关键语义：命令必须串行；任一命令超时/IO 失败即"毒化"会话——关闭连接、
/// 置 fault，禁止原地重试（迟到响应无法与新请求区分）。打印
/// start→位图→finish 之间绝不插入状态查询（P1 会拒绝位图帧）。
library;

import 'dart:async';

import 'package:meta/meta.dart';

import 'dart:typed_data';

import '../config/config.dart';
import '../errors.dart';
import '../hex.dart';
import '../protocol/a5.dart';
import '../render/render.dart';
import '../transport/transport.dart';
import '../util/async_lock.dart';
import 'printer_device.dart';

enum A5State { disconnected, connecting, initializing, ready, fault }

/// USB 通道连接后、首个查询前的前导字节。
final Uint8List usbPreamble = hexDecode('badcfe00c00300000a00');

class A5Device implements PrinterDevice {
  A5Device(this.transport, this.cfg) {
    transport.onBytes = _onBytes;
    transport.onDisconnected = _disconnected;
  }

  @override
  String get protocol => 'a5';

  final Transport transport;
  final AppConfig cfg;
  final A5Parser parser = A5Parser();
  final AsyncLock _commandLock = AsyncLock();

  A5State state = A5State.disconnected;
  double? battery;
  String? sn;
  int? powerDownTime;
  DateTime? connectedAt;
  String? version;
  String? lastError;
  int maxLength = 1024;
  bool mediaSupported = false;
  bool? lidClosed;
  bool? paperPresent;
  DateTime? mediaCheckedAt;

  Completer<A5Frame>? _pending;
  int _pendingCmd = 0;

  /// 仅供测试：暴露在途等待者。
  @visibleForTesting
  Completer<A5Frame>? get pendingForTest => _pending;

  void _onBytes(Uint8List data) {
    for (final frame in parser.feed(data)) {
      final p = _pending;
      if (p != null &&
          !p.isCompleted &&
          frame.messageType == 2 &&
          frame.command == _pendingCmd) {
        p.complete(frame);
      }
    }
  }

  void _disconnected() {
    state = A5State.fault;
    lastError = transport.lastError ?? 'A5 连接已断开';
    final p = _pending;
    if (p != null && !p.isCompleted) {
      p.completeError(DeviceError('A5 连接已断开'));
    }
  }

  /// 显式中止在途命令（对应 Python 任务取消语义：关会话防迟到响应）。
  void abortPending() {
    final p = _pending;
    if (p != null && !p.isCompleted) {
      p.completeError(DeviceError('命令已被中止'));
    }
    _disconnected();
  }

  Future<void> connect() async {
    state = A5State.connecting;
    lastError = null;
    try {
      await transport.open();
      state = A5State.initializing;
      if (transport.name == 'usb') {
        await transport.write(usbPreamble);
        await Future<void>.delayed(const Duration(milliseconds: 250));
      }
      version = await _queryText(0x0115);
      sn = await _queryText(0x0102);
      final maxRaw = await query(0x0114);
      maxLength = ByteData.sublistView(maxRaw).getUint16(0, Endian.little);
      if ((version ?? '').isEmpty || (sn ?? '').isEmpty || maxLength < 62) {
        throw DeviceError('A5 设备身份/包长无效');
      }
      // 本契约仅在实测的 P1 固件上成立，不代表所有 A5 机型。
      mediaSupported = sn!.startsWith('P1') && version == '01.03.18';
      if (mediaSupported) {
        final rawDpi = await query(0x0504);
        final widths = parseTlv(await query(0x0502));
        if (rawDpi.length != 2 || (widths[1]?.length ?? 0) != 2) {
          throw DeviceError('A5 打印规格返回格式无效');
        }
        final dpi = ByteData.sublistView(rawDpi).getUint16(0, Endian.little);
        final widthMm = ByteData.sublistView(widths[1]!)
            .getUint16(0, Endian.little);
        if (dpi < 50 || dpi > 1200 || widthMm < 20 || widthMm > 300) {
          throw DeviceError('A5 打印规格超出有效范围');
        }
        await getMediaStatus();
      }
      state = A5State.ready;
      connectedAt = DateTime.now();
    } catch (_) {
      state = A5State.fault;
      await transport.close();
      rethrow;
    }
  }

  Future<void> close() async {
    _disconnected();
    await transport.close();
    state = A5State.disconnected;
  }

  Future<A5Frame> command(
    int cmd, {
    Uint8List? content,
    Duration timeout = const Duration(seconds: 5),
  }) {
    return _commandLock.synchronize(() async {
      if (state == A5State.fault || state == A5State.disconnected) {
        throw DeviceError('A5 会话不可用，请重新连接');
      }
      final fut = _pending = Completer<A5Frame>();
      _pendingCmd = cmd;
      try {
        await transport.write(a5Build(cmd, content));
        return await fut.future.timeout(timeout);
      } catch (e) {
        // 超时/断连都会毒化会话：迟到响应不能当作新请求的应答。
        state = A5State.fault;
        await transport.close();
        if (e is DeviceError) rethrow;
        throw DeviceError(
          'A5 0x${cmd.toRadixString(16).toUpperCase()} 应答失败；'
          '会话已关闭，不能盲目重试: $e',
        );
      } finally {
        _pending = null;
        if (!fut.isCompleted) {
          fut.completeError(DeviceError('命令已结束'));
        }
      }
    });
  }

  Future<Uint8List> query(int cmd) async {
    final f = await command(cmd);
    final values = parseTlv(f.content);
    if (!values.containsKey(1)) {
      throw DeviceError('A5 0x${cmd.toRadixString(16).toUpperCase()} 缺少返回值');
    }
    return values[1]!;
  }

  Future<String> _queryText(int cmd) async =>
      String.fromCharCodes(await query(cmd)).replaceAll('\x00', '');

  Future<void> ack(
    int cmd, {
    Uint8List? content,
    Duration timeout = const Duration(seconds: 5),
  }) async {
    final result = await queryContent(cmd, content: content, timeout: timeout);
    if (!(result.isEmpty || (result.length == 1 && result[0] == 0))) {
      throw DeviceError(
        'A5 0x${cmd.toRadixString(16).toUpperCase()} 返回错误: ${hexEncode(result)}',
      );
    }
  }

  Future<Uint8List> queryContent(
    int cmd, {
    Uint8List? content,
    Duration timeout = const Duration(seconds: 5),
  }) async {
    final f = await command(cmd, content: content, timeout: timeout);
    final values = parseTlv(f.content);
    if (!values.containsKey(1)) {
      throw DeviceError(
        'A5 0x${cmd.toRadixString(16).toUpperCase()} 缺少 ACK 字段',
      );
    }
    return values[1]!;
  }

  @override
  Future<double> getBattery() async {
    final raw = await query(0x010b);
    final value = ByteData.sublistView(raw).getUint16(0, Endian.little) / 10;
    if (value < 0 || value > 100) {
      throw DeviceError('电量返回值超出范围');
    }
    battery = value;
    return value;
  }

  @override
  Future<Map<String, bool>> getMediaStatus() async {
    if (!mediaSupported) return {};
    final lid = await query(0x050c);
    final paper = await query(0x050d);
    if (!(lid.length == 1 && (lid[0] == 0 || lid[0] == 1)) ||
        !(paper.length == 1 && (paper[0] == 0 || paper[0] == 1))) {
      throw DeviceError('A5 盖/纸状态返回格式无效');
    }
    lidClosed = lid[0] == 1;
    paperPresent = paper[0] == 1;
    mediaCheckedAt = DateTime.now();
    return {'lidClosed': lidClosed!, 'paperPresent': paperPresent!};
  }

  Future<String> getSn() async {
    sn = await _queryText(0x0102);
    return sn!;
  }

  Future<int> getPowerDownTime() async {
    final raw = await query(0x0109);
    powerDownTime = ByteData.sublistView(raw).getUint16(0, Endian.little);
    return powerDownTime!;
  }

  Future<void> setPowerDownTime(int seconds) async {
    if (seconds < 0 || seconds > 65535) {
      throw const FormatException('关机时间必须 0..65535 秒');
    }
    await ack(
      0x010a,
      content: Uint8List.fromList([seconds & 0xFF, (seconds >> 8) & 0xFF]),
    );
    if (await getPowerDownTime() != seconds) {
      throw DeviceError('设备未确认关机时间设置');
    }
  }

  Future<void> keepaliveSetup() async {
    await getBattery();
    await getPowerDownTime();
    if (cfg.disableAutoPoweroff) {
      await setPowerDownTime(0);
    }
  }

  Future<void> selftest() => ack(0x0517);

  Future<void> feed(int lines) => ack(
    0x0516,
    content: Uint8List.fromList([lines & 0xFF, (lines >> 8) & 0xFF]),
  );

  @override
  Future<void> printPng(
    Uint8List png, {
    int? density,
    Future<bool> Function()? cancelCheck,
  }) async {
    final rows = rowsFromPng(png, threshold: cfg.threshold);
    await printRows(rows, density: density, cancelCheck: cancelCheck);
  }

  Future<void> printRows(
    Uint8List rows, {
    int? density,
    Future<bool> Function()? cancelCheck,
  }) async {
    if (rows.isEmpty || rows.length % 48 != 0) {
      throw DeviceError('P1 位图必须每行 48 字节');
    }
    var chunkSize = ((maxLength - 26) ~/ 48) * 48;
    if (chunkSize > 960) chunkSize = 960;
    if (chunkSize < 48) {
      throw DeviceError('设备包长不支持位图');
    }
    // 抓包序：单字节浓度、纸型 0，随后 start/data/finish。
    final level = (density ?? cfg.density).clamp(0, 100);
    await ack(0x0511, content: Uint8List.fromList([level]));
    await ack(0x0520, content: Uint8List.fromList([0, 0]));
    await ack(0x0519);
    var order = 1;
    for (var off = 0; off < rows.length; off += chunkSize, order++) {
      if (cancelCheck != null && await cancelCheck()) {
        throw DeviceError('用户中止图像发送，结果未知；缓冲内容仍可能出纸，不会自动重打');
      }
      final chunk = Uint8List.fromList(
        rows.sublist(
          off,
          off + chunkSize > rows.length ? rows.length : off + chunkSize,
        ),
      );
      await ack(
        0x051b,
        content: bitmapContent(chunk, order),
        timeout: const Duration(seconds: 15),
      );
    }
    if (cancelCheck != null && await cancelCheck()) {
      throw DeviceError('用户中止图像发送，结果未知；缓冲内容仍可能出纸，不会自动重打');
    }
    await ack(0x051a, timeout: const Duration(seconds: 30));
    // P1 在 start→finish 之间收到状态查询会拒绝位图帧；
    // 只有不间断的打印会话结束后才查询。
    if (mediaSupported) {
      final media = await getMediaStatus();
      if (!media['lidClosed']! || !media['paperPresent']!) {
        throw DeviceError('打印结束后检测到开盖或缺纸，结果未知；不会自动重打');
      }
    }
    if (cfg.postFeedLines > 0) {
      await feed(cfg.postFeedLines);
    }
  }
}
