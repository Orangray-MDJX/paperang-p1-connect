"""传输层抽象：BLE GATT / USB bulk 共用同一接口与同一套帧协议。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

OnBytes = Callable[[bytes], None]
OnDisconnected = Callable[[], None]


class Transport(ABC):
    """一帧一 write；收到的原始字节经 on_bytes 回调交给协议解析器。"""

    name: str = "abstract"
    # 单帧最大载荷（不含 10 字节帧开销），超出会损坏打印（设备缓冲有限）
    max_payload: int = 480

    def __init__(self) -> None:
        self.on_bytes: OnBytes | None = None
        self.on_disconnected: OnDisconnected | None = None

    @abstractmethod
    async def open(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def write(self, data: bytes) -> None: ...

    @property
    @abstractmethod
    def is_open(self) -> bool: ...
