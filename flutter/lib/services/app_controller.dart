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
import '../core/net/long_image.dart';
import '../net/lan_server.dart';
import '../platform/android_transports.dart';
import '../platform/mdns_bridge.dart';
import '../platform/service_bridge.dart';
import 'pdf_service.dart';
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
  LanServer? _lan;
  late final LongImageService longImage;

  bool get simulated => cfg.transportPref == 'simulated';
  String get configPath => '$dataDir${Platform.pathSeparator}config.json';
  String get dbPath => '$dataDir${Platform.pathSeparator}jobs.sqlite3';

  Future<void> start() async {
    final configFile = File(configPath);
    cfg = AppConfig.load(configFile);
    if (!configFile.existsSync() && cfg.transportPref == 'usb') {
      // 移动端首启默认自动（USB 优先，回落蓝牙）；桌面默认值保持 'usb'。
      cfg.transportPref = 'auto';
    }
    debugPrint(
      'P1DBG cfg loaded pref=${cfg.transportPref} lan=${cfg.lanEnabled}',
    );
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
      canAutoRetryConnect = true;
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
      case 'ble':
        // 广播扫描优先于地址（P1 的 LE 地址可不同于经典地址且未必配对），
        // 地址仅作为扫描未命中时的回退目标。
        final addr = cfg.bleAddress ?? cfg.sppAddress ?? '';
        return BleTransport(addr);
      case 'simulated':
        return SimulatedPrinter(name: 'simulated');
    }
    return null;
  }

  /// sppAddress 未配置时按名字前缀自动选择已配对设备；仅改内存，随下次保存落盘。
  Future<void> _ensureSppAddress() async {
    if ((cfg.sppAddress ?? '').isNotEmpty) return;
    try {
      final bonded = await RfcommTransport.listBonded();
      debugPrint('listBonded -> ${bonded.length} devices: '
          '${bonded.map((d) => d['name']).join(',')}');
      for (final d in bonded) {
        final name = d['name'] as String? ?? '';
        final hit = cfg.bleNamePrefixes.any(
          (p) => name.toLowerCase().startsWith(p.toLowerCase()),
        );
        if (hit) {
          cfg.sppAddress = d['address'] as String?;
          cfg.bleAddress = d['address'] as String?;
          debugPrint('auto-resolved ble/spp device: $name ${cfg.sppAddress}');
          return;
        }
      }
    } catch (e) {
      debugPrint('listBonded failed: $e');
    }
  }

  /// 首启自动连接失败后允许一次静默重试（权限弹窗挂起流程的补救）。
  bool canAutoRetryConnect = false;

  Future<void> retryConnectQuietly() async {
    if (!canAutoRetryConnect) return;
    canAutoRetryConnect = false;
    try {
      await connect();
    } catch (_) {
      // 仍失败则保持当前错误展示，不弹新提示
    }
  }

  Future<void> connect() async {
    await _ensureSppAddress();
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

  Future<int> submitPdfPages(
    List<Uint8List> pages,
    String title, {
    int? density,
    int from = 1,
  }) async {
    return queue.submit(
      PrintJob(title: title, pages: pages, density: density, source: 'pdf'),
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
    await _syncLanServer();
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

  /// LAN 网关与 mDNS 随配置开关；地址/子网变化需重启（与桌面一致）。
  Future<void> _syncLanServer() async {
    if (cfg.lanEnabled && cfg.lanAddress.isNotEmpty) {
      if (_lan?.isRunning != true) {
        _lan = LanServer(
          cfg: cfg,
          mgr: mgr,
          jobs: queue,
          longImage: longImage,
          pdfRenderer: PdfService.renderForPrint,
        );
        await _lan!.start();
      }
      final uuid = await MdnsBridge.uuid() ?? 'p1';
      final host = Platform.localHostname.split('.').first;
      await MdnsBridge.register(
        name: cfg.lanName,
        port: cfg.ippPort,
        txt: MdnsBridge.txt(
          uuid: uuid,
          product: cfg.lanName,
          pdl: 'image/urf,image/pwg-raster,image/jpeg',
          hostname: host,
        ),
      );
    } else {
      await MdnsBridge.unregister();
      await _lan?.stop();
      _lan = null;
    }
  }

  String get lanUrl => _lan?.isRunning == true
      ? 'http://${cfg.lanAddress}:${cfg.ippPort}/long-image'
      : '';

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}
