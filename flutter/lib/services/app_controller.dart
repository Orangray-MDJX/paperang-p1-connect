/// App 编排层：配置/连接管理/队列/前台服务通知的状态中枢。
library;

import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

import '../core/config/config.dart';
import '../core/connection/connection_manager.dart';
import '../core/queue/job_queue.dart';
import '../core/transport/simulated.dart';
import '../core/transport/transport.dart';
import '../platform/android_transports.dart';
import '../platform/service_bridge.dart';
import 'text_image.dart';

class AppController extends ChangeNotifier {
  AppController({required this.dataDir});

  final String dataDir;
  late AppConfig cfg;
  late DeviceManager mgr;
  late JobQueue queue;

  Map<String, Object?> status = {};
  List<JobRow> jobs = const [];
  Timer? _timer;
  String? launchError;

  bool get simulated => cfg.transportPref == 'simulated';
  String get configPath => '$dataDir${Platform.pathSeparator}config.json';
  String get dbPath => '$dataDir${Platform.pathSeparator}jobs.sqlite3';

  Future<void> start() async {
    cfg = AppConfig.load(File(configPath));
    mgr = DeviceManager(
      cfg,
      createTransport: _createTransport,
      simulated: simulated,
    );
    queue = await JobQueue.open(
      mgr,
      dbPath: dbPath,
      onEvent: (level, msg) {
        debugPrint('[$level] $msg');
      },
    );
    queue.start();
    unawaited(_autoConnect());
    _timer = Timer.periodic(const Duration(seconds: 1), (_) => refresh());
    await refresh();
  }

  Future<void> _autoConnect() async {
    try {
      await connect();
    } catch (e) {
      launchError = '$e';
      notifyListeners();
    }
  }

  Future<void> refresh() async {
    status = mgr.status();
    try {
      jobs = await queue.list(limit: 50);
    } catch (_) {}
    _updateNotification();
    notifyListeners();
  }

  Future<void> _updateNotification() async {
    try {
      await ServiceBridge.update(
        state: stateLabel,
        battery: batteryLabel,
        pending: queue.stats.pending,
      );
    } catch (_) {}
  }

  /// 状态机的界面文案（对齐桌面版托盘/管理页）。
  String get stateLabel {
    if (simulated && status['connected'] != true) return '演示模式（模拟打印机）';
    if (status['state'] == 'blocked') {
      if (status['lidClosed'] == false) return '请合好纸仓盖';
      if (status['paperPresent'] == false) return '打印机缺纸';
    }
    if (status['connected'] == true) {
      return queue.stats.printing ? '正在打印' : '设备已就绪';
    }
    switch (status['state']) {
      case 'connecting':
        return '正在连接打印机';
      case 'ready':
        return '设备已就绪';
      case 'fault':
        return '连接中断';
      default:
        return '等待打印机';
    }
  }

  String get batteryLabel {
    final b = status['battery'];
    if (b == null) return '';
    final text = b is double ? b.toStringAsFixed(0) : '$b';
    return '电量 $text%';
  }

  Transport? _createTransport(String name) {
    switch (name) {
      case 'usb':
        return UsbBulkTransport(vid: cfg.usbVid, pid: cfg.usbPid);
      case 'spp':
        final addr = cfg.sppAddress;
        if (addr == null || addr.isEmpty) return null;
        return RfcommTransport(addr);
      case 'simulated':
        return SimulatedPrinter(name: 'simulated');
    }
    return null;
  }

  Future<void> connect() async {
    await mgr.ensureConnected();
    mgr.startKeepalive();
    await refresh();
  }

  Future<void> disconnect() async {
    await mgr.disconnect();
    await refresh();
  }

  Future<int> submitText(String text, {int? density, int? fontSize}) async {
    final png = await textToPng(text, fontSize: fontSize ?? cfg.fontSize);
    return queue.submit(
      PrintJob(
        title: text.length > 24 ? '${text.substring(0, 24)}…' : text,
        pages: [png],
        density: density,
        source: 'text',
      ),
    );
  }

  Future<int> submitImage(List<int> bytes, String title, {int? density}) async {
    final png = await normalizeToPng(bytes);
    return queue.submit(
      PrintJob(title: title, pages: [png], density: density, source: 'image'),
    );
  }

  Future<void> cancel(int jobId) async {
    await queue.cancel(jobId);
    await refresh();
  }

  Future<void> resume(int jobId) async {
    await queue.resume(jobId);
    await refresh();
  }

  Future<void> saveConfig(AppConfig next) async {
    next.validate();
    next.save(File(configPath));
    final restartNeeded =
        next.apiPort != cfg.apiPort ||
        next.ippPort != cfg.ippPort ||
        next.lanEnabled != cfg.lanEnabled ||
        next.lanAddress != cfg.lanAddress ||
        next.lanNetwork != cfg.lanNetwork;
    final transportChanged =
        next.transportPref != cfg.transportPref ||
        next.usbVid != cfg.usbVid ||
        next.usbPid != cfg.usbPid ||
        next.sppAddress != cfg.sppAddress;
    cfg = next;
    mgr.cfg = next;
    if (transportChanged) {
      await mgr.disconnect();
      unawaited(_autoConnect());
    }
    await refresh();
    if (restartNeeded) {
      _lanRestartHint = true;
      notifyListeners();
    }
  }

  bool _lanRestartHint = false;
  bool consumeLanRestartHint() {
    final v = _lanRestartHint;
    _lanRestartHint = false;
    return v;
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}
