"""专业Agent协调器单元测试。"""

from app.agents.specialist_coordinator import (
    SpecialistCoordinator,
)
from app.models.schemas import (
    CommuteAnalysisResult,
    FacilityAnalysisResult,
    HousingDecisionRequest,
    SpecialistOpinion,
)
from app.services.candidate_service import (
    CandidateService,
)


class FakeCommuteAgent:
    """测试用通勤Agent。"""

    def __init__(self) -> None:
        self.called = False

    def analyze(
        self,
        request,
        candidates,
        requirements=None,
    ):
        self.called = True

        return CommuteAnalysisResult(
            opinions=[
                SpecialistOpinion(
                    candidate_id=candidate.id,
                    risk_level="低",
                    advantages=["通勤测试优势"],
                    risks=[],
                    conclusion="通勤测试结论",
                )
                for candidate in candidates
            ]
        )


class FakeFacilityAgent:
    """测试用配套设施Agent。"""

    def __init__(self) -> None:
        self.called = False

    def analyze(
        self,
        request,
        candidates,
        requirements=None,
    ):
        self.called = True

        return FacilityAnalysisResult(
            opinions=[
                SpecialistOpinion(
                    candidate_id=candidate.id,
                    risk_level="低",
                    advantages=["配套测试优势"],
                    risks=[],
                    conclusion="配套测试结论",
                )
                for candidate in candidates
            ]
        )


def test_coordinator_calls_both_agents() -> None:
    """协调器必须调用两个专业Agent。"""

    request = HousingDecisionRequest(
        city="北京",
        work_address="北京市海淀区中关村",
        monthly_budget=5000,
        max_commute_minutes=45,
        preferred_facilities=[
            "地铁站",
            "健身房",
        ],
        preferred_transportation="公共交通",
        free_text_input="希望环境安静",
    )

    candidates = CandidateService().list_candidates(
        "北京"
    )

    commute_agent = FakeCommuteAgent()
    facility_agent = FakeFacilityAgent()

    coordinator = SpecialistCoordinator(
        commute_agent=commute_agent,
        facility_agent=facility_agent,
    )

    result = coordinator.analyze(
        request=request,
        candidates=candidates,
    )

    assert commute_agent.called is True
    assert facility_agent.called is True

    assert len(
        result.commute_analysis.opinions
    ) == 3

    assert len(
        result.facility_analysis.opinions
    ) == 3
