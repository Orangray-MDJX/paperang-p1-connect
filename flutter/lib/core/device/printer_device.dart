/// 队列面向的打印机设备契约。
library;

import 'dart:typed_data';

abstract class PrinterDevice {
  String get protocol; // 'a5' | 'legacy'

  /// 电量百分比；无有效应答时抛异常（陈旧句柄防线）。
  Future<double> getBattery();

  /// 盖/纸状态；不支持的机型返回空 Map。
  Future<Map<String, bool>> getMediaStatus();

  Future<void> printPng(
    Uint8List png, {
    int? density,
    Future<bool> Function()? cancelCheck,
  });
}
