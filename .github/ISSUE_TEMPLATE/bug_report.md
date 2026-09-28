name: Bug 报告
about: 打印异常 / 服务错误 / 协议无响应
labels: bug
body:
  - type: markdown
    attributes:
      value: |
        感谢反馈！请尽量填写以下信息。日志与配置中不要包含设备序列号、
        内网地址等敏感信息（可用 `AA:BB:CC:DD:EE:FF`、`192.168.1.x` 占位）。
  - type: input
    id: env
    attributes:
      label: 环境
      placeholder: "Windows 版本 / Python 版本 / 连接通道（USB 或蓝牙）"
    validations:
      required: true
  - type: input
    id: device
    attributes:
      label: 设备与固件
      placeholder: "机型 + 固件版本（服务状态页可见，如 P1 / 01.03.18）"
    validations:
      required: true
  - type: textarea
    id: what-happened
    attributes:
      label: 发生了什么？
      description: 期望行为与实际行为；复现步骤
    validations:
      required: true
  - type: textarea
    id: logs
    attributes:
      label: 相关日志 / 任务状态
      description: "`GET /api/status` 输出、任务 state、服务报错栈"
  - type: dropdown
    id: entry
    attributes:
      label: 入口
      options:
        - HTTP API / 管理页
        - 局域网 IPP（Android/iOS/Windows）
        - MCP
        - CLI
        - Windows 打印队列
        - WinUI 窗口
