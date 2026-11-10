"""Pytest 公共测试配置。
conftest.py 中定义的 fixture，
可以被同一测试目录下的所有测试文件直接使用。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import HousingDecisionRequest

# pytest提供的一个装饰器，把一个普通函数标记成“测试准备函数”，以后测试函数需要它时，pytest会自动先执行这个函数，并把返回值传递进去
@pytest.fixture
def client() -> TestClient:
    """创建 FastAPI 测试客户端。

    TestClient 会直接在内存中调用 FastAPI 应用，
    因此不需要提前运行 Uvicorn。
    """

    return TestClient(app)

@pytest.fixture
def valid_payload() -> dict[str, object]:
    """创建一份合法的 HTTP 请求数据。"""
    return {
        "city": "北京",
        "work_address": "北京市海淀区中关村",
        "monthly_budget": 5000,
        "max_commute_minutes": 45,
        "preferred_facilities": [
            "地铁站",
            "健身房",
        ],
        "preferred_transportation": "公共交通",
        "free_text_input": "希望环境安静，附近最好有公园",
    }

@pytest.fixture
def housing_request(
    valid_payload: dict[str, object],
) -> HousingDecisionRequest:
    """把字典转换成经过 Pydantic 校验的业务模型。"""
    return HousingDecisionRequest.model_validate(
        valid_payload
    )

@pytest.fixture(autouse=True)
def history_repository(tmp_path, monkeypatch):
    """每个测试使用自己的临时数据库。"""

    from app.repositories.decision_history_repository import (
        DecisionHistoryRepository,
        get_decision_history_repository,
    )

    repository = DecisionHistoryRepository(
        db_path=tmp_path / "history.sqlite3",
    )

    monkeypatch.setitem(
        app.dependency_overrides,
        get_decision_history_repository,
        lambda: repository,
    )

    return repository


