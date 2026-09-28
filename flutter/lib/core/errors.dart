/// 核心层异常类型。
library;

/// 设备会话错误（连接失败、应答无效、会话毒化等）。
class DeviceError implements Exception {
  DeviceError(this.message);

  final String message;

  @override
  String toString() => 'DeviceError: $message';
}

/// 配置校验失败。
class ConfigError implements Exception {
  ConfigError(this.message);

  final String message;

  @override
  String toString() => 'ConfigError: $message';
}

/// 可达但缺纸/开盖：尚未发送任何页面。
class PrintBlockedError implements Exception {
  PrintBlockedError(this.message);

  final String message;

  @override
  String toString() => 'PrintBlockedError: $message';
}
