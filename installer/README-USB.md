# P1 的 USB 使用说明

实机参考（P1，A5 协议 01.03.18 固件）：VID 4348 / PID 5584。
USB 使用系统 `usbprint.sys` 的双向接口。自定义中文/条纹和 Windows IPP
打印已获得实机确认，无需 Zadig 或替换为 WinUSB。

1. 开机并连接 USB 数据线。
2. 运行 `scripts/run_tray.py`（本机已安装登录自启）。托盘会连接或启动后台服务。
3. 打开 http://127.0.0.1:8765/ 查看 USB 状态与任务。
4. Windows 应用打印时选择 `Paperang P1 (服务)`。

安装队列：管理员 PowerShell 执行 `installer/install_printer.ps1`。
队列使用内置 Microsoft IPP Class Driver，接入 127.0.0.1:8631/ipp/print。
重复安装会检查已存在的队列及驱动；卸载只删除该服务队列与不再使用的端口。

自动关机设置为 0，必须回读确认；每 60 秒发送状态查询。
已关机时软件不能唤醒，请按实体键；USB 未重新枚举时重新插入数据线。
打印发送途中失联会标记结果未知，不自动重打；请先核对纸面。

官方 F2S/F3S 驱动与 libusb/Zadig 探测仅作过调研，不随本项目发布，
也不能作为 P1 兼容性的证明，本项目不依赖官方驱动。
蓝牙按用户要求暂缓验证，默认 USB 失联时不会尝试蓝牙。
