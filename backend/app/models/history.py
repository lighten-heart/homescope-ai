"""决策历史的接口数据模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.schemas import (
    HousingDecisionRequest,
    MultiAgentDecisionResult,
)


class DecisionHistorySummary(BaseModel):
    """历史列表中的一条摘要。"""

    id: str
    created_at: datetime
    city: str
    monthly_budget: int
    recommended_candidate_id: str


class DecisionHistoryDetail(DecisionHistorySummary):
    """一条完整历史记录。"""

    # 保存时的数据结构版本。
    schema_version: Literal[1] = 1

    # 用户提交的、经过校验的需求。
    request: HousingDecisionRequest

    # 当次工作流产生的完整结果。
    result: MultiAgentDecisionResult


class DecisionHistoryPage(BaseModel):
    """分页列表；本阶段不计算全部记录总数。"""

    items: list[DecisionHistorySummary]
    limit: int
    offset: int