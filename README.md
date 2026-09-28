# Paperang P1 Connect

[![CI](https://github.com/Orangray-MDJX/paperang-p1-connect/actions/workflows/ci.yml/badge.svg)](../../actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](pyproject.toml)

非官方的 Paperang（喵喵机）P1 热敏打印机 Windows 服务：把一台只能用手机 App
的口袋打印机接入电脑生态——USB / 经典蓝牙打印、可持久化的任务队列、
局域网 IPP 打印（Android / iOS / Windows 原生打印即可发现）、HTTP API 与
MCP 工具，外加托盘与 WinUI 3 管理界面。

> **声明**：本项目与 Paperang / 喵喵机 / 作业帮无任何关联，为针对自有设备的
> 非官方互操作实现。协议细节见 [docs/protocol-a5.md](docs/protocol-a5.md)。
> 本项目不包含任何厂商官方二进制，也未破解任何加密或访问控制。
> 按原样提供，使用风险自负，请遵守当地法律。

## 功能特性

- **A5 协议**（P1 新固件）：帧构建/流式解析/CRC 校验，命令逐条应答确认，
  真实抓包向量测试；同时保留老机型的 gen1/gen2 协议实现。
- **多通道传输**：USB（系统 usbprint.sys，免 Zadig）、经典蓝牙 RFCOMM、
  BLE（实验）、官方 PC 库桥接（可选）。
- **可持久化任务队列**：SQLite 存储，跨服务重启；缺纸/开盖暂停为 held、
  发送中断标记 unknown 且禁止自动重打，杜绝重复出纸。
- **局域网 IPP 打印**：PWG Raster / Apple Raster(URF) / JPEG / PDF，
  Bonjour(mDNS) 自动发现，子网访问控制；客户端 `print-quality`
  （3 草稿/4 正常/5 高）映射为浓度档。Android、iOS 系统打印与
  Windows 打印队列均可接入。
- **长图打印**：手机浏览器上传 → 黑白预览 → 确认打印，按 384 点宽等比
  缩放，最高约 2 米（详见 [docs/long-image-printing.md](docs/long-image-printing.md)）。
- **HTTP API + MCP**：127.0.0.1:8765 管理 API；MCP stdio 服务让 AI 客户端
  直接调用打印能力。
- **Windows 集成**：托盘（连接状态/电量/待打印数）、WinUI 3 原生管理窗口、
  系统打印队列安装脚本、登录自启。

兼容性与实机验证状态见 [docs/VERIFICATION.md](docs/VERIFICATION.md)。

## 兼容性

| 机型/固件 | USB | 经典蓝牙 | BLE | 说明 |
|---|---|---|---|---|
| P1 · A5 01.03.18 | ✅ | ✅ | 实验 | 本项目验证基准 |
| 其他 A5 固件 | 未验证 | 未验证 | — | 命令表面可能兼容，欢迎反馈 |
| 老款 gen1/gen2 | ✅ | ✅ | ✅ | 沿用社区既有协议 |

设备自报纸宽 57mm / 200dpi，有效打印宽度 384 点（48 字节/行）。

## 安装（Windows 10/11）

```powershell
git clone <repo-url>
cd paperang-p1-connect
python -m venv .venv
.venv\Scripts\pip install -e .[dev]
```

- USB 打印保留系统 `usbprint.sys`，无需 Zadig。
- PDF/PS 渲染为可选能力：安装 Ghostscript 后自动可用，或用配置项
  `gs_path` 指定 `gswin64c.exe` 路径。

## 快速开始

```powershell
# 启动后台服务（单实例）
.venv\Scripts\python.exe scripts\run_service.py

# 管理页
start http://127.0.0.1:8765/

# 命令行打印
.venv\Scripts\python.exe -m paperang_p1 print-text "你好，喵喵机"
```

托盘入口：`.venv\Scripts\python.exe -m paperang_p1.tray`（托盘会拉起并保活服务）。
WinUI 管理窗口需 .NET 8 SDK 构建：`powershell -ExecutionPolicy Bypass -File scripts\build_winui.ps1`。

## HTTP API（仅回环 127.0.0.1:8765）

交互文档见 `http://127.0.0.1:8765/docs`。

| 端点 | 说明 |
|---|---|
| `GET /api/status` | 连接、协议、电量、自动关机时间 |
| `POST /api/print/text` | `{"text":"...","density":0..100}`，返回 job_id |
| `POST /api/print/image` | 本地 `path` 或 `b64` |
| `POST /api/print/file` | 本地 PDF/PS/PNG/JPG |
| `GET /api/jobs` / `GET /api/jobs/{id}` | 任务列表与结果 |
| `POST /api/jobs/{id}/cancel` | 取消；打印中于分片边界停止 |
| `POST /api/jobs/{id}/resume` | 唤醒设备后恢复 held 任务 |
| `GET/PUT /api/config` | 配置读写 |

## 局域网打印

开启后 IPP 端点默认 `http://<本机局域网IP>:8631/ipp/print`，Android /
iOS 系统打印可直接发现（Bonjour），Windows 可手动添加 IPP 打印机。
管理 API 与 MCP 不对局域网开放，LAN 入口限配置子网。

配置与防火墙脚本：`installer/enable_lan.ps1` / `installer/disable_lan.ps1`。
详细步骤与已验证客户端见 [docs/LAN-PRINTING.md](docs/LAN-PRINTING.md)。

## Windows 系统打印队列

管理员 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File installer\install_printer.ps1
```

队列使用内置 Microsoft IPP Class Driver 接入本服务。应用打印时选择
`Paperang P1 (服务)`。卸载用 `installer/uninstall_printer.ps1`。
登录自启：`installer\install_autostart.ps1`。

## MCP

13 个工具覆盖状态、扫描、连接、打印、配置、任务管理。配置示例见
[docs/mcp-config.example.json](docs/mcp-config.example.json)（把路径替换为你的仓库位置）。

## 任务语义与安全边界

- 每个任务进入打印前查询电量；A5 命令逐条匹配 CRC/类型/命令，超时即关闭
  会话重建，不原地重试。
- 发送期间失联 → `unknown`，**不自动重打**；未发送 → `held`，按设备实体键
  唤醒后手动恢复。
- 打印会话（开始→位图→结束）之间不插入状态查询，这是设备的硬约束。
- 已关机/深度休眠的设备无法由软件唤醒；自动关机设 0 会回读确认。
- `transport_pref=auto` 按 USB、经典蓝牙顺序连接；打印过程中不跨通道重发。

## 测试

```powershell
.venv\Scripts\python.exe -m pytest -q
```

覆盖协议帧（真实抓包向量）、任务持久化与中断语义、IPP/PWG/URF 编解码、
LAN 访问控制、长图入口、渲染管线与打印质量链路。无需真实设备。

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/protocol-a5.md](docs/protocol-a5.md) | A5 协议规格（帧格式/命令表/时序/约束） |
| [docs/VERIFICATION.md](docs/VERIFICATION.md) | 已验证能力清单 |
| [docs/LAN-PRINTING.md](docs/LAN-PRINTING.md) | 局域网/IPP 打印部署 |
| [docs/long-image-printing.md](docs/long-image-printing.md) | 长图打印 |
| [installer/README-USB.md](installer/README-USB.md) | USB 通道说明 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 贡献指南与红线 |
| [docs/OPEN-SOURCE-CHECKLIST.md](docs/OPEN-SOURCE-CHECKLIST.md) | 发布/提交前自查清单 |

## 致谢

gen1/gen2 协议的公开先行工作：tinyprinter/python-paperang、ihciah、
sharperang、createskyblue。IPP 实现参考 PWG IPP Everywhere 与
OpenPrinting ippeveprinter。

## 许可证

[MIT](LICENSE)。第三方组件见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。
本仓库不分发任何厂商官方软件与 Ghostscript 二进制。
