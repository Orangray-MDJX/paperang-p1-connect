import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../services/app_controller.dart';
import '../services/intent_bridge.dart';
import 'controller_scope.dart';
import 'pdf_print_tab.dart';

class PrintPage extends StatefulWidget {
  const PrintPage({super.key});

  @override
  State<PrintPage> createState() => _PrintPageState();
}

class _PrintPageState extends State<PrintPage> {
  final _text = TextEditingController();
  int? _density;
  double _fontSize = 24;
  String? _pickedPath;
  Uint8List? _pickedBytes;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _takeSharedIfAny();
  }

  Future<void> _takeSharedIfAny() async {
    final path = await IntentBridge.takeSharedImage();
    if (path != null && mounted) {
      await _loadPicked(path);
    }
  }

  Future<void> _pick() async {
    final path = await IntentBridge.pickImage();
    if (path == null) return;
    await _loadPicked(path);
  }

  Future<void> _loadPicked(String path) async {
    final bytes = await File(path).readAsBytes();
    setState(() {
      _pickedPath = path;
      _pickedBytes = bytes;
    });
  }

  Future<void> _submitText(AppController c) async {
    final text = _text.text.trim();
    if (text.isEmpty || _busy) return;
    setState(() => _busy = true);
    try {
      final id = await c.submitText(
        text,
        density: _density,
        fontSize: _fontSize.round(),
      );
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('任务 $id 已提交')));
        _text.clear();
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _submitImage(AppController c) async {
    final bytes = _pickedBytes;
    if (bytes == null || _busy) return;
    setState(() => _busy = true);
    try {
      final name = _pickedPath?.split(Platform.pathSeparator).last ?? '图片';
      final id = await c.submitImage(bytes, name, density: _density);
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('任务 $id 已提交')));
        setState(() {
          _pickedBytes = null;
          _pickedPath = null;
        });
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = ControllerScope.of(context);
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('打印'),
          bottom: const TabBar(
            tabs: [
              Tab(text: '文本'),
              Tab(text: '图片'),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            ListView(
              padding: const EdgeInsets.all(16),
              children: [
                TextField(
                  controller: _text,
                  maxLines: 5,
                  minLines: 2,
                  decoration: const InputDecoration(
                    labelText: '打印内容',
                    hintText: '支持多行与中文，自动按 384 点宽换行',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),
                ListTile(
                  title: const Text('字体大小'),
                  subtitle: Slider(
                    value: _fontSize,
                    min: 12,
                    max: 64,
                    divisions: 52,
                    label: _fontSize.round().toString(),
                    onChanged: (v) => setState(() => _fontSize = v),
                  ),
                  trailing: Text('${_fontSize.round()}'),
                ),
                _densitySelector(),
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: _busy ? null : () => _submitText(c),
                  icon: const Icon(Icons.print),
                  label: const Text('打印'),
                ),
              ],
            ),
            ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (_pickedBytes != null)
                  Card(
                    child: Column(
                      children: [
                        Image.memory(
                          _pickedBytes!,
                          height: 240,
                          fit: BoxFit.contain,
                        ),
                        OverflowBar(
                          children: [
                            TextButton(
                              onPressed: () => setState(() {
                                _pickedBytes = null;
                                _pickedPath = null;
                              }),
                              child: const Text('移除'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  onPressed: _pick,
                  icon: const Icon(Icons.photo_library_outlined),
                  label: Text(_pickedBytes == null ? '选择图片' : '重新选择'),
                ),
                const SizedBox(height: 8),
                Text(
                  '自动缩放到 384 点宽（57mm 纸宽）；透明区域按白纸打印。'
                  '长图无需裁切，按宽度等比输出。',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 8),
                _densitySelector(),
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: _pickedBytes == null || _busy
                      ? null
                      : () => _submitImage(c),
                  icon: const Icon(Icons.print),
                  label: const Text('打印'),
                ),
              ],
            ),
            const PdfPrintTab(),
          ],
        ),
      ),
    );
  }

  Widget _densitySelector() {
    return ListTile(
      title: const Text('打印浓度'),
      subtitle: _density == null
          ? const Text('跟随全局设置')
          : Text('$_density / 100'),
      trailing: PopupMenuButton<int?>(
        initialValue: _density,
        onSelected: (v) => setState(() => _density = v),
        itemBuilder: (_) => [
          const PopupMenuItem(value: null, child: Text('跟随全局设置')),
          for (final v in [0, 30, 50, 80, 100])
            PopupMenuItem(value: v, child: Text('$v')),
        ],
        child: const Padding(
          padding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          child: Icon(Icons.tune),
        ),
      ),
    );
  }
}
