"""运行配置：JSON 持久化于 %APPDATA%/PaperangP1/config.json。"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming"))) / "PaperangP1"
CONFIG_PATH = APP_DIR / "config.json"


@dataclass
class Config:
    # 连接
    transport_pref: str = "usb"          # auto | vendor | spp | usb | ble
    vendor_py32: str | None = None        # 32 位 Python 路径（驱动官方 libprw.dll）
    spp_address: str | None = None        # 经典蓝牙 MAC（gen2 数据通道）
    ble_address: str | None = None        # BLE 地址（旧固件/辅助通道）
    ble_name_prefixes: list[str] = field(
        default_factory=lambda: ["MiaoMiaoJi", "Paperang", "paperang", "miaomiaoji"])
    usb_vid: int = 0x4348
    usb_pid: int = 0x5584

    # A5 会话与旧 02 协议分离；handshake_mode 仅影响旧协议。
    protocol_mode: str = "auto"           # auto | a5 | legacy
    rfcomm_data_channel: int = 1
    handshake_mode: str = "gen2"
    wait_ack_cmd: bool = False            # gen2 固件对指令无 ACK，默认发后不等

    # 打印
    density: int = 80                     # 浓度 0-100
    pre_feed_lines: int = 10              # 打印前进纸（点行）
    post_feed_lines: int = 16            # 打印尾部约 2mm
    chunk_lines_ble: int = 10             # BLE 每包行数（480B 载荷，Yrr0r 实证值）
    chunk_lines_usb: int = 21             # USB 每包行数（1008B，sharperang 实证值）
    chunk_lines_spp: int = 21             # SPP 每包行数（串口链路可靠）
    chunk_delay_ms_ble: float = 60.0      # 包间延迟，防止设备缓冲溢出丢行
    chunk_delay_ms_usb: float = 100.0
    chunk_delay_ms_spp: float = 20.0
    wait_ack: bool = False                # 仅旧协议选项，A5 打印始终逐条等 ACK

    # 保活
    disable_auto_poweroff: bool = True    # 连接后 SET_POWER_DOWN_TIME(0)
    keepalive: bool = True                # 周期 GET_BAT_STATUS 心跳
    keepalive_interval_s: int = 60

    # 渲染
    dither: str = "floyd-steinberg"       # floyd-steinberg | atkinson | threshold
    threshold: int = 128
    font_path: str | None = None          # 缺省自动找 msyh.ttc/simhei.ttf
    font_size: int = 24

    # 服务端口
    api_port: int = 8765                  # 本地 HTTP API（仅 127.0.0.1）
    spool_port: int = 9100                # Windows 打印机 RAW 端口（仅 127.0.0.1）

    ipp_port: int = 8631                  # 本地 IPP 端点

    lan_enabled: bool = False
    lan_address: str = ""
    lan_network: str = ""
    lan_name: str = "Paperang P1"
    ipp_long_media: bool = False          # experimental custom roll lengths

    # Ghostscript
    gs_path: str | None = None

    def validate(self):
        import ipaddress
        if self.lan_enabled:
            address = ipaddress.IPv4Address(self.lan_address)
            network = ipaddress.IPv4Network(self.lan_network)
            if address not in network or address.is_loopback or address.is_unspecified:
                raise ValueError('Invalid LAN address/network')
        if not self.lan_name or len(self.lan_name.encode('utf-8')) > 63 or '.' in self.lan_name:
            raise ValueError('Invalid DNS-SD printer name')
        defaults = Config()
        for f in fields(self):
            value, default = getattr(self, f.name), getattr(defaults, f.name)
            if default is None:
                if value is not None and not isinstance(value, str):
                    raise ValueError(f'{f.name}: expected string or null')
            elif type(default) is float:
                if type(value) not in (int, float): raise ValueError(f'{f.name}: expected number')
            elif type(value) is not type(default):
                raise ValueError(f'{f.name}: invalid type')
        choices = {'transport_pref': ('auto','vendor','usb','spp','ble'),
                   'protocol_mode': ('auto','a5','legacy'),
                   'handshake_mode': ('gen1','gen2','none'),
                   'dither': ('floyd-steinberg','atkinson','threshold')}
        for name, values in choices.items():
            if getattr(self, name) not in values: raise ValueError(f'{name}: unsupported value')
        ranges = {'density': (0,100), 'threshold': (0,255), 'font_size': (1,384),
                  'pre_feed_lines': (0,65535), 'post_feed_lines': (0,65535),
                  'rfcomm_data_channel': (1,30), 'keepalive_interval_s': (5,3600),
                  'usb_vid': (0,65535), 'usb_pid': (0,65535)}
        for name in ('api_port','ipp_port','spool_port'): ranges[name] = (1,65535)
        for name in ('chunk_lines_ble','chunk_lines_usb','chunk_lines_spp'): ranges[name] = (1,1000)
        for name in ('chunk_delay_ms_ble','chunk_delay_ms_usb','chunk_delay_ms_spp'): ranges[name] = (0,10000)
        for name, (low, high) in ranges.items():
            if not low <= getattr(self, name) <= high: raise ValueError(f'{name}: expected {low}..{high}')
        if len({self.api_port,self.ipp_port,self.spool_port}) != 3:
            raise ValueError('service ports must be distinct')
        if not all(isinstance(x, str) for x in self.ble_name_prefixes):
            raise ValueError('ble_name_prefixes: expected strings')

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                names = {f.name for f in fields(cls)}
                for k, v in data.items():
                    if k in names:
                        setattr(cfg, k, v)
                cfg.validate()
            except Exception:
                log.exception("读取配置失败，使用默认配置: %s", CONFIG_PATH)
                cfg = cls()
        return cfg


def find_ghostscript(cfg: Config) -> str | None:
    """定位 gswin64c.exe：配置项 > PATH > 常见安装目录（PDF/PS 渲染可选依赖）。"""
    if cfg.gs_path and Path(cfg.gs_path).exists():
        return cfg.gs_path
    import shutil
    p = shutil.which("gswin64c") or shutil.which("gs")
    if p:
        return p
    for base in (r"C:\Program Files\gs", r"C:\Program Files (x86)\gs"):
        root = Path(base)
        if root.is_dir():
            cands = sorted(root.glob("gs*/bin/gswin64c.exe"))
            if cands:
                return str(cands[-1])
    return None
