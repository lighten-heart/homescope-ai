"""第十二阶段基础测试，不调用真实模型或地图接口。"""

import pytest

from app.core.ttl_cache import TTLCache
from app.core.workflow_execution import (
    WorkflowBudgetExceeded,
    WorkflowExecution,
)
from app.models.schemas import Location, MapEnrichmentResult
from app.services.candidate_service import CandidateService
from app.services.map_cache_service import MapCacheService


class FakeClock:
    """通过修改now模拟时间流逝，不需要sleep。"""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_ttl_cache_expires():
    clock = FakeClock()

    cache = TTLCache(
        ttl_seconds=10,
        clock=clock,
    )

    cache.set("a", 123)

    assert cache.get("a") == 123

    clock.now = 10

    assert cache.get("a") is None


def test_ttl_cache_has_capacity_limit():
    cache = TTLCache(
        ttl_seconds=60,
        max_entries=2,
    )

    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)

    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3


def test_map_cache_returns_independent_copies():
    cache = MapCacheService(ttl_seconds=60)

    original = MapEnrichmentResult(
        work_location=Location(
            longitude=116.30,
            latitude=39.98,
        ),
        candidates=[],
    )

    cache.set("test-key", original)

    # 修改原对象，不应影响已写入的缓存。
    original.work_location.longitude = 120.0

    first = cache.get("test-key")
    assert first is not None
    assert first.work_location.longitude == 116.30

    # 修改读取结果，也不应污染缓存。
    first.work_location.longitude = 121.0

    second = cache.get("test-key")
    assert second is not None
    assert second.work_location.longitude == 116.30


def test_map_key_matches_query_inputs(housing_request):
    cache = MapCacheService(ttl_seconds=60)
    candidates = CandidateService().list_candidates("北京")

    original_key = cache.build_key(housing_request, candidates)

    # 仅预算变化，不影响当前地图采集输入。
    budget_changed = housing_request.model_copy(
        update={"monthly_budget": 6000}
    )

    assert cache.build_key(
        budget_changed,
        candidates,
    ) == original_key

    # 工作地址变化，必须重新查询。
    address_changed = housing_request.model_copy(
        update={"work_address": "北京市朝阳区望京"}
    )

    assert cache.build_key(
        address_changed,
        candidates,
    ) != original_key

    # 交通方式变化，也不能复用原结果。
    transport_changed = housing_request.model_copy(
        update={"preferred_transportation": "驾车"}
    )

    assert cache.build_key(
        transport_changed,
        candidates,
    ) != original_key


def test_workflow_records_stage_duration():
    clock = FakeClock()

    execution = WorkflowExecution(
        budget_seconds=10,
        clock=clock,
    )

    with execution.measure("test_stage"):
        clock.now = 0.25

    assert execution.stage_durations_ms["test_stage"] == 250.0
    assert execution.elapsed_ms == 250.0


def test_budget_exceeded_after_stage_returns():
    clock = FakeClock()

    execution = WorkflowExecution(
        budget_seconds=1,
        clock=clock,
    )

    with pytest.raises(WorkflowBudgetExceeded) as exc:
        with execution.measure("map_enrichment"):
            clock.now = 2.0

    assert exc.value.stage == "map_enrichment"
    assert exc.value.stage_durations_ms["map_enrichment"] == 2000.0


def test_budget_blocks_starting_another_stage():
    clock = FakeClock()

    execution = WorkflowExecution(
        budget_seconds=1,
        clock=clock,
    )

    clock.now = 2.0
    called = False

    with pytest.raises(WorkflowBudgetExceeded):
        with execution.measure("decision_agent"):
            called = True

    assert called is False