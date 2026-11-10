"""选址决策API路由。"""
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from app.decision.scoring import evaluate_candidates

from app.models.schemas import (
    CandidateListResponse,
    HousingDecisionRequest,
    HousingDecisionResponse,
)
from app.services.candidate_service import (
    CandidateService,
    get_candidate_service,
)


# prefix表示当前文件中所有接口都以/decision开头。
# main.py稍后还会统一添加/api前缀。
router = APIRouter(
    prefix="/decision",
    tags=["选址决策"],
)


@router.post(
    "/validate",
    response_model=HousingDecisionRequest,
    summary="校验选址需求",
)
def validate_housing_request(
    request: HousingDecisionRequest,
) -> HousingDecisionRequest:
    """校验并返回标准化后的选址需求。"""
    return request


@router.get(
    "/candidates",
    response_model=CandidateListResponse,
    summary="查询候选区域",
)
def list_candidate_areas(
    # 输入参数city必须是长度1~40的字符串。
    city: Annotated[
        str,
        Query(
            min_length=1,
            max_length=40,
            description="需要查询的城市",
        ),
    ],
    candidate_service: CandidateService = Depends(
        get_candidate_service
    ),
) -> CandidateListResponse:
    """查询指定城市的候选区域。

    API路由只负责：

    1. 接收城市参数；
    2. 调用候选区域服务；
    3. 包装响应结果。

    路由本身不保存模拟数据。
    """
    candidates = candidate_service.list_candidates(city)
    message = (
        "候选区域查询成功"
        if candidates
        else f"暂时没有{city.strip()}的候选区域数据"
    )

    return CandidateListResponse(
        success=True,
        message=message,
        data=candidates,
    )

@router.post(
    "/evaluate",
    response_model=HousingDecisionResponse,
    summary="评估候选区域",
)
def evaluate_housing_decision(
    request: HousingDecisionRequest,
    candidate_service: CandidateService = Depends(
        get_candidate_service
    ),
) -> HousingDecisionResponse:
    """根据用户需求评估并排序候选区域。

    路由层只负责协调执行顺序：

    1. 获取候选区域；
    2. 调用评分算法；
    3. 包装API响应。
    """

    # 数据从服务层获取。
    candidates = candidate_service.list_candidates(
        request.city
    )

    # 分数由决策层计算。
    result = evaluate_candidates(
        request=request,
        candidates=candidates,
    )

    # API层负责包装HTTP响应。
    return HousingDecisionResponse(
        success=True,
        message="选址评估完成",
        data=result,
    )
