/// 连接管理：传输优先级（auto = USB → 经典蓝牙）、会话复用、保活轮询。
/// 直译自 connection_manager.py 的 DeviceManager（A5 通道；老机型 legacy
/// 会话暂未接入，协议层已就绪）。
library;

import 'dart:async';

import '../config/config.dart';
import '../device/device_a5.dart';
import '../device/printer_device.dart';
import '../queue/job_queue.dart';
import '../transport/transport.dart';
import '../util/async_lock.dart';

/// 按传输名构造通道；返回 null 表示该通道当前不可用（无设备/无权限）。
typedef TransportFactory = Transport? Function(String name);

class DeviceManager implements QueueManager {
  DeviceManager(
    this.cfg, {
    required this.createTransport,
    this.simulated = false,
  });

  final AppConfig cfg;
  final TransportFactory createTransport;

  /// 演示模式：固定使用模拟打印机（无真机时在模拟器上完整体验）。
  final bool simulated;

  @override
  final AsyncLock operationLock = AsyncLock();

  A5Device? device;
  String state = 'disconnected';
  String? lastError;
  DateTime? lastSeen;
  Timer? _keepalive;
  String _currentTransport = '';

  List<String> get _prefs {
    if (simulated) return ['simulated'];
    if (cfg.transportPref == 'auto') return ['usb', 'spp'];
    return [cfg.transportPref];
  }

  @override
  Future<PrinterDevice> ensureConnected([String? pref]) async {
    final names = pref == null ? _prefs : [pref];
    final dev = device;
    if (dev != null &&
        dev.transport.isOpen &&
        dev.state == A5State.ready &&
        names.contains(dev.transport.name)) {
      return dev;
    }
    await disconnect();
    Object? lastFailure;
    for (final name in names) {
      try {
        final transport = name == 'simulated'
            ? (createTransport('simulated') ??
                  (throw StateError('simulated transport 未配置')))
            : createTransport(name);
        if (transport == null) continue;
        final candidate = A5Device(transport, cfg);
        await candidate.connect();
        await candidate.keepaliveSetup();
        device = candidate;
        _currentTransport = transport.name;
        state = 'ready';
        lastError = null;
        lastSeen = DateTime.now();
        return candidate;
      } on StateError {
        rethrow;
      } catch (e) {
        lastFailure = e;
        // 保活初始化失败仅在该通道实际已断时才算连接失败，
        // 与桌面版语义一致：继续尝试下一个通道。
      }
    }
    state = 'fault';
    lastError = '无法连接打印机: $lastFailure';
    throw StateError(lastError!);
  }

  @override
  Future<void> disconnect() async {
    _keepalive?.cancel();
    _keepalive = null;
    final dev = device;
    device = null;
    _currentTransport = '';
    if (dev != null) {
      try {
        await dev.close();
      } catch (_) {}
    }
  }

  /// 启动保活轮询（电量 + 盖/纸，与打印串行）。
  void startKeepalive() {
    _keepalive?.cancel();
    if (!cfg.keepalive) return;
    _keepalive = Timer.periodic(Duration(seconds: cfg.keepaliveIntervalS), (
      _,
    ) async {
      await operationLock.synchronize(() async {
        final dev = device;
        if (dev == null || dev.state != A5State.ready) return;
        try {
          await dev.getBattery();
          await dev.getMediaStatus();
          lastSeen = DateTime.now();
        } catch (_) {
          await disconnect();
          state = 'fault';
          lastError = '保活查询无应答，连接已关闭';
        }
      });
    });
  }

  Future<void> stop() async {
    _keepalive?.cancel();
    _keepalive = null;
    await disconnect();
  }

  Map<String, Object?> status() {
    final dev = device;
    final ready = dev?.state == A5State.ready;
    String display = state;
    if (ready) {
      if (dev!.lidClosed == false) {
        display = 'blocked';
      } else if (dev.paperPresent == false) {
        display = 'blocked';
      }
    }
    return {
      'connected': ready,
      'printable':
          ready && dev!.lidClosed != false && dev.paperPresent != false,
      'lidClosed': dev?.lidClosed,
      'paperPresent': dev?.paperPresent,
      'state': display,
      'protocol': dev == null ? null : 'a5',
      'transport': _currentTransport,
      'version': dev?.version,
      'sn': dev?.sn,
      'battery': dev?.battery,
      'powerDownTime': dev?.powerDownTime,
      'lastError': lastError,
    };
  }
}
