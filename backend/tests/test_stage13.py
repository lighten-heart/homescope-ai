"""第十三阶段：专家并发、输入隔离与失败传播。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import Mock

import pytest

from app.agents.agent_utils import SpecialistAgentError
from app.agents.specialist_coordinator import SpecialistCoordinator
from app.core.parallel_execution import ParallelAgentRunner
from app.models.schemas import (
    CommuteAnalysisResult,
    FacilityAnalysisResult,
    SpecialistOpinion,
)
from app.services.candidate_service import CandidateService


def make_analysis(result_type, candidates):
    """生成合法的专家测试结果，不调用模型。"""

    return result_type(
        opinions=[
            SpecialistOpinion(
                candidate_id=candidate.id,
                risk_level="低",
                advantages=["测试优势"],
                risks=[],
                conclusion="测试结论",
            )
            for candidate in candidates
        ]
    )


def test_runner_really_starts_both_tasks():
    """两个任务必须都启动，才能通过屏障。"""

    barrier = Barrier(2)

    def first():
        barrier.wait(timeout=5)
        return "commute"

    def second():
        barrier.wait(timeout=5)
        return "facility"

    first_result, second_result, durations = (
        ParallelAgentRunner().run_pair(
            first_stage="commute_agent",
            first_operation=first,
            second_stage="facility_agent",
            second_operation=second,
        )
    )

    assert first_result == "commute"
    assert second_result == "facility"

    assert set(durations) == {
        "commute_agent",
        "facility_agent",
    }
    assert all(value >= 0 for value in durations.values())


def test_coordinator_isolates_inputs(housing_request):
    """一个专家修改输入，不应影响另一个专家和原始数据。"""

    candidates = CandidateService().list_candidates("北京")

    original_budget = housing_request.monthly_budget
    original_name = candidates[0].name
    original_facilities = list(candidates[0].facilities)

    mutated = Event()

    def commute_operation(request, candidates, requirements=None):
        request.monthly_budget = 1
        candidates[0].name = "被通勤专家修改"
        candidates[0].facilities.append("仅供隔离测试")

        mutated.set()

        return make_analysis(CommuteAnalysisResult, candidates)

    def facility_operation(request, candidates, requirements=None):
        assert mutated.wait(timeout=5)

        assert request.monthly_budget == original_budget
        assert candidates[0].name == original_name
        assert candidates[0].facilities == original_facilities

        return make_analysis(FacilityAnalysisResult, candidates)

    commute_agent = Mock()
    commute_agent.analyze.side_effect = commute_operation

    facility_agent = Mock()
    facility_agent.analyze.side_effect = facility_operation

    result = SpecialistCoordinator(
        commute_agent=commute_agent,
        facility_agent=facility_agent,
    ).analyze(
        request=housing_request,
        candidates=candidates,
    )

    # 调用者自己的数据也不能被污染。
    assert housing_request.monthly_budget == original_budget
    assert candidates[0].name == original_name
    assert candidates[0].facilities == original_facilities

    assert set(result.stage_durations_ms) == {
        "commute_agent",
        "facility_agent",
    }

    commute_agent.analyze.assert_called_once()
    facility_agent.analyze.assert_called_once()


@pytest.mark.parametrize(
    "failed_agent",
    ["commute", "facility"],
)
def test_specialist_failure_is_propagated_without_retry(
    housing_request,
    failed_agent,
):
    """任何一个专家失败，都传播异常且不重复调用专家。"""

    candidates = CandidateService().list_candidates("北京")
    error = SpecialistAgentError("测试用结构校验失败")

    commute_agent = Mock()
    commute_agent.analyze.return_value = make_analysis(
        CommuteAnalysisResult,
        candidates,
    )

    facility_agent = Mock()
    facility_agent.analyze.return_value = make_analysis(
        FacilityAnalysisResult,
        candidates,
    )

    if failed_agent == "commute":
        commute_agent.analyze.side_effect = error
    else:
        facility_agent.analyze.side_effect = error

    coordinator = SpecialistCoordinator(
        commute_agent=commute_agent,
        facility_agent=facility_agent,
    )

    with pytest.raises(SpecialistAgentError) as exc:
        coordinator.analyze(
            request=housing_request,
            candidates=candidates,
        )

    assert exc.value is error
    commute_agent.analyze.assert_called_once()
    facility_agent.analyze.assert_called_once()


def test_runner_waits_for_started_sibling_after_failure():
    """一个任务失败后，另一个已启动任务仍会完成。"""

    failed = Event()
    sibling_finished = Event()
    error = SpecialistAgentError("测试失败")

    def first():
        failed.set()
        raise error

    def second():
        assert failed.wait(timeout=5)
        sibling_finished.set()
        return "done"

    with pytest.raises(SpecialistAgentError) as exc:
        ParallelAgentRunner().run_pair(
            first_stage="commute_agent",
            first_operation=first,
            second_stage="facility_agent",
            second_operation=second,
        )

    assert exc.value is error
    assert sibling_finished.is_set()


def test_llm_client_initialized_once_under_concurrency(monkeypatch):
    """并发首次读取client，只构造一个客户端，不访问网络。"""

    import app.services.llm_service as module
    from app.core.config import Settings

    service = module.LLMService(
        Settings(_env_file=None),
    )

    # 本测试只验证初始化同步，不验证密钥配置。
    monkeypatch.setattr(
        service,
        "_validate_configuration",
        lambda: None,
    )

    fake_client = object()
    factory = Mock(return_value=fake_client)

    monkeypatch.setattr(
        module,
        "ControlledHelloAgentsLLM",
        factory,
    )

    barrier = Barrier(2)

    def read_client():
        barrier.wait(timeout=5)
        return service.client

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(read_client)
        second = executor.submit(read_client)

        assert first.result() is fake_client
        assert second.result() is fake_client

    factory.assert_called_once()