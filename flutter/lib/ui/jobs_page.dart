import 'package:flutter/material.dart';

import '../core/queue/job_queue.dart';
import 'controller_scope.dart';

const _stateLabels = {
  'receiving': ('接收文档中', 2),
  'pending': ('等待打印', 1),
  'held': ('等待设备恢复', 2),
  'printing': ('打印中', 1),
  'completed': ('设备已接收', 0),
  'cancelled': ('已取消', 2),
  'failed': ('失败', 2),
  'unknown': ('结果未知', 2),
};

class JobsPage extends StatelessWidget {
  const JobsPage({super.key});

  @override
  Widget build(BuildContext context) {
    final c = ControllerScope.of(context);
    return AnimatedBuilder(
      animation: c,
      builder: (context, _) => Scaffold(
        appBar: AppBar(title: Text('任务（${c.jobs.length}）')),
        body: c.jobs.isEmpty
            ? const Center(child: Text('暂无打印任务'))
            : ListView.builder(
                itemCount: c.jobs.length,
                itemBuilder: (context, i) {
                  final job = c.jobs[i];
                  final (label, tone) =
                      _stateLabels[job.state] ?? (job.state, 2);
                  final color = switch (tone) {
                    0 => Colors.green,
                    1 => Colors.blue,
                    _ => Theme.of(context).colorScheme.error,
                  };
                  final canCancel = !terminalStates.contains(job.state);
                  final canResume = job.state == 'held';
                  return ListTile(
                    leading: Icon(switch (job.state) {
                      'completed' => Icons.check_circle,
                      'printing' => Icons.print,
                      'held' => Icons.pause_circle,
                      'unknown' => Icons.help,
                      _ => Icons.receipt_long,
                    }, color: color),
                    title: Text('#${job.id} ${job.title}'),
                    subtitle: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '$label · ${job.pagesDone}/${job.pageCount} 页'
                          '${job.density != null ? ' · 浓度 ${job.density}' : ''}',
                        ),
                        if (job.state == 'unknown')
                          Text(
                            '可能已部分出纸，不会自动重打；请核对纸面',
                            style: TextStyle(color: color),
                          ),
                        if (job.error != null)
                          Text(
                            job.error!,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(color: color),
                          ),
                      ],
                    ),
                    isThreeLine: true,
                    trailing: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (canResume)
                          IconButton(
                            icon: const Icon(Icons.play_arrow),
                            tooltip: '恢复',
                            onPressed: () => c.resume(job.id),
                          ),
                        if (canCancel)
                          IconButton(
                            icon: const Icon(Icons.stop),
                            tooltip: '取消',
                            onPressed: () => c.cancel(job.id),
                          ),
                      ],
                    ),
                  );
                },
              ),
      ),
    );
  }
}
