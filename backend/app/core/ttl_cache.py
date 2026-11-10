"""线程安全、有容量上限的内存TTL缓存。"""
import time
from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from typing import Generic, TypeVar

KeyType = TypeVar("KeyType")
ValueType = TypeVar("ValueType")

class TTLCache(
    Generic[KeyType, ValueType]
):
    """TTL负责过期，容量上限负责控制内存占用。

    容量满时移除最早写入的记录。
    这是FIFO策略，不是LRU策略。
    """

    def __init__(
        self,
        ttl_seconds: float,
        max_entries: int = 128,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds必须大于0")

        if max_entries <= 0:
            raise ValueError("max_entries必须大于0")
        
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries

        # 正常运行使用单调时钟。
        # 测试时可以注入假时钟，不需要真实等待。
        self._clock = clock or time.monotonic

        self._values: OrderedDict[
            KeyType,
            tuple[float, ValueType],
        ] = OrderedDict()

        self._lock = Lock()

    def get(
        self,
        key: KeyType,
    ) -> ValueType | None:
        """读取缓存，不存在或已过期时返回None。"""

        with self._lock:
            cached = self._values.get(key)

            if cached is None:
                return None

            expires_at, value = cached

            if self._clock() >= expires_at:
                self._values.pop(key, None)
                return None

            return value

    def set(
        self,
        key: KeyType,
        value: ValueType,
    ) -> None:
        """写入缓存，先清理过期数据，再处理容量限制。"""
        with self._lock:
            now = self._clock()

            expired_keys = [
                cached_key
                for cached_key, (expires_at, _) in self._values.items()
                if now >= expires_at
            ]

            for cached_key in expired_keys:
                self._values.pop(cached_key, None)

            # 更新已有key时，将它视为一次新的写入。
            self._values.pop(key, None)

            while len(self._values) >= self.max_entries:
                self._values.popitem(last=False)

            self._values[key] = (
                now + self.ttl_seconds,
                value,
            )
        

    def clear(self) -> None:
        """清空所有缓存。"""

        with self._lock:
            self._values.clear()