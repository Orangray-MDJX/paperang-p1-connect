name: 新机型/固件适配
about: 为未验证的机型或固件版本报告兼容性
labels: compatibility
body:
  - type: markdown
    attributes:
      value: |
        本项目仅在 P1（A5 01.03.18）上实机验证。感谢你扩展兼容性矩阵！
        请只提供自观测数据，不要粘贴官方软件的代码或资源。
  - type: input
    id: device
    attributes:
      label: 机型与固件版本
      placeholder: "如 P2 / X2 / F1，固件号（能获取到的话）"
    validations:
      required: true
  - type: dropdown
    id: channel
    attributes:
      label: 测试通道
      options:
        - USB
        - 经典蓝牙（RFCOMM）
        - BLE
        - 未测试
  - type: textarea
    id: observation
    attributes:
      label: 观测结果
      description: |
        服务状态页的连接结果、日志中的帧收发情况、是否应答查询命令等。
        如有条件，欢迎按 docs/protocol-a5.md 的格式整理命令表差异。
    validations:
      required: true
  - type: textarea
    id: extra
    attributes:
      label: 补充信息
      description: SDP 服务列表、GATT 表、广播名等（注意脱敏 MAC）
