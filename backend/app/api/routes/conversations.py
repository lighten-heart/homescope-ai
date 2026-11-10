"""会话创建、需求版本和结果关联接口。"""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from app.models.conversation import (
    BindDecisionRequest,
    ConversationDetail,
    ConversationVersionPage,
    CreateConversationRequest,
    CreateVersionRequest,
)

from app.repositories.conversation_repository import (
    ConversationConflictError,
    ConversationNotFoundError,
    ConversationRepository,
    ConversationStorageError,
)

from app.repositories.decision_history_repository import (
    DecisionHistoryRepository,
    HistoryStorageError,
    get_decision_history_repository,
)

from app.services.conversation_service import (
    ConversationService,
    DecisionHistoryNotFoundError,
)

router = APIRouter(
    prefix="/conversations",
    tags=["会话与版本"],
)
# 准备业务服务及其依赖
def get_conversation_service(
    history: DecisionHistoryRepository = Depends(
        get_decision_history_repository
    ),
) -> ConversationService:
    # 创建会话仓库
    repository = ConversationRepository(
        db_path=history.db_path
    )

    # 把两个仓库交给会话服务
    return ConversationService(
        repository=repository,
        history_repository=history,
    )


@contextmanager
# 把业务异常翻译成HTTP错误
def conversation_errors() -> Iterator[None]:
    """统一将业务异常转换为HTTP错误。"""

    try:
        yield

    except (
        ConversationNotFoundError,
        DecisionHistoryNotFoundError,
    ) as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ConversationConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except (
        ConversationStorageError,
        HistoryStorageError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail="会话数据暂时不可读取或保存",
        ) from exc

# 创建会话接口
@router.post(
    "",
    response_model=ConversationDetail,
    status_code=201,
    summary="创建选址会话",
)
def create_conversation(
    payload: CreateConversationRequest,
    service: ConversationService = Depends(
        get_conversation_service
    ),
) -> ConversationDetail:
    with conversation_errors():
        return service.create(payload.request)

# 读取当前会话接口
@router.get(
    "/{session_id}",
    response_model=ConversationDetail,
    summary="读取当前会话",
)
def get_conversation(
    session_id: UUID,
    service: ConversationService = Depends(
        get_conversation_service
    ),
) -> ConversationDetail:
    with conversation_errors():
        return service.get(str(session_id))

# 创建下一版需求接口
@router.post(
    "/{session_id}/versions",
    response_model=ConversationDetail,
    status_code=201,
    summary="创建下一版完整需求",
)
def create_conversation_version(
    session_id: UUID,
    payload: CreateVersionRequest,
    service: ConversationService = Depends(
        get_conversation_service
    ),
) -> ConversationDetail:
    with conversation_errors():
        return service.create_version(
            session_id=str(session_id),
            expected_version=payload.expected_version,
            request=payload.request,
        )


@router.get(
    "/{session_id}/versions",
    response_model=ConversationVersionPage,
    summary="分页查询需求版本",
)

# 分页查询版本接口
def list_conversation_versions(
    session_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: ConversationService = Depends(
        get_conversation_service
    ),
) -> ConversationVersionPage:
    with conversation_errors():
        return service.list_versions(
            session_id=str(session_id),
            limit=limit,
            offset=offset,
        )

@router.post(
    "/{session_id}/decision",
    response_model=ConversationDetail,
    summary="关联当前版本的分析历史",
)

# 关联当前版本的分析历史
def bind_conversation_decision(
    session_id: UUID,
    payload: BindDecisionRequest,
    service: ConversationService = Depends(
        get_conversation_service
    ),
) -> ConversationDetail:
    with conversation_errors():
        return service.bind_decision(
            session_id=str(session_id),
            expected_version=payload.expected_version,
            history_id=str(payload.history_id),
        )