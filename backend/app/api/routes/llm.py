"""LLM状态检查与连通性测试接口。"""
import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from app.core.config import Settings, get_settings
from app.models.schemas import (
    LLMChatRequest,
    LLMChatResponse,
    LLMStatusResponse,
)
from app.services.llm_service import (
    LLMConfigurationError,
    LLMService,
    get_llm_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/llm",
    tags=["大模型"],
)

@router.get(
    "/status",
    response_model=LLMStatusResponse,
    summary="查看LLM配置状态",
)
def get_llm_status(
    settings: Settings = Depends(get_settings),
) -> LLMStatusResponse:
    """检查LLM是否启用以及必要配置是否完整。

    该接口不会真正请求模型，也不会返回API Key。
    """

    configured = all(
        [
            settings.llm_enabled,
            bool(settings.llm_model_id),
            bool(
                settings
                .llm_api_key
                .get_secret_value()
            ),
            bool(settings.llm_base_url),
        ]
    )

    return LLMStatusResponse(
        enabled=settings.llm_enabled,
        configured=configured,
        provider=settings.llm_provider,
        model_id=settings.llm_model_id,
    )

@router.post(
    "/chat",
    response_model=LLMChatResponse,
    summary="测试LLM连接",
)
def chat_with_llm(
    request: LLMChatRequest,
    llm_service: LLMService = Depends(
        get_llm_service
    ),
) -> LLMChatResponse:
    """发送测试消息并返回大模型回答。"""

    try:
        answer = llm_service.chat(request.message)

    except LLMConfigurationError as exc:
        # 配置未启用或缺少字段，属于服务暂时不可用。
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=str(exc),
        ) from exc

    except Exception as exc:
        # 记录完整异常，但不把内部错误和密钥返回给前端。
        logger.exception("调用LLM失败")

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "LLM调用失败，请检查模型名称、"
                "接口地址、API Key和网络连接"
            ),
        ) from exc

    return LLMChatResponse(
        success=True,
        provider=llm_service.settings.llm_provider,
        model_id=llm_service.settings.llm_model_id,
        answer=answer,
    )