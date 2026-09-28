# flutter/

Paperang P1 的 Android 应用（Material Design 3）。构建与使用说明见
[仓库主 README](../README.md)。

- `lib/core/` 是不依赖 Flutter 的纯 Dart 核心：协议、设备会话、队列、
  渲染与网络面，测试直译自桌面版 pytest 黄金向量。
- `lib/platform/` 为 Android 平台通道（经典蓝牙 RFCOMM、USB bulk、
  前台服务）。
