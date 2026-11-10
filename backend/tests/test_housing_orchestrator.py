"""完整多Agent编排器测试。"""

from types import SimpleNamespace
from unittest.mock import Mock
from app.services.map_cache_service import MapCacheService
import pytest

from app.agents.housing_orchestrator import (
    HousingDecisionOrchestrator,
)
from app.models.schemas import (
    CandidateDecisionExplanation,
    CommuteAnalysisResult,
    DecisionNarrative,
    FacilityAnalysisResult,
    HousingDecisionRequest,
    MultiAgentSpecialistResult,
    RequirementAnalysis,
    SpecialistOpinion,
)
from app.services.candidate_service import (
    CandidateService,
)
from app.models.schemas import (
    Location,
    MapCandidateEnrichment,
    MapEnrichmentResult,
)

class FakeRequirementAgent:
    def analyze(
        self,
        request: HousingDecisionRequest,
    ) -> RequirementAnalysis:
        return RequirementAnalysis(
            city=request.city,
            work_address=request.work_address,
            monthly_budget=request.monthly_budget,
            max_commute_minutes=(
                request.max_commute_minutes
            ),
            preferred_transportation=(
                request.preferred_transportation
            ),
            required_facilities=[],
            optional_facilities=(
                request.preferred_facilities
            ),
            lifestyle_tags=["安静"],
            hard_constraints=["预算和通勤限制"],
            soft_preferences=["环境安静"],
            clarification_questions=[],
            summary="测试需求分析",
        )


class FakeSpecialistCoordinator:
    def analyze(
        self,
        request,
        candidates,
        requirements=None,
    ) -> MultiAgentSpecialistResult:
        opinions = [
            SpecialistOpinion(
                candidate_id=candidate.id,
                risk_level="低",
                advantages=["测试优势"],
                risks=[],
                conclusion="测试结论",
            )
            for candidate in candidates
        ]

        return MultiAgentSpecialistResult(
            commute_analysis=CommuteAnalysisResult(
                opinions=opinions
            ),
            facility_analysis=FacilityAnalysisResult(
                opinions=opinions
            ),
        )


class FakeDecisionAgent:
    def synthesize(
        self,
        request,
        requirements,
        specialist_analysis,
        scoring_result,
    ) -> DecisionNarrative:
        explanations = [
            CandidateDecisionExplanation(
                candidate_id=(
                    evaluation.candidate.id
                ),
                recommendation_level=(
                    "优先推荐"
                    if evaluation.rank == 1
                    else "可以考虑"
                ),
                explanation="测试综合解释",
                main_advantages=["测试优势"],
                main_tradeoffs=["测试权衡"],
            )
            for evaluation
            in scoring_result.evaluations
        ]

        return DecisionNarrative(
            executive_summary="测试总体结论",
            candidate_explanations=explanations,
            overall_risks=[],
            next_actions=["实地看房"],
        )

class FakeMapDataAgent:
    """测试用地图Agent，不连接高德。"""
    def enrich(
        self,
        request,
        candidates,
    ) -> MapEnrichmentResult:
        return MapEnrichmentResult(
            work_location=Location(
                longitude=116.30,
                latitude=39.98,
            ),
            candidates=[
                MapCandidateEnrichment(
                    candidate_id=candidate.id,
                    location=candidate.location,
                    commute_minutes=(
                        candidate.commute_minutes
                    ),
                    route_distance_meters=10000,
                    subway_distance_meters=(
                        candidate
                        .subway_distance_meters
                    ),
                    facilities=candidate.facilities,
                    evidence=["测试地图证据"],
                )
                for candidate in candidates
            ],
        )

def test_complete_orchestrator_pipeline(
    housing_request: HousingDecisionRequest,
) -> None:
    """完整工作流应返回确定性推荐结果。"""

    orchestrator = HousingDecisionOrchestrator(
        candidate_service=CandidateService(),
        requirement_agent=FakeRequirementAgent(),
        specialist_coordinator=(
            FakeSpecialistCoordinator()
        ),
        decision_agent=FakeDecisionAgent(),
        map_data_agent=FakeMapDataAgent(),
        map_cache=MapCacheService(ttl_seconds=60),
    )

    result = orchestrator.run(housing_request)

    assert (
        result.recommended_candidate_id
        == "beijing-area-a"
    )

    assert len(
        result.scoring_result.evaluations
    ) == 3

    assert result.pipeline_trace == [
        "candidate_service_completed",
        "requirement_agent_completed",
        "map_data_agent_completed",
        "specialist_agents_completed",
        "deterministic_scoring_completed",
        "decision_agent_completed",
    ]


def make_demo_orchestrator(map_agent):
    return HousingDecisionOrchestrator(
        candidate_service=CandidateService(),
        requirement_agent=FakeRequirementAgent(),
        map_data_agent=map_agent,
        specialist_coordinator=FakeSpecialistCoordinator(),
        decision_agent=FakeDecisionAgent(),
        map_enrichment_enabled=False,
        map_cache=MapCacheService(ttl_seconds=60),
    )


def test_demo_mode_skips_map_and_preserves_mock_provenance(housing_request):
    map_agent = Mock()
    result = make_demo_orchestrator(map_agent).run(housing_request)
    map_agent.enrich.assert_not_called()
    assert result.map_enrichment is None
    assert result.model_dump()["map_enrichment"] is None
    assert "map_data_agent_skipped_demo_mode" in result.pipeline_trace
    assert "map_data_agent_completed" not in result.pipeline_trace
    assert result.pipeline_trace[-1] == "decision_agent_completed"
    assert all(e.candidate.data_source == "mock" for e in result.scoring_result.evaluations)
    assert "模拟" in result.scoring_result.disclaimer
    assert any("学习模式" in risk for risk in result.narrative.overall_risks)


def test_live_failure_does_not_silently_fallback_to_demo(housing_request):
    from app.services.llm_errors import LLMUpstreamError

    map_agent = Mock()
    error = LLMUpstreamError("llm_content_rejected", "拒绝", "map_data_agent", None)
    map_agent.enrich.side_effect = error
    orchestrator = make_demo_orchestrator(map_agent)
    orchestrator.map_enrichment_enabled = True
    orchestrator.specialist_coordinator = Mock()
    with pytest.raises(LLMUpstreamError) as exc:
        orchestrator.run(housing_request)
    assert exc.value is error
    orchestrator.specialist_coordinator.analyze.assert_not_called()


def test_demo_api_explicitly_marks_skipped_map(client, valid_payload, monkeypatch):
    from app.main import app
    from app.agents.housing_orchestrator import get_housing_orchestrator

    orchestrator = make_demo_orchestrator(None)
    monkeypatch.setitem(app.dependency_overrides, get_housing_orchestrator, lambda: orchestrator)
    response = client.post("/api/workflows/housing-decision", json=valid_payload)
    assert response.status_code == 200
    assert "学习模式" in response.json()["message"]
    assert response.json()["data"]["map_enrichment"] is None


def test_demo_factory_does_not_construct_map_agent(monkeypatch):
    import app.agents.housing_orchestrator as module

    factory = Mock(side_effect=AssertionError("不应创建地图Agent"))
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(map_enrichment_enabled=False))
    monkeypatch.setattr(module, "get_map_data_agent", factory)
    module.get_housing_orchestrator.cache_clear()
    try:
        orchestrator = module.get_housing_orchestrator()
        assert orchestrator.map_data_agent is None
        factory.assert_not_called()
    finally:
        module.get_housing_orchestrator.cache_clear()


def test_constructor_accepts_injected_dependencies():
    """新增依赖可显式注入，构造时不会调用执行器或缓存。"""
    runner, cache, settings = Mock(), Mock(), Mock()
    orchestrator = HousingDecisionOrchestrator(
        candidate_service=CandidateService(),
        requirement_agent=FakeRequirementAgent(),
        map_data_agent=None,
        specialist_coordinator=FakeSpecialistCoordinator(),
        decision_agent=FakeDecisionAgent(),
        map_enrichment_enabled=False,
        runner=runner,
        map_cache=cache,
        settings=settings,
    )
    assert orchestrator.runner is runner
    assert orchestrator.map_cache is cache
    assert orchestrator.settings is settings
    runner.run.assert_not_called()
    cache.get.assert_not_called()


def test_constructor_supports_existing_callers(monkeypatch):
    """旧代码不传新增依赖时仍能构造实例，避免修复语法后出现TypeError。"""
    import app.agents.housing_orchestrator as module

    runner, cache, settings = Mock(), Mock(), Mock()
    monkeypatch.setattr(module, "get_async_agent_runner", lambda: runner)
    monkeypatch.setattr(module, "get_map_cache_service", lambda: cache)
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    orchestrator = HousingDecisionOrchestrator(
        candidate_service=CandidateService(),
        requirement_agent=FakeRequirementAgent(),
        map_data_agent=None,
        specialist_coordinator=FakeSpecialistCoordinator(),
        decision_agent=FakeDecisionAgent(),
        map_enrichment_enabled=False,
    )
    assert orchestrator.runner is runner
    assert orchestrator.map_cache is cache
    assert orchestrator.settings is settings


def test_factory_wires_new_dependencies(monkeypatch):
    import app.agents.housing_orchestrator as module

    settings = SimpleNamespace(map_enrichment_enabled=False)
    runner, cache = Mock(), Mock()
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(module, "get_async_agent_runner", lambda: runner)
    monkeypatch.setattr(module, "get_map_cache_service", lambda: cache)
    module.get_housing_orchestrator.cache_clear()
    try:
        orchestrator = module.get_housing_orchestrator()
        assert orchestrator.settings is settings
        assert orchestrator.runner is runner
        assert orchestrator.map_cache is cache
    finally:
        module.get_housing_orchestrator.cache_clear()


def test_app_lifespan_and_openapi_start_without_external_calls():
    """导入应用并走启动/关闭生命周期；不触发模型或高德调用。"""
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        response = client.get("/openapi.json")
        assert response.status_code == 200
        assert "/api/workflows/housing-decision" in response.json()["paths"]


def test_repeated_workflow_reuses_map_result(housing_request):
    from app.core.config import Settings

    settings = Settings(
        _env_file=None,
        map_cache_enabled=True,
        workflow_budget_seconds=600,
    )

    map_agent = Mock(wraps=FakeMapDataAgent())

    orchestrator = HousingDecisionOrchestrator(
        candidate_service=CandidateService(),
        requirement_agent=FakeRequirementAgent(),
        map_data_agent=map_agent,
        specialist_coordinator=FakeSpecialistCoordinator(),
        decision_agent=FakeDecisionAgent(),
        map_cache=MapCacheService(ttl_seconds=60),
        settings=settings,
    )

    first = orchestrator.run(housing_request)
    second = orchestrator.run(housing_request)

    # 两次工作流，只调用一次地图Agent。
    assert map_agent.enrich.call_count == 1

    assert first.cache_hits == []
    assert second.cache_hits == ["map_enrichment"]

    assert "map_data_agent_completed" in first.pipeline_trace
    assert "map_cache_hit" in second.pipeline_trace

    assert "decision_agent_completed" in second.pipeline_trace
    assert "map_enrichment" in second.stage_durations_ms


def test_disabled_cache_always_calls_map(housing_request):
    from app.core.config import Settings

    settings = Settings(
        _env_file=None,
        map_cache_enabled=False,
        workflow_budget_seconds=600,
    )

    map_agent = Mock(wraps=FakeMapDataAgent())

    orchestrator = HousingDecisionOrchestrator(
        candidate_service=CandidateService(),
        requirement_agent=FakeRequirementAgent(),
        map_data_agent=map_agent,
        specialist_coordinator=FakeSpecialistCoordinator(),
        decision_agent=FakeDecisionAgent(),
        map_cache=MapCacheService(ttl_seconds=60),
        settings=settings,
    )

    orchestrator.run(housing_request)
    result = orchestrator.run(housing_request)

    assert map_agent.enrich.call_count == 2
    assert result.cache_hits == []


def test_map_failure_is_not_cached(housing_request):
    from app.core.config import Settings
    from app.agents.map_data_agent import MapDataAgentError

    settings = Settings(
        _env_file=None,
        map_cache_enabled=True,
        workflow_budget_seconds=600,
    )

    candidates = CandidateService().list_candidates("北京")
    cache = MapCacheService(ttl_seconds=60)

    map_agent = Mock()
    map_agent.enrich.side_effect = MapDataAgentError(
        "测试地图查询失败"
    )

    orchestrator = HousingDecisionOrchestrator(
        candidate_service=CandidateService(),
        requirement_agent=FakeRequirementAgent(),
        map_data_agent=map_agent,
        specialist_coordinator=FakeSpecialistCoordinator(),
        decision_agent=FakeDecisionAgent(),
        map_cache=cache,
        settings=settings,
    )

    with pytest.raises(MapDataAgentError):
        orchestrator.run(housing_request)

    key = cache.build_key(housing_request, candidates)

    assert cache.get(key) is None
    assert map_agent.enrich.call_count == 1


def test_budget_error_returns_504(client, valid_payload, monkeypatch):
    from app.main import app
    from app.agents.housing_orchestrator import get_housing_orchestrator
    from app.core.workflow_execution import WorkflowBudgetExceeded

    orchestrator = Mock()

    orchestrator.run.side_effect = WorkflowBudgetExceeded(
        stage="map_enrichment",
        elapsed_ms=610000,
        durations={"map_enrichment": 605000},
    )

    monkeypatch.setitem(
        app.dependency_overrides,
        get_housing_orchestrator,
        lambda: orchestrator,
    )

    response = client.post(
        "/api/workflows/housing-decision",
        json=valid_payload,
    )

    assert response.status_code == 504
    assert response.json()["detail"]["code"] == (
        "workflow_budget_exceeded"
    )

@pytest.mark.parametrize(
    "failed_agent",
    ["commute", "facility"],
)
def test_specialist_failure_stops_final_decision(
    housing_request,
    failed_agent,
):
    """真实协调器中的专家失败后，不应调用决策Agent。"""

    from app.agents.agent_utils import SpecialistAgentError
    from app.agents.specialist_coordinator import SpecialistCoordinator

    candidates = CandidateService().list_candidates("北京")

    # 复用本文件已有的假协调器，生成合法专家结果。
    prepared = FakeSpecialistCoordinator().analyze(
        request=housing_request,
        candidates=candidates,
    )

    commute_agent = Mock()
    commute_agent.analyze.return_value = (
        prepared.commute_analysis
    )

    facility_agent = Mock()
    facility_agent.analyze.return_value = (
        prepared.facility_analysis
    )

    error = SpecialistAgentError("测试专家失败")

    if failed_agent == "commute":
        commute_agent.analyze.side_effect = error
    else:
        facility_agent.analyze.side_effect = error

    # 关闭地图查询，保证自动化测试不调用外部服务。
    orchestrator = make_demo_orchestrator(None)

    # 使用本阶段真正的并发协调器。
    orchestrator.specialist_coordinator = SpecialistCoordinator(
        commute_agent=commute_agent,
        facility_agent=facility_agent,
    )

    decision_agent = Mock()
    orchestrator.decision_agent = decision_agent

    with pytest.raises(SpecialistAgentError) as exc:
        orchestrator.run(housing_request)

    assert exc.value is error
    decision_agent.synthesize.assert_not_called()

    commute_agent.analyze.assert_called_once()
    facility_agent.analyze.assert_called_once()

@pytest.fixture
def completed_history_result(housing_request):
    """用已有假Agent生成结果，不连接外部服务。"""

    from app.core.config import Settings

    orchestrator = make_demo_orchestrator(None)

    # 测试预算不受本地.env临时配置影响。
    orchestrator.settings = Settings(
        _env_file=None,
        workflow_budget_seconds=600,
    )

    return orchestrator.run(housing_request)

def test_history_survives_new_repository_instance(
    history_repository,
    housing_request,
    completed_history_result,
):
    """换一个仓库对象，仍能读取同一数据库文件中的结果。"""

    from app.repositories.decision_history_repository import (
        DecisionHistoryRepository,
    )

    record_id = history_repository.save(
        request=housing_request,
        result=completed_history_result,
    )

    reopened = DecisionHistoryRepository(
        db_path=history_repository.db_path,
    )

    loaded = reopened.get(record_id)

    assert loaded is not None
    assert loaded.id == record_id

    assert loaded.request.model_dump() == (
        housing_request.model_dump()
    )
    assert loaded.result.model_dump() == (
        completed_history_result.model_dump()
    )


def test_history_list_pagination(
    history_repository,
    housing_request,
    completed_history_result,
):
    """分页查询不能丢失或重复这两条记录。"""

    first_id = history_repository.save(
        housing_request,
        completed_history_result,
    )
    second_id = history_repository.save(
        housing_request,
        completed_history_result,
    )

    first_page = history_repository.list_recent(
        limit=1,
        offset=0,
    )
    second_page = history_repository.list_recent(
        limit=1,
        offset=1,
    )

    assert len(first_page) == 1
    assert len(second_page) == 1
    assert first_page[0].id != second_page[0].id

    assert {
        first_page[0].id,
        second_page[0].id,
    } == {first_id, second_id}


def test_workflow_saves_history_and_can_be_queried(
    client,
    valid_payload,
    completed_history_result,
    monkeypatch,
):
    """通过POST保存，再通过GET读取；查询不重新运行工作流。"""

    from app.main import app
    from app.agents.housing_orchestrator import (
        get_housing_orchestrator,
    )

    orchestrator = Mock()
    orchestrator.run.return_value = completed_history_result

    monkeypatch.setitem(
        app.dependency_overrides,
        get_housing_orchestrator,
        lambda: orchestrator,
    )

    response = client.post(
        "/api/workflows/housing-decision",
        json=valid_payload,
    )

    assert response.status_code == 200
    body = response.json()

    assert body["history_id"]
    assert body["history_warning"] is None

    record_id = body["history_id"]

    detail_response = client.get(
        f"/api/history/{record_id}"
    )

    assert detail_response.status_code == 200
    assert detail_response.json()["result"] == body["data"]

    list_response = client.get("/api/history")

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["id"] == record_id

    # 后面的两个GET没有再运行工作流。
    orchestrator.run.assert_called_once()


def test_history_save_failure_keeps_analysis_result(
    client,
    valid_payload,
    completed_history_result,
    monkeypatch,
):
    """分析已成功时，保存失败必须显式提示且不重跑分析。"""

    from app.main import app
    from app.agents.housing_orchestrator import (
        get_housing_orchestrator,
    )
    from app.repositories.decision_history_repository import (
        HistoryStorageError,
        get_decision_history_repository,
    )

    orchestrator = Mock()
    orchestrator.run.return_value = completed_history_result

    repository = Mock()
    repository.save.side_effect = HistoryStorageError(
        "测试存储失败"
    )

    monkeypatch.setitem(
        app.dependency_overrides,
        get_housing_orchestrator,
        lambda: orchestrator,
    )
    monkeypatch.setitem(
        app.dependency_overrides,
        get_decision_history_repository,
        lambda: repository,
    )

    response = client.post(
        "/api/workflows/housing-decision",
        json=valid_payload,
    )

    assert response.status_code == 200
    body = response.json()

    assert body["success"] is True
    assert body["history_id"] is None
    assert "保存失败" in body["history_warning"]
    assert body["data"] == completed_history_result.model_dump(
        mode="json"
    )

    orchestrator.run.assert_called_once()
    repository.save.assert_called_once()


def test_failed_workflow_does_not_save_history(
    client,
    valid_payload,
    history_repository,
    monkeypatch,
):
    """失败的工作流不能生成成功历史记录。"""

    from app.main import app
    from app.agents.agent_utils import SpecialistAgentError
    from app.agents.housing_orchestrator import (
        get_housing_orchestrator,
    )

    orchestrator = Mock()
    orchestrator.run.side_effect = SpecialistAgentError(
        "测试专家失败"
    )

    monkeypatch.setitem(
        app.dependency_overrides,
        get_housing_orchestrator,
        lambda: orchestrator,
    )

    response = client.post(
        "/api/workflows/housing-decision",
        json=valid_payload,
    )

    assert response.status_code == 502
    assert history_repository.list_recent() == []


def test_history_missing_id_returns_404(client):
    from uuid import uuid4

    response = client.get(
        f"/api/history/{uuid4()}"
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "url",
    [
        "/api/history?limit=0",
        "/api/history?limit=101",
        "/api/history?offset=-1",
        "/api/history/not-a-uuid",
    ],
)
def test_history_rejects_invalid_parameters(client, url):
    response = client.get(url)

    assert response.status_code == 422