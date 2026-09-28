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
  await controller.start();
  runApp(
    ControllerScope(
      controller: controller,
      notifier: controller,
      child: PaperangApp(controller: controller),
    ),
  );
}
