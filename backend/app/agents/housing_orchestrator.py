"""HomeScope AI完整多Agent工作流编排器。"""

from functools import lru_cache

from app.core.workflow_execution import WorkflowExecution

from app.core.config import Settings, get_settings
from app.core.resilience import (
    AsyncAgentRunner,
    get_async_agent_runner,
)
# fallback_service尚未实现，当前同步流程也未使用它，不提前导入空模块中的函数。
from app.services.map_cache_service import (
    MapCacheService,
    get_map_cache_service,
)
from app.models.schemas import (
    HousingDecisionRequest,
    MapEnrichmentResult,
    MultiAgentDecisionResult,
)
from app.agents.decision_agent import (
    DecisionSynthesisAgent,
    get_decision_agent,
)
from app.agents.requirement_agent import (
    RequirementAnalysisAgent,
    get_requirement_agent,
)
from app.agents.specialist_coordinator import (
    SpecialistCoordinator,
    get_specialist_coordinator,
)
from app.decision.scoring import evaluate_candidates
from app.models.schemas import (
    HousingDecisionRequest,
    MultiAgentDecisionResult,
)
from app.services.candidate_service import (
    CandidateService,
    get_candidate_service,
)
from app.agents.map_data_agent import (
    MapDataAgent,
    MapDataAgentError,
    get_map_data_agent,
)
from app.services.candidate_enrichment_service import (
    apply_map_enrichment,
)

class NoCandidateAreasError(RuntimeError):
    """当前城市没有候选区域。"""

class HousingDecisionOrchestrator:
    """协调完整的多Agent选址工作流。"""

    def __init__(
        self,
        candidate_service: CandidateService,
        requirement_agent: RequirementAnalysisAgent,
        map_data_agent: MapDataAgent | None,
        specialist_coordinator: SpecialistCoordinator,
        decision_agent: DecisionSynthesisAgent,
        map_enrichment_enabled: bool = True,
        *,
        runner: AsyncAgentRunner | None = None,
        map_cache: MapCacheService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.candidate_service = candidate_service
        self.requirement_agent = requirement_agent
        self.map_data_agent = map_data_agent
        self.specialist_coordinator = (
            specialist_coordinator
        )
        self.decision_agent = decision_agent
        self.map_enrichment_enabled = map_enrichment_enabled
        # 兼容已有构造调用；新增依赖只能按名称传入，缺省时使用共享实例。
        # 这里只准备依赖，不改变run中的同步执行方式，也不启用重试或降级。
        self.runner = runner if runner is not None else get_async_agent_runner()
        self.map_cache = map_cache if map_cache is not None else get_map_cache_service()
        self.settings = settings if settings is not None else get_settings()

    def _load_map_enrichment(
        self,
        request: HousingDecisionRequest,
        candidates,
        cache_hits: list[str],
    ) -> MapEnrichmentResult:
        """先读缓存，未命中时才调用真实地图Agent。"""

        if self.map_data_agent is None:
            raise RuntimeError("地图增强已启用，但没有配置地图Agent")

        cache_enabled = self.settings.map_cache_enabled
        # 生成缓存键
        cache_key = self.map_cache.build_key(request, candidates)

        result = None

        # 开启缓存时，先尝试读取
        if cache_enabled:
            result = self.map_cache.get(cache_key)

        from_cache = result is not None

        if result is None:
            # 这里抛出的异常向上传递。
            # 不缓存失败，不自动改用模拟数据。
            result = self.map_data_agent.enrich(
                request=request,
                candidates=candidates,
            )

        # 命中缓存也不能跳过候选ID校验。
        expected_ids = {candidate.id for candidate in candidates}
        actual_ids = [
            item.candidate_id
            for item in result.candidates
        ]

        if (
            len(actual_ids) != len(set(actual_ids))
            or set(actual_ids) != expected_ids
        ):
            raise MapDataAgentError(
                "地图增强结果的候选区域与输入不一致"
            )

        if from_cache:
            cache_hits.append("map_enrichment")

        elif cache_enabled:
            # 只在地图Agent成功返回且候选ID校验通过后写入。
            self.map_cache.set(cache_key, result)

        return result
    
    def run(
        self,
        request: HousingDecisionRequest,
    ) -> MultiAgentDecisionResult:
        """执行带地图缓存、计时和预算检查的同步工作流。"""

        execution = WorkflowExecution(
            budget_seconds=self.settings.workflow_budget_seconds,
        )

        pipeline_trace: list[str] = []
        cache_hits: list[str] = []

        # 1. 获取候选区域。
        with execution.measure("candidate_service"):
            candidates = self.candidate_service.list_candidates(
                request.city
            )

            if not candidates:
                raise NoCandidateAreasError(
                    f"当前没有{request.city}的候选区域数据"
                )

        pipeline_trace.append("candidate_service_completed")

        # 2. 理解用户需求。此阶段不缓存。
        with execution.measure("requirement_agent"):
            requirement_analysis = self.requirement_agent.analyze(
                request
            )

        pipeline_trace.append("requirement_agent_completed")

        # 3. 获取地图增强数据：缓存或真实查询。
        map_enrichment = None

        if self.map_enrichment_enabled:
            with execution.measure("map_enrichment"):
                map_enrichment = self._load_map_enrichment(
                    request=request,
                    candidates=candidates,
                    cache_hits=cache_hits,
                )

                candidates = apply_map_enrichment(
                    candidates=candidates,
                    enrichment=map_enrichment,
                )

            if "map_enrichment" in cache_hits:
                pipeline_trace.append("map_cache_hit")
            else:
                pipeline_trace.append("map_data_agent_completed")

        else:
            pipeline_trace.append(
                "map_data_agent_skipped_demo_mode"
            )

        # 4. 专业分析。
        # 协调器内部并发执行两个同步专家；这里等待汇总结果。
        with execution.measure("specialist_agents"):
            specialist_analysis = self.specialist_coordinator.analyze(
                request=request,
                candidates=candidates,
                requirements=requirement_analysis,
            )

        pipeline_trace.append("specialist_agents_completed")

        # 5. 确定性评分。
        with execution.measure("deterministic_scoring"):
            scoring_result = evaluate_candidates(
                request=request,
                candidates=candidates,
            )

        demo_warning = (
            "学习模式：已跳过真实地图增强，"
            "通勤和设施来自模拟候选数据，"
            "仅用于功能演示，不能作为实际租房依据。"
        )

        if not self.map_enrichment_enabled:
            scoring_result.disclaimer = demo_warning

        pipeline_trace.append("deterministic_scoring_completed")

        # 6. 综合解释。
        with execution.measure("decision_agent"):
            narrative = self.decision_agent.synthesize(
                request=request,
                requirements=requirement_analysis,
                specialist_analysis=specialist_analysis,
                scoring_result=scoring_result,
            )

        if not self.map_enrichment_enabled:
            narrative.overall_risks.append(demo_warning)

        if "map_enrichment" in cache_hits:
            narrative.overall_risks.append(
                "地图数据来自有效期内的缓存，"
                "不代表本次请求时实时重新查询；"
                "实际路线和设施情况请以最新信息为准。"
            )

        pipeline_trace.append("decision_agent_completed")

        execution.checkpoint("response")

        return MultiAgentDecisionResult(
            recommended_candidate_id=(
                scoring_result.evaluations[0].candidate.id
            ),
            requirement_analysis=requirement_analysis,
            specialist_analysis=specialist_analysis,
            scoring_result=scoring_result,
            narrative=narrative,
            map_enrichment=map_enrichment,
            pipeline_trace=pipeline_trace,
            stage_durations_ms=execution.stage_durations_ms,
            total_duration_ms=execution.elapsed_ms,
            cache_hits=cache_hits,
        )

@lru_cache
def get_housing_orchestrator(
) -> HousingDecisionOrchestrator:
    """返回完整工作流编排器。"""

    settings = get_settings()
    return HousingDecisionOrchestrator(
        candidate_service=get_candidate_service(),
        requirement_agent=get_requirement_agent(),
        map_data_agent=(
            get_map_data_agent()
            if settings.map_enrichment_enabled
            else None
        ),
        map_enrichment_enabled=settings.map_enrichment_enabled,
        specialist_coordinator=(
            get_specialist_coordinator()
        ),
        decision_agent=get_decision_agent(),
        runner=get_async_agent_runner(),
        map_cache=get_map_cache_service(),
        settings=settings,
    )

