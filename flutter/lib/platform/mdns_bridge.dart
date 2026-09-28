/// mDNS/Bonjour 注册桥（NsdManager + TXT + MulticastLock，Kotlin 侧实现）。
library;

import 'package:flutter/services.dart';

class MdnsBridge {
  static const _channel = MethodChannel('p1/mdns');

  /// 注册 _ipp._tcp；返回实际注册名。TXT 全集对齐桌面版 lan_discovery.py。
  static Future<String?> register({
    required String name,
    required int port,
    required Map<String, String> txt,
  }) async {
    try {
      return await _channel.invokeMethod<String>('register', {
        'name': name,
        'port': port,
        'txt': txt,
      });
    } on PlatformException {
      return null;
    }
  }

  static Future<void> unregister() => _channel.invokeMethod('unregister');

  static Future<String?> uuid() async {
    try {
      return await _channel.invokeMethod<String>('uuid');
    } on PlatformException {
      return null;
    }
  }

  /// 桌面版 TXT 全集（URF/媒体/USB 标识）。
  static Map<String, String> txt({
    required String uuid,
    required String product,
    required String pdl,
    required String hostname,
  }) => {
    'txtvers': '1',
    'qtotal': '1',
    'rp': 'ipp/print',
    'ty': product,
    'product': '($product)',
    'pdl': pdl,
    'URF': 'W8,RS300,DM1,IS1,V1.4',
    'Color': 'F',
    'Duplex': 'F',
    'UUID': uuid,
    'usb_MFG': 'Paperang',
    'usb_MDL': 'P1',
    'note': 'Paperang P1 service on $hostname',
    'priority': '0',
  };
}
