/// Android 平台通道：经典蓝牙 RFCOMM 与 USB bulk 传输（Kotlin 侧见
/// android/app/src/main/kotlin/dev/p1connect/paperang_p1/）。
library;

import 'dart:async';

import 'package:flutter/services.dart';

import '../core/transport/transport.dart';

class RfcommTransport extends Transport {
  RfcommTransport(this.address, {this.channel = 1}) {
    maxPayload = 1024;
  }

  final String address;
  final int channel; // SPP 服务固定通道（createRfcommSocketToServiceRecord）

  static const _method = MethodChannel('p1/bluetooth');
  static const _events = EventChannel('p1/bluetooth/events');
  StreamSubscription? _sub;

  @override
  String get name => 'spp';

  @override
  bool isOpen = false;

  /// 列出已配对设备（按名称前缀过滤由调用方完成）。
  static Future<List<Map<Object?, Object?>>> listBonded() async {
    final result = await _method.invokeListMethod<Object?>('listBonded');
    return result?.cast<Map<Object?, Object?>>() ?? const [];
  }

  @override
  Future<void> open() async {
    _sub ??= _events.receiveBroadcastStream().listen(_onEvent, onError: (_) {});
    await _method.invokeMethod('connect', {'address': address});
    isOpen = true;
    lastError = null;
  }

  void _onEvent(dynamic event) {
    if (event is! Map) return;
    if (event['type'] == 'data') {
      onBytes?.call(event['data'] as Uint8List);
    } else if (event['type'] == 'disconnected') {
      lastError = event['reason'] as String?;
      isOpen = false;
      onDisconnected?.call();
    }
  }

  @override
  Future<void> write(Uint8List data) =>
      _method.invokeMethod('write', {'data': data});

  @override
  Future<void> close() async {
    isOpen = false;
    await _sub?.cancel();
    _sub = null;
    try {
      await _method.invokeMethod('close');
    } on PlatformException {
      // 通道可能在服务侧已关闭
    }
  }
}

class UsbBulkTransport extends Transport {
  UsbBulkTransport({required this.vid, required this.pid}) {
    maxPayload = 1024;
  }

  final int vid;
  final int pid;

  static const _method = MethodChannel('p1/usb');
  static const _events = EventChannel('p1/usb/events');
  StreamSubscription? _sub;

  @override
  String get name => 'usb';

  @override
  bool isOpen = false;

  @override
  Future<void> open() async {
    _sub ??= _events.receiveBroadcastStream().listen(_onEvent, onError: (_) {});
    await _method.invokeMethod('open', {'vid': vid, 'pid': pid});
    isOpen = true;
    lastError = null;
  }

  void _onEvent(dynamic event) {
    if (event is! Map) return;
    if (event['type'] == 'data') {
      onBytes?.call(event['data'] as Uint8List);
    } else if (event['type'] == 'disconnected') {
      lastError = event['reason'] as String?;
      isOpen = false;
      onDisconnected?.call();
    }
  }

  @override
  Future<void> write(Uint8List data) =>
      _method.invokeMethod('write', {'data': data});

  @override
  Future<void> close() async {
    isOpen = false;
    await _sub?.cancel();
    _sub = null;
    try {
      await _method.invokeMethod('close');
    } on PlatformException {
      // 通道可能在服务侧已关闭
    }
  }
}
