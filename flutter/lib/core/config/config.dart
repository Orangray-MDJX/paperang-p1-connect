/// 运行配置（键名/默认值/校验规则与桌面版 config.py 对齐）。
///
/// 持久化为 JSON 文件；路径由上层注入（App 用应用数据目录，测试用临时目录）。
library;

import 'dart:convert';
import 'dart:io';

import '../errors.dart';

class AppConfig {
  AppConfig();

  // 连接
  String transportPref = 'usb'; // auto | vendor | spp | usb | ble
  String? vendorPy32;
  String? sppAddress;
  String? bleAddress;
  List<String> bleNamePrefixes = [
    'MiaoMiaoJi',
    'Paperang',
    'paperang',
    'miaomiaoji',
  ];
  int usbVid = 0x4348;
  int usbPid = 0x5584;

  // 协议
  String protocolMode = 'auto'; // auto | a5 | legacy
  int rfcommDataChannel = 1;
  String handshakeMode = 'gen2'; // gen1 | gen2 | none
  bool waitAckCmd = false;

  // 打印
  int density = 80;
  int preFeedLines = 10;
  int postFeedLines = 16;
  int chunkLinesBle = 10;
  int chunkLinesUsb = 21;
  int chunkLinesSpp = 21;
  double chunkDelayMsBle = 60.0;
  double chunkDelayMsUsb = 100.0;
  double chunkDelayMsSpp = 20.0;
  bool waitAck = false;
  bool disableAutoPoweroff = true;
  bool keepalive = true;
  int keepaliveIntervalS = 60;
  String dither = 'floyd-steinberg'; // floyd-steinberg | atkinson | threshold
  int threshold = 128;
  String? fontPath;
  int fontSize = 24;

  // 网络
  int apiPort = 8765;
  int spoolPort = 9100;
  int ippPort = 8631;
  bool lanEnabled = false;
  String lanAddress = '';
  String lanNetwork = '';
  String lanName = 'Paperang P1';
  bool ippLongMedia = false;
  String? gsPath;

  Map<String, dynamic> toJson() => {
    'transport_pref': transportPref,
    'vendor_py32': vendorPy32,
    'spp_address': sppAddress,
    'ble_address': bleAddress,
    'ble_name_prefixes': bleNamePrefixes,
    'usb_vid': usbVid,
    'usb_pid': usbPid,
    'protocol_mode': protocolMode,
    'rfcomm_data_channel': rfcommDataChannel,
    'handshake_mode': handshakeMode,
    'wait_ack_cmd': waitAckCmd,
    'density': density,
    'pre_feed_lines': preFeedLines,
    'post_feed_lines': postFeedLines,
    'chunk_lines_ble': chunkLinesBle,
    'chunk_lines_usb': chunkLinesUsb,
    'chunk_lines_spp': chunkLinesSpp,
    'chunk_delay_ms_ble': chunkDelayMsBle,
    'chunk_delay_ms_usb': chunkDelayMsUsb,
    'chunk_delay_ms_spp': chunkDelayMsSpp,
    'wait_ack': waitAck,
    'disable_auto_poweroff': disableAutoPoweroff,
    'keepalive': keepalive,
    'keepalive_interval_s': keepaliveIntervalS,
    'dither': dither,
    'threshold': threshold,
    'font_path': fontPath,
    'font_size': fontSize,
    'api_port': apiPort,
    'spool_port': spoolPort,
    'ipp_port': ippPort,
    'lan_enabled': lanEnabled,
    'lan_address': lanAddress,
    'lan_network': lanNetwork,
    'lan_name': lanName,
    'ipp_long_media': ippLongMedia,
    'gs_path': gsPath,
  };

  static AppConfig fromJson(Map<String, dynamic> data) {
    final cfg = AppConfig();
    final json = _coerceTypes(data);
    json.forEach((key, value) {
      switch (key) {
        case 'transport_pref':
          cfg.transportPref = value as String;
        case 'vendor_py32':
          cfg.vendorPy32 = value as String?;
        case 'spp_address':
          cfg.sppAddress = value as String?;
        case 'ble_address':
          cfg.bleAddress = value as String?;
        case 'ble_name_prefixes':
          cfg.bleNamePrefixes = (value as List).cast<String>();
        case 'usb_vid':
          cfg.usbVid = value as int;
        case 'usb_pid':
          cfg.usbPid = value as int;
        case 'protocol_mode':
          cfg.protocolMode = value as String;
        case 'rfcomm_data_channel':
          cfg.rfcommDataChannel = value as int;
        case 'handshake_mode':
          cfg.handshakeMode = value as String;
        case 'wait_ack_cmd':
          cfg.waitAckCmd = value as bool;
        case 'density':
          cfg.density = value as int;
        case 'pre_feed_lines':
          cfg.preFeedLines = value as int;
        case 'post_feed_lines':
          cfg.postFeedLines = value as int;
        case 'chunk_lines_ble':
          cfg.chunkLinesBle = value as int;
        case 'chunk_lines_usb':
          cfg.chunkLinesUsb = value as int;
        case 'chunk_lines_spp':
          cfg.chunkLinesSpp = value as int;
        case 'chunk_delay_ms_ble':
          cfg.chunkDelayMsBle = (value as num).toDouble();
        case 'chunk_delay_ms_usb':
          cfg.chunkDelayMsUsb = (value as num).toDouble();
        case 'chunk_delay_ms_spp':
          cfg.chunkDelayMsSpp = (value as num).toDouble();
        case 'wait_ack':
          cfg.waitAck = value as bool;
        case 'disable_auto_poweroff':
          cfg.disableAutoPoweroff = value as bool;
        case 'keepalive':
          cfg.keepalive = value as bool;
        case 'keepalive_interval_s':
          cfg.keepaliveIntervalS = value as int;
        case 'dither':
          cfg.dither = value as String;
        case 'threshold':
          cfg.threshold = value as int;
        case 'font_path':
          cfg.fontPath = value as String?;
        case 'font_size':
          cfg.fontSize = value as int;
        case 'api_port':
          cfg.apiPort = value as int;
        case 'spool_port':
          cfg.spoolPort = value as int;
        case 'ipp_port':
          cfg.ippPort = value as int;
        case 'lan_enabled':
          cfg.lanEnabled = value as bool;
        case 'lan_address':
          cfg.lanAddress = value as String;
        case 'lan_network':
          cfg.lanNetwork = value as String;
        case 'lan_name':
          cfg.lanName = value as String;
        case 'ipp_long_media':
          cfg.ippLongMedia = value as bool;
        case 'gs_path':
          cfg.gsPath = value as String?;
      }
    });
    return cfg;
  }

  /// num→int/double 按目标字段整理（JSON 里 int/double 边界与 Python 一致：
  /// 数值字段接受 int 或 double，double 字段以 num 收敛）。
  static Map<String, dynamic> _coerceTypes(Map<String, dynamic> data) {
    return Map.fromEntries(
      data.entries.map((e) {
        if (e.value is num && e.key.startsWith('chunk_delay')) {
          return MapEntry(e.key, (e.value as num).toDouble());
        }
        return MapEntry(e.key, e.value);
      }),
    );
  }

  void validate() {
    void inSet(String name, String value, Set<String> allowed) {
      if (!allowed.contains(value)) {
        throw ConfigError('$name 必须是 ${allowed.join('/')}');
      }
    }

    void range(String name, int value, int min, int max) {
      if (value < min || value > max) {
        throw ConfigError('$name 必须在 $min..$max 之间');
      }
    }

    inSet('transport_pref', transportPref, {
      'auto',
      'vendor',
      'spp',
      'usb',
      'ble',
    });
    inSet('protocol_mode', protocolMode, {'auto', 'a5', 'legacy'});
    inSet('handshake_mode', handshakeMode, {'gen1', 'gen2', 'none'});
    inSet('dither', dither, {'floyd-steinberg', 'atkinson', 'threshold'});
    range('density', density, 0, 100);
    range('threshold', threshold, 0, 255);
    range('font_size', fontSize, 1, 384);
    range('pre_feed_lines', preFeedLines, 0, 65535);
    range('post_feed_lines', postFeedLines, 0, 65535);
    range('chunk_lines_ble', chunkLinesBle, 1, 1000);
    range('chunk_lines_usb', chunkLinesUsb, 1, 1000);
    range('chunk_lines_spp', chunkLinesSpp, 1, 1000);
    if (chunkDelayMsBle < 0 || chunkDelayMsBle > 10000) {
      throw ConfigError('chunk_delay_ms_ble 必须在 0..10000 之间');
    }
    if (chunkDelayMsUsb < 0 || chunkDelayMsUsb > 10000) {
      throw ConfigError('chunk_delay_ms_usb 必须在 0..10000 之间');
    }
    if (chunkDelayMsSpp < 0 || chunkDelayMsSpp > 10000) {
      throw ConfigError('chunk_delay_ms_spp 必须在 0..10000 之间');
    }
    range('keepalive_interval_s', keepaliveIntervalS, 5, 3600);
    range('rfcomm_data_channel', rfcommDataChannel, 1, 30);
    range('usb_vid', usbVid, 0, 65535);
    range('usb_pid', usbPid, 0, 65535);
    for (final name in ['api_port', 'ipp_port', 'spool_port']) {
      final v = switch (name) {
        'api_port' => apiPort,
        'ipp_port' => ippPort,
        _ => spoolPort,
      };
      range(name, v, 1, 65535);
    }
    if (apiPort == ippPort || apiPort == spoolPort || ippPort == spoolPort) {
      throw ConfigError('api_port/ipp_port/spool_port 不能重复');
    }
    if (lanEnabled) {
      if (lanAddress.isEmpty || lanNetwork.isEmpty) {
        throw ConfigError('启用局域网必须提供 lan_address 与 lan_network');
      }
      if (!_ipInNetwork(lanAddress, lanNetwork)) {
        throw ConfigError('lan_address 必须位于 lan_network 子网内');
      }
      if (_isLoopbackOrUnspecified(lanAddress)) {
        throw ConfigError('lan_address 不能是回环或未指定地址');
      }
    }
    final nameBytes = utf8.encode(lanName);
    if (lanName.isEmpty || nameBytes.length > 63 || lanName.contains('.')) {
      throw ConfigError('lan_name 非空、UTF-8 不超过 63 字节且不含点');
    }
    for (final p in bleNamePrefixes) {
      if (p.isEmpty) throw ConfigError('ble_name_prefixes 不能包含空串');
    }
  }

  static bool _isLoopbackOrUnspecified(String ip) =>
      ip == '0.0.0.0' || ip.startsWith('127.') || ip == '::' || ip == '::1';

  static bool _ipInNetwork(String ip, String cidr) {
    try {
      final parts = cidr.split('/');
      if (parts.length != 2) return false;
      final prefix = int.parse(parts[1]);
      final netAddr = InternetAddress.tryParse(parts[0]);
      final ipAddr = InternetAddress.tryParse(ip);
      if (netAddr == null || ipAddr == null) return false;
      if (netAddr.type != ipAddr.type) return false;
      final a = netAddr.rawAddress, b = ipAddr.rawAddress;
      var remaining = prefix;
      for (var i = 0; i < a.length && remaining > 0; i++) {
        final bits = remaining >= 8 ? 8 : remaining;
        final mask = (0xFF << (8 - bits)) & 0xFF;
        if ((a[i] & mask) != (b[i] & mask)) return false;
        remaining -= 8;
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  static AppConfig load(File file) {
    if (!file.existsSync()) return AppConfig();
    try {
      final cfg = AppConfig.fromJson(
        jsonDecode(file.readAsStringSync()) as Map<String, dynamic>,
      );
      cfg.validate();
      return cfg;
    } catch (_) {
      return AppConfig();
    }
  }

  void save(File file) {
    file.parent.createSync(recursive: true);
    file.writeAsStringSync(
      const JsonEncoder.withIndent('  ').convert(toJson()),
    );
  }
}
