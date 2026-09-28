import 'dart:io';

import 'package:flutter/material.dart';

import 'services/app_controller.dart';
import 'services/intent_bridge.dart';
import 'ui/app.dart';
import 'ui/controller_scope.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  var dataDir = Directory.systemTemp.path; // 桌面测试/CLI 兜底
  final filesDir = await IntentBridge.filesDir();
  if (filesDir != null) {
    dataDir = filesDir;
    await Directory(dataDir).create(recursive: true);
  }
  final controller = AppController(dataDir: dataDir);
  // 先上 UI 再初始化服务链：任何启动环节异常都不该留用户在黑屏
  runApp(
    ControllerScope(
      controller: controller,
      notifier: controller,
      child: PaperangApp(controller: controller),
    ),
  );
  unawaited(controller.start());
}

void unawaited(Future<void> f) {}
