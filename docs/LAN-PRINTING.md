# 局域网打印

以下以 `192.168.1.100` 为例（请替换为本机实际局域网 IP），打印机名 Paperang P1。
打印端点：`http://192.168.1.100:8631/ipp/print`。
手机和电脑须连接同一可互通的 Wi-Fi；访客隔离或跨子网会阻止自动发现。

- Android：打开系统默认打印服务，从应用的“打印”中搜索 Paperang P1。
  自动发现不可用时，若系统支持手动添加 IPP，可输入上述地址。
- iOS/iPadOS：在支持打印的应用中选择“分享 → 打印 → 选择打印机”，搜索 Paperang P1。
  发现使用 Bonjour 的 _universal._sub._ipp._tcp，格式支持 Apple Raster W8。
- Windows：本机原有 Paperang P1 (服务) 队列继续可用。

IPP 支持 PWG Raster、Apple Raster（URF W8）、JPEG，以及 PDF（Windows 桌面端经 Ghostscript，Android 端经系统 PdfRenderer，v0.2.1 起）。
API 与 MCP 管理仍只在 127.0.0.1:8765，局域网端口不提供配置、文件路径打印或管理页面。
LAN 入口限制为配置的子网（示例 `192.168.1.0/24`），防火墙仅开放 TCP 8631 和 UDP 5353。
新增单张长图入口：`http://192.168.1.100:8631/long-image`。先生成黑白预览，再确认打印，绕过手机固定页面排版。
该入口只提供图片上传、对应任务查询与取消；不开放配置或本地文件路径。详见 [长图说明](long-image-printing.md)。

配置：lan_enabled、lan_address、lan_network、lan_name。更改后需重启后台服务，
DHCP 地址变化时须更新地址、子网及防火墙规则。
管理员执行 installer/enable_lan.ps1 会写配置并安装防火墙规则，随后需重启服务。
installer/disable_lan.ps1 会拒绝 LAN 请求并撤销规则；重启后撤回广播且仅监听回环地址。
这些脚本默认管理 API 为 8765，IPP 为 8631。

## 验证证据与边界

实机验证（P1，A5 01.03.18 固件）：

- 独立 mDNS 客户端成功解析 _ipp、_universal 子类型及 _print 子类型，
  端口 8631，URF=W8,RS300,DM1,IS1,V1.4。
- 经 LAN IP 提交 Apple Raster 条纹任务，收到全部打印结束 ACK，job-uri 为 LAN 地址。
- LAN /api/config 与 /docs 返回 404；子网外请求返回 403。
- Android 默认打印服务可发现 P1 并经 LAN→蓝牙通道完成打印，纸面经人工确认。
- iOS Safari / Chrome 原生打印完成；iOS 接受 57×100 mm 自定义纸张。
- Android 忽略自定义 57×100 mm 纸张，使用 4×6 英寸逻辑页面，由服务缩放到 384 点宽。
- 未宣称 AirPrint、Mopria 或 IPP Everywhere 认证。
- USB 连续空闲 30 分钟无断连。

实现参考：
- https://pwg.org/ipp/everywhere.html
- https://openprinting.github.io/driverless
- https://github.com/OpenPrinting/libcups/blob/master/cups/raster-stream.c
- https://github.com/OpenPrinting/libcups/blob/master/tools/ippeveprinter.c
