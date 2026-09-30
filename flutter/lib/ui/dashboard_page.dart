import 'package:flutter/material.dart';

import 'controller_scope.dart';
import '../services/intent_bridge.dart';

class DashboardPage extends StatelessWidget {
  const DashboardPage({super.key});

  @override
  Widget build(BuildContext context) {
    final c = ControllerScope.of(context);
    return AnimatedBuilder(
      animation: c,
      builder: (context, _) {
        final s = c.status;
        final connected = s['connected'] == true;
        final error = s['lastError'] as String?;
        return Scaffold(
          appBar: AppBar(title: const Text('总览')),
          body: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              const _BatteryHintCard(),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(
                            connected
                                ? Icons.check_circle
                                : Icons.print_disabled,
                            color: connected
                                ? Colors.green
                                : Theme.of(context).colorScheme.error,
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Text(
                              c.stateLabel,
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      Text(
                        '连接方式：${s['transport'] ?? '未连接'}'
                        '${c.simulated ? '（演示）' : ''}',
                      ),
                      Text(c.batteryLabel),
                      if (s['version'] != null) Text('固件：${s['version']}'),
                      if (s['powerDownTime'] != null)
                        Text('自动关机：${s['powerDownTime']} 秒'),
                      if (c.connectHint.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: Text(
                            c.connectHint,
                            style: TextStyle(
                              color: Theme.of(context).colorScheme.error,
                              fontSize: 13,
                            ),
                          ),
                        ),
                      if (error != null && !connected)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: Text(
                            error,
                            style: TextStyle(
                              color: Theme.of(context).colorScheme.error,
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: connected
                          ? null
                          : () async {
                              try {
                                await c.connect();
                              } catch (e) {
                                if (!context.mounted) return;
                                ScaffoldMessenger.of(
                                  context,
                                ).showSnackBar(SnackBar(content: Text('$e')));
                              }
                            },
                      icon: const Icon(Icons.link),
                      label: const Text('连接打印机'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: connected ? () => c.disconnect() : null,
                      icon: const Icon(Icons.link_off),
                      label: const Text('断开'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Card(
                child: ListTile(
                  leading: const Icon(Icons.pending_actions),
                  title: Text('等待打印：${c.queue.stats.pending} 个任务'),
                  subtitle: Text(
                    '已完成 ${c.queue.stats.done} · 失败/未知 ${c.queue.stats.failed}',
                  ),
                ),
              ),
              if (c.launchError != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    '自动连接失败：${c.launchError}（设备可能已关机，请按实体键唤醒后重试）',
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }
}

/// 后台常驻（前台服务）在国产 ROM 上会被电池优化冻结：表现为后台断连、
/// 严重时点图标无响应。已连接但未豁免时给出一次性引导。
class _BatteryHintCard extends StatefulWidget {
  const _BatteryHintCard();

  @override
  State<_BatteryHintCard> createState() => _BatteryHintCardState();
}

class _BatteryHintCardState extends State<_BatteryHintCard> {
  Future<bool>? _exempt;

  @override
  void didChangeDependencies() {
    _exempt ??= IntentBridge.isIgnoringBatteryOptimizations();
    super.didChangeDependencies();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<bool>(
      future: _exempt,
      builder: (context, snap) {
        final c = ControllerScope.of(context);
        if (snap.data != false || c.simulated) return const SizedBox.shrink();
        return Card(
          color: Theme.of(context).colorScheme.secondaryContainer,
          child: ListTile(
            leading: const Icon(Icons.battery_saver),
            title: const Text('建议关闭电池优化'),
            subtitle: const Text('后台冻结会导致断连甚至无法打开应用'),
            trailing: FilledButton.tonal(
              onPressed: () async {
                await IntentBridge.requestIgnoreBatteryOptimizations();
                if (mounted) {
                  setState(() {
                    _exempt = IntentBridge.isIgnoringBatteryOptimizations();
                  });
                }
              },
              child: const Text('去设置'),
            ),
          ),
        );
      },
    );
  }
}
