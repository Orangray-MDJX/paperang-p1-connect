# 已验证能力清单

本项目所有"已完成"结论都有对应的实机验证或自动化测试支撑。
下表为汇总；带 * 的项目需要真实设备，无法在 CI 中复现。

## 协议层（自动化测试，真实抓包向量）

| 能力 | 证据 |
|---|---|
| A5 帧构建/流式解析/CRC/坏帧滑窗 | `tests/test_a5.py` 真实抓包向量逐字节验证 |
| gen1/gen2 帧协议（老机型） | `tests/test_protocol.py` |
| 分片/粘包、错误命令响应、超时关闭 | 同上 |

## 打印链路 *（实机：P1 · A5 01.03.18）

| 能力 | 结果 |
|---|---|
| USB 中文/条纹打印 | 纸面确认 |
| 经典蓝牙 RFCOMM ch1 打印（独立蓝牙会话） | 纸面确认 |
| Windows 系统打印（IPP 队列 → 服务 → 设备） | 测试页内容与纸长确认 |
| PDF / PS 渲染（Ghostscript 可选依赖） | 纸面确认 |
| 浓度分档、浓度阶梯验收 | 纸面对比确认 |

## 可靠性边界 *（实机验证的产品语义）

| 场景 | 行为 |
|---|---|
| 打印中拔 USB / 断蓝牙 / 设备关机 | 任务标记 unknown，禁止自动重打 |
| 缺纸 / 开盖 | 任务暂停为 held，装纸/合盖后手动恢复 |
| 发送中取消 | 分片边界停止，结果标记 unknown |
| 设备空闲 30 分钟（自动关机设 0） | 无断连，状态轮询持续 |
| 服务重启 / 电脑重启 | 队列 SQLite 持久化，历史任务不重打 |
| 登录自启 | 计划任务方式验收（真实重启） |

## 局域网打印 *（多客户端实机）

| 客户端 | 结果 |
|---|---|
| Android 系统默认打印服务 | 发现 + 打印完成，纸面确认 |
| iOS Safari / Chrome | 打印完成，纸面确认；接受 57×100 mm 自定义纸张 |
| Windows / 第三方 IPP 客户端 | Apple Raster / PWG Raster 任务收到完整结束应答 |
| 长图网页入口（Android / iOS 上传） | 预览→确认→打印全流程，纸面确认 |

## Android 应用 *（实机：P1 · A5 01.03.18，v0.2.1）*

| 能力 | 结果 |
|---|---|
| 蓝牙自动连接（BLE 敲门 → RFCOMM） | 冷启动即连，电量/纸仓真实应答 |
| PDF 打开/渲染/翻页/缩放预览 | 3 页文档逐页验证 |
| PDF 打印（打印本页） | 任务 completed 1/1，每数据块 ACK |
| PDF 页面导出 PNG 到下载目录 | MediaStore 落盘确认（integration test） |
| 经典蓝牙直连（通道 1） | RFCOMM 会话与 A5 握手正常 |
| 桌面端 BLE 敲门重连（服务） | 深睡设备免按键自动恢复连接 |

## 桌面端（v0.2.1 修复回归）

| 能力 | 证据 |
|---|---|
| 幽灵连接竞态（安卓桥 success 时机） | `flutter/test/connection_manager_test.dart` + 真机 logcat |
| 桌面 BLE 敲门（`_ble_poke`） | 实机：spp 首败 → poke → 重连成功，`tests/`（68 项）全绿 |

## 服务与集成（自动化测试 + 实机）

| 能力 | 证据 |
|---|---|
| HTTP API、任务队列持久化、取消/恢复 | `tests/test_api.py`、`test_jobs.py` |
| IPP 服务（PWG/Apple Raster/JPEG） | `tests/test_ipp.py` |
| LAN 子网访问控制（403/404 边界） | `tests/test_lan.py` |
| 长图入口（凭证隔离、过期、防重复确认） | `tests/test_long_image.py` |
| 打印质量管线 | `tests/test_quality_pipeline.py` |
| MCP 工具 | 本地集成验证 |

> 未宣称：AirPrint / Mopria / IPP Everywhere 认证；对 01.03.18 之外固件的兼容性。
