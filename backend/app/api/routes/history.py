"""决策历史查询接口。"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.history import (
    DecisionHistoryDetail,
    DecisionHistoryPage,
)
from app.repositories.decision_history_repository import (
    DecisionHistoryRepository,
    HistoryStorageError,
    get_decision_history_repository,
)

router = APIRouter(
    prefix="/history",
    tags=["决策历史"],
)

@router.get(
    "",
    response_model=DecisionHistoryPage,
    summary="分页查询决策历史",
)
def list_decision_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    repository: DecisionHistoryRepository = Depends(
        get_decision_history_repository
    ),
) -> DecisionHistoryPage:
    """按保存时间从新到旧分页查询历史摘要。"""
    try:
        items = repository.list_recent(
            limit=limit,
            offset=offset,
        )

    except HistoryStorageError as exc:
        raise HTTPException(
            status_code=503,
            detail="历史记录暂时不可读取",
        ) from exc

    return DecisionHistoryPage(
        items=items,
        limit=limit,
        offset=offset,
    )

@router.get(
    "/{record_id}",
    response_model=DecisionHistoryDetail,
    summary="查询一条决策历史详情",
)
def get_decision_history(
    record_id: UUID,
    repository: DecisionHistoryRepository = Depends(
        get_decision_history_repository
    ),
) -> DecisionHistoryDetail:
    try:
        record = repository.get(str(record_id))

    except HistoryStorageError as exc:
        raise HTTPException(
            status_code=503,
            detail="历史记录暂时不可读取",
        ) from exc

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="历史记录不存在",
        )

    return record