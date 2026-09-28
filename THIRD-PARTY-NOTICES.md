# 第三方组件与许可声明

本项目（paperang-p1-connect，MIT License）使用以下第三方组件。
各组件的完整许可文本以其官方发布为准，本文件仅作汇总提示。

## Python 运行时依赖（requirements.txt）

| 组件 | 许可 | 备注 |
|---|---|---|
| bleak | MIT | 蓝牙 LE |
| pillow | MIT-CMU | 图像处理 |
| pyusb | BSD | USB |
| libusb-package | Apache-2.0 | libusb 二进制打包 |
| pyserial | BSD | 串口 |
| fastapi | MIT | HTTP API |
| uvicorn[standard] | BSD-3-Clause | ASGI 服务器（其传递依赖如 httptools/uvloop/websockets 等均为 MIT/BSD） |
| pystray | **LGPL-3.0** | 托盘图标。以独立 pip 包形式引用、可由用户自行替换，满足 LGPL 引用条件；再分发时须保留其许可与源码可得性 |
| pywebview | BSD-3-Clause | 内嵌网页视图 |
| qrcode[pil] | BSD | 二维码 |
| fastmcp | Apache-2.0 | MCP 服务 |
| httpx | BSD-3-Clause | HTTP 客户端 |
| winrt-* 系列 | MIT | Windows Runtime 投影 |
| zeroconf | **LGPL-2.1-or-later** | mDNS/Bonjour。以独立 pip 包形式引用、可由用户自行替换；再分发时须保留其许可与源码可得性 |

## Windows UI（winui/）

| 组件 | 许可 | 备注 |
|---|---|---|
| QRCoder | MIT | 随附许可文本见 `winui/PaperangP1/Licenses/QRCoder.txt` |
| .NET 8 / Windows App SDK | MIT / 许可见微软官方 | 仅构建运行时依赖，本项目不分发其二进制 |

## 可选外部程序

| 程序 | 许可 | 说明 |
|---|---|---|
| Ghostscript | AGPL-3.0（官方版） | PDF/PS 渲染的可选依赖。本项目**不分发** Ghostscript 二进制，仅以命令行子进程方式调用用户自行安装的副本；不开启该功能则完全不需要它。 |

## 声明

- 本项目不包含、也不再分发任何厂商（Paperang / 喵喵机 / 作业帮）的官方二进制、驱动或应用程序。
- 与上述商标权利人无关联；项目名与文档中的设备名称仅作描述性指代。
