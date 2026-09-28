import 'package:flutter/material.dart';

import '../core/config/config.dart';
import '../platform/android_transports.dart';
import '../services/app_controller.dart';
import '../services/intent_bridge.dart';
import 'controller_scope.dart';

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key});

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  late AppConfig _draft;
  bool _bootStart = false;
  String? _savedHint;

  @override
  void initState() {
    super.initState();
    _draft = ControllerScope.of(context).cfg;
  }

  Future<void> _save(AppController c) async {
    try {
      await c.saveConfig(_draft);
      await IntentBridge.setBootStart(_bootStart);
      if (!mounted) return;
      final lanHint = c.consumeLanRestartHint();
      setState(() => _savedHint = lanHint ? '已保存；局域网设置将在重启服务后生效' : '已保存');
    } catch (e) {
      if (mounted) setState(() => _savedHint = '保存失败：$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = ControllerScope.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('设置')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _section('连接'),
          ListTile(
            title: const Text('连接方式'),
            subtitle: Text(_transportLabel(_draft.transportPref)),
            trailing: PopupMenuButton<String>(
              initialValue: _draft.transportPref,
              onSelected: (v) => setState(() => _draft = _clone(pref: v)),
              itemBuilder: (_) => const [
                PopupMenuItem(value: 'auto', child: Text('自动（USB 优先，回落蓝牙）')),
                PopupMenuItem(value: 'usb', child: Text('USB 数据线')),
                PopupMenuItem(value: 'spp', child: Text('经典蓝牙')),
                PopupMenuItem(value: 'simulated', child: Text('演示模式（模拟打印机）')),
              ],
            ),
          ),
          if (_draft.transportPref == 'spp')
            FutureBuilder<List<Map<Object?, Object?>>>(
              future: RfcommTransport.listBonded(),
              builder: (context, snap) {
                final devices = (snap.data ?? const [])
                    .where((d) => _matchPrefix(d['name'] as String? ?? ''))
                    .toList();
                return ListTile(
                  title: const Text('蓝牙打印机'),
                  subtitle: Text(_draft.sppAddress ?? '未选择'),
                  trailing: PopupMenuButton<String>(
                    onSelected: (addr) =>
                        setState(() => _draft = _clone(sppAddress: addr)),
                    itemBuilder: (_) => devices
                        .map(
                          (d) => PopupMenuItem(
                            value: d['address'] as String,
                            child: Text(
                              '${d['name'] ?? ''} ${_mask(d['address'] as String)}',
                            ),
                          ),
                        )
                        .toList(),
                  ),
                );
              },
            ),
          SwitchListTile(
            title: const Text('保持设备在线'),
            subtitle: const Text('定期查询电量与状态；关闭自动关机'),
            value: _draft.keepalive,
            onChanged: (v) => setState(() => _draft = _clone(keepalive: v)),
          ),
          _section('打印'),
          ListTile(
            title: Text('默认浓度：${_draft.density}'),
            subtitle: Slider(
              value: _draft.density.toDouble(),
              min: 0,
              max: 100,
              divisions: 100,
              label: _draft.density.toString(),
              onChanged: (v) =>
                  setState(() => _draft = _clone(density: v.round())),
            ),
          ),
          ListTile(
            title: Text('抖动算法'),
            subtitle: Text(_draft.dither),
            trailing: PopupMenuButton<String>(
              onSelected: (v) => setState(() => _draft = _clone(dither: v)),
              itemBuilder: (_) => const [
                PopupMenuItem(
                  value: 'floyd-steinberg',
                  child: Text('Floyd-Steinberg（默认）'),
                ),
                PopupMenuItem(value: 'atkinson', child: Text('Atkinson')),
                PopupMenuItem(value: 'threshold', child: Text('阈值（无抖动）')),
              ],
            ),
          ),
          SwitchListTile(
            title: const Text('关闭设备自动关机'),
            subtitle: const Text('连接时设置自动关机为 0 并回读确认'),
            value: _draft.disableAutoPoweroff,
            onChanged: (v) =>
                setState(() => _draft = _clone(disableAutoPoweroff: v)),
          ),
          _section('局域网打印'),
          SwitchListTile(
            title: const Text('开放局域网 IPP'),
            subtitle: const Text('其它设备经 Wi-Fi 打印（iOS/Android/Windows）'),
            value: _draft.lanEnabled,
            onChanged: (v) => setState(() => _draft = _clone(lanEnabled: v)),
          ),
          if (_draft.lanEnabled) ...[
            ListTile(
              title: const Text('本机局域网地址'),
              subtitle: Text(
                _draft.lanAddress.isEmpty ? '未填写' : _draft.lanAddress,
              ),
              trailing: IconButton(
                icon: const Icon(Icons.edit),
                onPressed: () => _editDialog(
                  '局域网地址',
                  _draft.lanAddress,
                  (v) => setState(() => _draft = _clone(lanAddress: v)),
                ),
              ),
            ),
            ListTile(
              title: const Text('允许子网'),
              subtitle: Text(
                _draft.lanNetwork.isEmpty ? '未填写' : _draft.lanNetwork,
              ),
              trailing: IconButton(
                icon: const Icon(Icons.edit),
                onPressed: () => _editDialog(
                  '允许子网（如 192.168.1.0/24）',
                  _draft.lanNetwork,
                  (v) => setState(() => _draft = _clone(lanNetwork: v)),
                ),
              ),
            ),
            ListTile(
              title: const Text('打印机名称'),
              subtitle: Text(_draft.lanName),
              trailing: IconButton(
                icon: const Icon(Icons.edit),
                onPressed: () => _editDialog(
                  '打印机名称',
                  _draft.lanName,
                  (v) => setState(() => _draft = _clone(lanName: v)),
                ),
              ),
            ),
          ],
          _section('系统'),
          SwitchListTile(
            title: const Text('开机自启服务'),
            subtitle: const Text('仅启动常驻服务；连接在设备可用时自动恢复'),
            value: _bootStart,
            onChanged: (v) => setState(() => _bootStart = v),
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: () => _save(c),
            icon: const Icon(Icons.save),
            label: const Text('保存设置'),
          ),
          if (_savedHint != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(_savedHint!),
            ),
        ],
      ),
    );
  }

  bool _matchPrefix(String name) =>
      ControllerScope.of(context).cfg.bleNamePrefixes
          .any((p) => name.toLowerCase().startsWith(p.toLowerCase()));

  String _mask(String address) {
    final parts = address.split(':');
    return parts.length == 6
        ? '${parts[0]}:${parts[1]}:${parts[2]}:••:••:••'
        : address;
  }

  String _transportLabel(String pref) => switch (pref) {
    'auto' => '自动（USB 优先，回落蓝牙）',
    'usb' => 'USB 数据线',
    'spp' => '经典蓝牙',
    'simulated' => '演示模式（模拟打印机）',
    _ => pref,
  };

  Widget _section(String title) => Padding(
    padding: const EdgeInsets.only(top: 16, bottom: 4),
    child: Text(
      title,
      style: Theme.of(context).textTheme.labelLarge
          ?.copyWith(color: Theme.of(context).colorScheme.primary),
    ),
  );

  AppConfig _clone({
    String? pref,
    String? sppAddress,
    bool? keepalive,
    int? density,
    String? dither,
    bool? disableAutoPoweroff,
    bool? lanEnabled,
    String? lanAddress,
    String? lanNetwork,
    String? lanName,
  }) {
    final next = AppConfig.fromJson(_draft.toJson());
    if (pref != null) next.transportPref = pref;
    if (sppAddress != null) next.sppAddress = sppAddress;
    if (keepalive != null) next.keepalive = keepalive;
    if (density != null) next.density = density;
    if (dither != null) next.dither = dither;
    if (disableAutoPoweroff != null) {
      next.disableAutoPoweroff = disableAutoPoweroff;
    }
    if (lanEnabled != null) next.lanEnabled = lanEnabled;
    if (lanAddress != null) next.lanAddress = lanAddress;
    if (lanNetwork != null) next.lanNetwork = lanNetwork;
    if (lanName != null) next.lanName = lanName;
    return next;
  }

  Future<void> _editDialog(
    String title,
    String initial,
    void Function(String) onOk,
  ) async {
    final controller = TextEditingController(text: initial);
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: TextField(controller: controller, autofocus: true),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('确定'),
          ),
        ],
      ),
    );
    if (ok == true) {
      onOk(controller.text.trim());
    }
    controller.dispose();
  }
}
