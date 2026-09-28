/// 前台服务桥：常驻通知的启动/停止/更新。
library;

import 'package:flutter/services.dart';

class ServiceBridge {
  static const _channel = MethodChannel('p1/service');

  static Future<void> start() => _channel.invokeMethod('start');

  static Future<void> stop() => _channel.invokeMethod('stop');

  static Future<void> update({
    required String state,
    required String battery,
    required int pending,
  }) => _channel.invokeMethod('update', {
    'state': state,
    'battery': battery,
    'pending': pending,
  });
}
