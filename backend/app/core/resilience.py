"""Agent异步执行、超时和重试控制。"""

import asyncio
from collections.abc import Callable
from functools import lru_cache
from typing import TypeVar

from app.core.config import get_settings

ResultType = TypeVar("ResultType")

class AsyncAgentRunner:
    """在线程池中执行同步Agent调用。"""

    def __init__(
        self,
        timeout_seconds: float,
        retry_attempts: int,
        base_delay_seconds: float,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.base_delay_seconds = (
            base_delay_seconds
        )

    async def run(
        self,
        operation: Callable[[], ResultType],
    ) -> ResultType:
        """异步执行操作，并进行超时和重试。
        
        总执行次数为：

        1次首次调用 + retry_attempts次重试
        """

        total_attempts = (
            self.retry_attempts + 1
        )

        last_error: Exception | None = None

        for attempt_index in range(total_attempts):
            try:
                return await asyncio.wait_for(
                    # 把同步调用放进线程池
                    asyncio.to_thread(operation),
                    timeout=self.timeout_seconds,
                )

            except Exception as exc:
                last_error = exc

                is_last_attempt = (
                    attempt_index
                    == total_attempts - 1
                )

                if is_last_attempt:
                    break

                # 指数退避：
                # 0.5秒、1秒、2秒……
                delay = (
                    self.base_delay_seconds
                    * (2 ** attempt_index)
                )

                await asyncio.sleep(delay)

        if last_error is None:
            raise RuntimeError(
                "Agent执行失败，但没有捕获到异常"
            )

        raise last_error


@lru_cache
def get_async_agent_runner() -> AsyncAgentRunner:
    """返回共享的Agent执行器。"""

    settings = get_settings()

    return AsyncAgentRunner(
        timeout_seconds=(
            settings.agent_timeout_seconds
        ),
        retry_attempts=(
            settings.agent_retry_attempts
        ),
        base_delay_seconds=(
            settings
            .agent_retry_base_delay_seconds
        ),
    )