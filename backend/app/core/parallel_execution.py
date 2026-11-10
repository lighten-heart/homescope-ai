"""两个独立同步任务的并发执行与耗时记录。"""

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from typing import TypeVar

from hello_agents.core.exceptions import HelloAgentsException

from app.services.llm_errors import LLMUpstreamError, classify_llm_error


logger = logging.getLogger(__name__)

FirstResult = TypeVar("FirstResult")
SecondResult = TypeVar("SecondResult")
ResultType = TypeVar("ResultType")


class ParallelAgentRunner:
    """每次执行创建两个工作线程，不保存请求状态。"""

    def __init__(self, *, connection_retry_enabled: bool = True) -> None:
        self.connection_retry_enabled = connection_retry_enabled

    def _run_one(
        self,
        stage: str,
        operation: Callable[[], ResultType],
        attempt_durations: list[float] | None = None,
    ) -> tuple[ResultType, float]:
        """执行一个任务，并记录成功或失败时的耗时。"""

        started_at = time.monotonic()
        status = "failed"

        logger.info("specialist_started stage=%s", stage)

        try:
            try:
                result = operation()
            except HelloAgentsException as exc:
                # 为尚未自行转换的框架异常补充阶段信息。
                raise classify_llm_error(exc, stage=stage) from exc

            status = "completed"

        except Exception as exc:
            # 只记录异常类型，不输出模型回复或用户输入。
            logger.warning(
                "specialist_failed stage=%s error_type=%s",
                stage,
                type(exc).__name__,
            )
            raise

        finally:
            duration_ms = round(
                (time.monotonic() - started_at) * 1000,
                2,
            )
            if attempt_durations is not None:
                attempt_durations.append(duration_ms)
            logger.info(
                "specialist_finished stage=%s status=%s duration_ms=%.2f",
                stage,
                status,
                duration_ms,
            )

        return result, duration_ms

    def _collect_result(self, stage, operation, future, attempt_durations):
        """首轮全部结束后，只对无工具专家的明确连接故障恢复一次。"""
        try:
            result, _ = future.result()
        except LLMUpstreamError as exc:
            diagnostics = exc.diagnostics or {}
            if not (
                self.connection_retry_enabled
                and stage in {"commute_agent", "facility_agent"}
                and exc.stage == stage
                and exc.code == "llm_connection_error"
                and diagnostics.get("retryable") is True
                and diagnostics.get("transport_reason") in {
                    "connect_error", "read_error", "remote_protocol_error",
                }
            ):
                raise
            logger.warning(
                "specialist_connection_retry stage=%s retry=1 reason=%s",
                stage, diagnostics["transport_reason"],
            )
            # 这时两个首轮线程已结束；不取消线程、不重跑成功的兄弟任务。
            # 短暂退避，恢复仅发生一次，第二次异常直接向上传播。
            retry_wait_started = time.monotonic()
            time.sleep(0.5)
            attempt_durations.append((time.monotonic() - retry_wait_started) * 1000)
            result, _ = self._run_one(stage, operation, attempt_durations)
        return result, round(sum(attempt_durations), 2)

    def run_pair(
        self,
        *,
        first_stage: str,
        first_operation: Callable[[], FirstResult],
        second_stage: str,
        second_operation: Callable[[], SecondResult],
    ) -> tuple[FirstResult, SecondResult, dict[str, float]]:
        """并发执行两个任务；全部结束后返回结果或抛出异常。"""

        first_durations: list[float] = []
        second_durations: list[float] = []
        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="housing-specialist",
        ) as executor:
            # 先提交两个任务，再等待，避免意外恢复为串行执行。
            first_future = executor.submit(
                self._run_one,
                first_stage,
                first_operation,
                first_durations,
            )
            second_future = executor.submit(
                self._run_one,
                second_stage,
                second_operation,
                second_durations,
            )

            # 所有首轮任务结束之后，才允许对明确的连接故障做一次恢复。
            wait([first_future, second_future])

            # 两个都失败时优先处理第一个；不吞掉结构错误或内容拒绝。
            first_result, first_duration = self._collect_result(
                first_stage, first_operation, first_future, first_durations,
            )
            second_result, second_duration = self._collect_result(
                second_stage, second_operation, second_future, second_durations,
            )

        return (
            first_result,
            second_result,
            {
                first_stage: first_duration,
                second_stage: second_duration,
            },
        )
