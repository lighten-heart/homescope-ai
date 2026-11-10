"""专业Agent协调器：并发执行通勤和设施分析。"""

from functools import lru_cache

from app.agents.commute_agent import (
    CommuteAnalysisAgent,
    get_commute_agent,
)
from app.agents.facility_agent import (
    FacilityAnalysisAgent,
    get_facility_agent,
)
from app.core.parallel_execution import ParallelAgentRunner
from app.models.schemas import (
    CandidateArea,
    HousingDecisionRequest,
    MultiAgentSpecialistResult,
    RequirementAnalysis,
)

class SpecialistCoordinator:
    """为两个专家准备独立输入，并汇总并发分析结果。"""

    def __init__(
        self,
        commute_agent: CommuteAnalysisAgent,
        facility_agent: FacilityAnalysisAgent,
        *,
        parallel_runner: ParallelAgentRunner | None = None,
    ) -> None:
        self.commute_agent = commute_agent
        self.facility_agent = facility_agent
        self.parallel_runner = (
            parallel_runner
            if parallel_runner is not None
            else ParallelAgentRunner()
        )

    def analyze(
        self,
        request: HousingDecisionRequest,
        candidates: list[CandidateArea],
        requirements: RequirementAnalysis | None = None,
    ) -> MultiAgentSpecialistResult:
        """并发分析；任意专家失败时向调用者传播异常。"""

        # 两个专家分别拿到独立的输入副本。
        # 某个专家修改输入时，不会影响另一个专家或编排器。
        commute_request = request.model_copy(deep=True)
        facility_request = request.model_copy(deep=True)

        commute_candidates = [
            candidate.model_copy(deep=True)
            for candidate in candidates
        ]

        facility_candidates = [
            candidate.model_copy(deep=True)
            for candidate in candidates
        ]

        commute_requirements = (
            requirements.model_copy(deep=True)
            if requirements is not None
            else None
        )

        facility_requirements = (
            requirements.model_copy(deep=True)
            if requirements is not None
            else None
        )

        (
            commute_analysis,
            facility_analysis,
            durations,
        ) = self.parallel_runner.run_pair(
            first_stage="commute_agent",
            first_operation=lambda: self.commute_agent.analyze(
                request=commute_request,
                candidates=commute_candidates,
                requirements=commute_requirements,
            ),
            second_stage="facility_agent",
            second_operation=lambda: self.facility_agent.analyze(
                request=facility_request,
                candidates=facility_candidates,
                requirements=facility_requirements,
            ),
        )

        return MultiAgentSpecialistResult(
            commute_analysis=commute_analysis,
            facility_analysis=facility_analysis,
            stage_durations_ms=durations,
        )


@lru_cache
def get_specialist_coordinator() -> SpecialistCoordinator:
    """返回不保存请求输入和对话历史的协调器。"""
        
    return SpecialistCoordinator(
        commute_agent=get_commute_agent(),
        facility_agent=get_facility_agent(),
    )
