/// API 33+ 通知运行时权限申请（前台服务状态通知）。
library;

import 'package:flutter/services.dart';

class AppNotificationPermission {
  static const _channel = MethodChannel('p1/intent');

  /// 返回是否已授权（旧版本恒为 true）。
  static Future<bool> request() async {
    try {
      final granted = await _channel.invokeMethod<bool>('requestNotifications');
      return granted ?? true;
    } on PlatformException {
      return false;
    }
  }
}
