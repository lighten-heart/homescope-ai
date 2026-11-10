"""HomeScope AI 接口集成测试。

这里通过 HTTP 请求测试完整调用链：

请求
→ FastAPI 路由
→ Pydantic 校验
→ Service 服务
→ 评分算法
→ HTTP 响应
"""

from fastapi.testclient import TestClient
from app.agents.requirement_agent import (
    get_requirement_agent,
)
from app.main import app
from app.models.schemas import RequirementAnalysis

def test_health_check(
    client: TestClient,
) -> None:
    """健康检查接口应正常响应。"""
    response = client.get("/health")
    # Assert：验证实际结果。
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_validate_normalizes_input(
    client: TestClient,
    valid_payload: dict[str, object],
) -> None:
    """参数校验接口应清理空格、空值和重复设施。"""
    valid_payload["city"] = "  北京  "
    valid_payload["preferred_facilities"] = [
        " 地铁站 ",
        "",
        "地铁站",
        " 健身房 ",
    ]
    response = client.post(
        "/api/decision/validate",
        json=valid_payload,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["city"] == "北京"
    assert body["preferred_facilities"] == [
        "地铁站",
        "健身房",
    ]

def test_validate_rejects_invalid_budget(
    client: TestClient,
    valid_payload: dict[str, object],
) -> None:
    """预算低于 500 元时，Pydantic 应拒绝请求。"""
    valid_payload["monthly_budget"] = 499
    response = client.post(
        "/api/decision/validate",
        json=valid_payload,
    )
    assert response.status_code == 422

def test_list_beijing_candidates(
    client: TestClient,
) -> None:
    """北京应该返回三个模拟候选区域。"""
    response = client.get(
        "/api/decision/candidates",
        params={"city": "北京"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert len(body["data"]) == 3
    assert body["data"][0]["id"] == "beijing-area-a"
    assert body["data"][0]["data_source"] == "mock"

def test_evaluate_returns_ranked_candidates(
    client: TestClient,
    valid_payload: dict[str, object],
) -> None:
    """评估接口应按综合得分从高到低返回候选区域。"""
    response = client.post(
        "/api/decision/evaluate",
        json=valid_payload,
    )
    assert response.status_code == 200

    body = response.json()
    evaluations = body["data"]["evaluations"]

    scores = [
        item["total_score"]
        for item in evaluations
    ]

    ranks = [
        item["rank"]
        for item in evaluations
    ]

    assert body["success"] is True
    assert len(evaluations) == 3

    # sorted(..., reverse=True) 会生成降序排列的新列表。
    assert scores == sorted(scores, reverse=True)

    assert ranks == [1, 2, 3]

    assert (
        evaluations[0]["candidate"]["id"]
        == "beijing-area-a"
    )

def test_evaluate_unknown_city_returns_empty_result(
    client: TestClient,
    valid_payload: dict[str, object],
) -> None:
    """没有模拟数据的城市应返回空结果，而不是系统错误。"""

    valid_payload["city"] = "上海"
    response = client.post(
        "/api/decision/evaluate",
        json=valid_payload,
    )
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["evaluations"] == []
    assert "没有" in result["recommendation"]

def test_llm_status_does_not_expose_api_key(
    client: TestClient,
) -> None:
    """LLM状态接口不能泄露API Key。"""

    response = client.get("/api/llm/status")

    assert response.status_code == 200

    body = response.json()

    assert "enabled" in body
    assert "configured" in body
    assert "provider" in body
    assert "model_id" in body

    # 响应中绝对不能出现密钥字段。
    assert "api_key" not in body

class FakeRequirementAgent:
    """测试专用假Agent，不会调用真实LLM。"""

    def analyze(self, request):
        """返回固定的需求分析结果。"""

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
                + ["公园"]
            ),
            lifestyle_tags=["安静"],
            hard_constraints=[
                f"月租不超过{request.monthly_budget}元",
                (
                    "通勤不超过"
                    f"{request.max_commute_minutes}分钟"
                ),
            ],
            soft_preferences=[
                "环境安静",
                "靠近公园",
            ],
            clarification_questions=[],
            summary="用户希望寻找通勤方便且安静的区域",
        )


def test_analyze_requirements_with_fake_agent(
    client: TestClient,
    valid_payload: dict[str, object],
) -> None:
    """需求分析接口应返回结构化结果。"""

    # 临时把真实Agent替换成假Agent。
    app.dependency_overrides[
        get_requirement_agent
    ] = lambda: FakeRequirementAgent()

    try:
        response = client.post(
            "/api/agents/requirements",
            json=valid_payload,
        )

        assert response.status_code == 200

        body = response.json()

        assert body["success"] is True
        assert body["data"]["city"] == "北京"
        assert "安静" in body["data"]["lifestyle_tags"]
        assert (
            "公园"
            in body["data"]["optional_facilities"]
        )

    finally:
        # 测试结束后必须恢复原来的依赖。
        app.dependency_overrides.pop(
            get_requirement_agent,
            None,
        )

