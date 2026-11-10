"""会话及需求版本的数据模型。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.schemas import HousingDecisionRequest

class CreateConversationRequest(BaseModel):
    """创建会话时，提交第一份完整需求。"""

    model_config = ConfigDict(extra="forbid")

    request: HousingDecisionRequest

class CreateVersionRequest(BaseModel):
    """基于指定版本，提交一份新的完整需求。"""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(
        ge=1,
        strict=True,
    )

    request: HousingDecisionRequest

class BindDecisionRequest(BaseModel):
    """把已经保存的分析历史关联到当前需求版本。"""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(
        ge=1,
        strict=True,
    )

    history_id: UUID

class ConversationVersion(BaseModel):
    """一份需求版本及其关联的决策历史。"""

    session_id: str
    version: int
    created_at: datetime

    request: HousingDecisionRequest

    history_id: str | None = None

class ConversationDetail(BaseModel):
    """会话信息及当前需求版本。"""

    id: str
    created_at: datetime
    updated_at: datetime

    current_version: int

    current: ConversationVersion


class ConversationVersionPage(BaseModel):
    """分页返回需求版本。"""

    items: list[ConversationVersion]
    limit: int
    offset: int