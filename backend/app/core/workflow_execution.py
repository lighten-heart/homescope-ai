"""工作流阶段计时和阶段间预算检查。"""

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from hello_agents.core.exceptions import HelloAgentsException

from app.services.llm_errors import classify_llm_error

logger = logging.getLogger(__name__)

class WorkflowBudgetExceeded(RuntimeError):
    """自定义超出预算异常"""

    def __init__(
        self,
        stage: str,
        elapsed_ms: float,
        durations: dict[str, float],
    ) -> None:
        super().__init__("工作流超过阶段间时间预算")
        self.stage = stage
        self.elapsed_ms = elapsed_ms
        self.stage_durations_ms = dict(durations)


class WorkflowExecution:
    """一次工作流请求的计时与预算管理器"""

    def __init__(
        self,
        budget_seconds: float,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if budget_seconds <= 0:
            raise ValueError("budget_seconds必须大于0")

        self._clock = clock or time.monotonic
        self._started_at = self._clock()
        self._budget_seconds = budget_seconds

        self.stage_durations_ms: dict[str, float] = {}

    @property
    def elapsed_ms(self) -> float:
        """看总共用了多久时间"""

        return round(
            (self._clock() - self._started_at) * 1000,
            2,
        )

    def checkpoint(self, stage: str) -> None:
        """只检查总时间是否超出预算"""

        elapsed_seconds = self._clock() - self._started_at

        if elapsed_seconds >= self._budget_seconds:
            raise WorkflowBudgetExceeded(
                stage=stage,
                elapsed_ms=self.elapsed_ms,
                durations=self.stage_durations_ms,
            )

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        """自动包住一个阶段，完成计时和异常处理"""

        self.checkpoint(stage)
        started_at = self._clock()

        try:
            yield

        except HelloAgentsException as exc:
            # 补齐其他Agent尚未统一处理的模型异常。
            # 已转换成LLMUpstreamError的异常会原样继续传播。
            raise classify_llm_error(
                exc,
                stage=stage,
            ) from exc

        finally:
            duration_ms = round(
                (self._clock() - started_at) * 1000,
                2,
            )

            self.stage_durations_ms[stage] = duration_ms

            # 不记录地址、模型回复或密钥。
            logger.info(
                "workflow_stage stage=%s duration_ms=%.2f",
                stage,
                duration_ms,
            )

        # 如果阶段正常返回，但已经耗尽预算，
        # 在这里停止，不启动下一阶段。
        self.checkpoint(stage)