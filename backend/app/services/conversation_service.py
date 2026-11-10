"""会话业务入口。"""
"""服务层负责读取历史仓库、确认历史存在、交给会话仓库检查需求和版本、关联结果"""

from app.models.conversation import (
    ConversationDetail,
    ConversationVersionPage,
)
from app.models.schemas import HousingDecisionRequest

from app.repositories.conversation_repository import (
    ConversationRepository,
)
from app.repositories.decision_history_repository import (
    DecisionHistoryRepository,
)

class DecisionHistoryNotFoundError(RuntimeError):
    """要关联的分析历史不存在。"""


class ConversationService:
    def __init__(
        self,
        repository: ConversationRepository,
        history_repository: DecisionHistoryRepository,
    ) -> None:
        self.repository = repository
        self.history_repository = history_repository

    def create(
        self,
        request: HousingDecisionRequest,
    ) -> ConversationDetail:
        return self.repository.create(request)

    def get(
        self,
        session_id: str,
    ) -> ConversationDetail:
        return self.repository.get(session_id)

    def create_version(
        self,
        session_id: str,
        expected_version: int,
        request: HousingDecisionRequest,
    ) -> ConversationDetail:
        return self.repository.create_version(
            session_id=session_id,
            expected_version=expected_version,
            request=request,
        )

    def list_versions(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
    ) -> ConversationVersionPage:
        items = self.repository.list_versions(
            session_id,
            limit=limit,
            offset=offset,
        )

        return ConversationVersionPage(
            items=items,
            limit=limit,
            offset=offset,
        )

    def bind_decision(
        self,
        session_id: str,
        expected_version: int,
        history_id: str,
    ) -> ConversationDetail:
        history = self.history_repository.get(
            history_id
        )

        if history is None:
            raise DecisionHistoryNotFoundError(
                "分析历史不存在"
            )

        return self.repository.bind_decision(
            session_id=session_id,
            expected_version=expected_version,
            history=history,
        )
