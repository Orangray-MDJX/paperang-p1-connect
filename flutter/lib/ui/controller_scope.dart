import 'package:flutter/material.dart';

import '../services/app_controller.dart';

/// 通过 InheritedNotifier 向页面暴露 AppController。
class ControllerScope extends InheritedNotifier {
  const ControllerScope({
    super.key,
    required this.controller,
    required super.notifier,
    required super.child,
  });

  final AppController controller;

  static AppController of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<ControllerScope>()!.controller;
}
