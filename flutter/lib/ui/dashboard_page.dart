import 'package:flutter/material.dart';

import 'controller_scope.dart';

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
        final battery = s['battery'];
        final error = s['lastError'] as String?;
        return Scaffold(
          appBar: AppBar(title: const Text('总览')),
          body: ListView(
            padding: const EdgeInsets.all(16),
            children: [
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
                      if (battery != null) Text('电量：$battery%'),
                      if (s['version'] != null) Text('固件：${s['version']}'),
                      if (s['powerDownTime'] != null)
                        Text('自动关机：${s['powerDownTime']} 秒'),
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
