"""Paperang P1 (喵喵机) Windows 打印连接服务。"""

__version__ = "0.1.0"

# P1 热敏打印头规格
LINE_DOTS = 384          # 每行点数
LINE_BYTES = LINE_DOTS // 8   # 每行字节数 = 48
DPI = 203                # 约每英寸点数（8 点/mm）
