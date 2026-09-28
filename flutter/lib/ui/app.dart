import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import '../services/app_controller.dart';
import '../services/notification_permission.dart';
import 'dashboard_page.dart';
import 'jobs_page.dart';
import 'print_page.dart';
import 'settings_page.dart';

class PaperangApp extends StatelessWidget {
  const PaperangApp({super.key, required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: controller,
      builder: (context, _) => MaterialApp(
        title: 'Paperang P1',
        theme: ThemeData(
          useMaterial3: true,
          colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF252A33)),
        ),
        darkTheme: ThemeData(
          useMaterial3: true,
          colorScheme: ColorScheme.fromSeed(
            seedColor: const Color(0xFF252A33),
            brightness: Brightness.dark,
          ),
        ),
        home: const HomePage(),
      ),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int _index = 0;

  @override
  void initState() {
    super.initState();
    // API 33+ 通知运行时权限：前台服务状态通知需要它
    SchedulerBinding.instance.addPostFrameCallback((_) => _askNotifications());
  }

  Future<void> _askNotifications() async {
    final state = ScaffoldMessenger.of(context);
    final granted = await AppNotificationPermission.request();
    if (!granted && mounted) {
      state.showSnackBar(
        const SnackBar(content: Text('未授予通知权限，前台服务状态将不可见；可在系统设置中开启')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      const DashboardPage(),
      const PrintPage(),
      const JobsPage(),
      const SettingsPage(),
    ];
    return Scaffold(
      body: pages[_index],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.print_outlined),
            selectedIcon: Icon(Icons.print),
            label: '总览',
          ),
          NavigationDestination(
            icon: Icon(Icons.edit_note_outlined),
            selectedIcon: Icon(Icons.edit_note),
            label: '打印',
          ),
          NavigationDestination(
            icon: Icon(Icons.receipt_long_outlined),
            selectedIcon: Icon(Icons.receipt_long),
            label: '任务',
          ),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings),
            label: '设置',
          ),
        ],
      ),
    );
  }
}
