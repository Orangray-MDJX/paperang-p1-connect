/// 系统交互桥：分享接收、图片选择、应用数据目录。
library;

import 'package:flutter/services.dart';

class IntentBridge {
  static const _channel = MethodChannel('p1/intent');

  static Future<String?> filesDir() async {
    try {
      return await _channel.invokeMethod<String>('filesDir');
    } on PlatformException {
      return null;
    }
  }

  /// 取走通过系统"分享"收到的图片缓存路径（一次性）。
  static Future<String?> takeSharedImage() async {
    try {
      return await _channel.invokeMethod<String>('takeSharedImage');
    } on PlatformException {
      return null;
    }
  }

  /// 系统文件选择器选一张图片，返回缓存路径（取消返回 null）。
  static Future<String?> pickImage() async {
    try {
      return await _channel.invokeMethod<String>('pickImage');
    } on PlatformException {
      return null;
    }
  }

  static Future<void> setBootStart(bool enabled) async {
    await _channel.invokeMethod('setBootStart', {'enabled': enabled});
  }

  static Future<bool> isIgnoringBatteryOptimizations() async {
    try {
      return await _channel.invokeMethod<bool>(
            'isIgnoringBatteryOptimizations',
          ) ??
          false;
    } on PlatformException {
      return false;
    }
  }

  static Future<bool> requestIgnoreBatteryOptimizations() async {
    try {
      return await _channel.invokeMethod<bool>(
            'requestIgnoreBatteryOptimizations',
          ) ??
          false;
    } on PlatformException {
      return false;
    }
  }
}

/// 供 normalizeToPng 使用的 PNG 头嗅探（不用引入额外依赖）。
bool looksLikePng(Uint8List bytes) =>
    bytes.length > 8 &&
    bytes[0] == 0x89 &&
    bytes[1] == 0x50 &&
    bytes[2] == 0x4E &&
    bytes[3] == 0x47;
