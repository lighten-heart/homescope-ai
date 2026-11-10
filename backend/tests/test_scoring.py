"""核心评分算法单元测试。

单元测试直接调用评分函数，
不经过 FastAPI 和 HTTP 层。
"""

import pytest

from app.decision.scoring import (
    DEFAULT_WEIGHTS,
    evaluate_candidates,
)
from app.models.schemas import HousingDecisionRequest
from app.services.candidate_service import CandidateService

def test_default_weights_sum_to_one() -> None:
    """所有评分权重之和必须等于 1。"""
    total_weight = sum(DEFAULT_WEIGHTS.values())
    # 浮点数计算可能存在微小误差，
    # 所以使用 pytest.approx，而不是直接比较。
    assert total_weight == pytest.approx(1.0)

def test_evaluation_scores_and_order(
    housing_request: HousingDecisionRequest,
) -> None:
    """固定输入应该产生稳定的分数和排名。"""
    candidate_service = CandidateService()
    candidates = candidate_service.list_candidates(
        "北京"
    )
    result = evaluate_candidates(
        request=housing_request,
        candidates=candidates,
    )

    candidate_ids = [
        evaluation.candidate.id
        for evaluation in result.evaluations
    ]

    scores = [
        evaluation.total_score
        for evaluation in result.evaluations
    ]

    assert candidate_ids == [
        "beijing-area-a",
        "beijing-area-b",
        "beijing-area-c",
    ]

    assert scores == pytest.approx(
        [
            95.8,
            83.46,
            72.6,
        ]
    )

    assert result.evaluations[0].rank == 1
    best_candidate_name = (
        result.evaluations[0].candidate.name
    )

    assert best_candidate_name in result.recommendation


def test_evaluation_generates_warnings(
    housing_request: HousingDecisionRequest,
) -> None:
    """超预算和超通勤限制时，应生成对应风险提示。"""
    candidates = CandidateService().list_candidates(
        "北京"
    )

    result = evaluate_candidates(
        request=housing_request,
        candidates=candidates,
    )
    area_b = result.evaluations[1]
    area_c = result.evaluations[2]

    # B 区域月租 5200，超过 5000 元预算。
    assert any(
        "超出预算" in warning
        for warning in area_b.warnings
    )

    # C 区域通勤 54 分钟，超过 45 分钟限制。
    assert any(
        "超过限制" in warning
        for warning in area_c.warnings
    )


def test_empty_candidates_returns_empty_result(
    housing_request: HousingDecisionRequest,
) -> None:
    """候选区域为空时，评分算法也应该正常返回。"""

    result = evaluate_candidates(
        request=housing_request,
        candidates=[],
    )

    assert result.evaluations == []
    assert "没有" in result.recommendation
