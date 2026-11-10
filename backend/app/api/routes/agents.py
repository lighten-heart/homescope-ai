"""HomeScope AI业务Agent接口。"""
import logging

from app.agents.agent_utils import (
    SpecialistAgentError,
)

from app.agents.specialist_coordinator import (
    SpecialistCoordinator,
    get_specialist_coordinator,
)

from app.services.llm_service import (
    LLMConfigurationError,
)

from app.models.schemas import (
    HousingDecisionRequest,
    MultiAgentSpecialistResponse,
)

from app.services.candidate_service import (
    CandidateService,
    get_candidate_service,
)

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from app.agents.requirement_agent import (
    RequirementAgentError,
    RequirementAnalysisAgent,
    get_requirement_agent,
)
from app.models.schemas import (
    HousingDecisionRequest,
    RequirementAnalysisResponse,
)
from app.services.llm_service import (
    LLMConfigurationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/agents",
    tags=["业务智能体"],
)

@router.post(
    "/requirements",
    response_model=RequirementAnalysisResponse,
    summary="使用Agent分析住房需求",
)
def analyze_housing_requirements(
    request: HousingDecisionRequest,
    agent: RequirementAnalysisAgent = Depends(
        get_requirement_agent
    ),
) -> RequirementAnalysisResponse:
    """功能：把用户输入转换成结构化住房需求。"""
    try:
        result = agent.analyze(request)

    except LLMConfigurationError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=str(exc),
        ) from exc

    except RequirementAgentError as exc:
        logger.warning(
            "需求分析Agent输出无效：%s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception("需求分析Agent调用失败")

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="需求分析Agent调用失败",
        ) from exc

    return RequirementAnalysisResponse(
        success=True,
        message="需求分析完成",
        data=result,
    )

@router.post(
    "/specialists",
    response_model=MultiAgentSpecialistResponse,
    summary="执行专业多Agent分析",
)
def analyze_with_specialists(
    request: HousingDecisionRequest,
    coordinator: SpecialistCoordinator = Depends(
        get_specialist_coordinator
    ),
    candidate_service: CandidateService = Depends(
        get_candidate_service
    ),
) -> MultiAgentSpecialistResponse:
    """使用通勤和配套Agent分析候选区域。"""

    candidates = candidate_service.list_candidates(
        request.city
    )

    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="当前城市没有候选区域数据",
        )

    try:
        result = coordinator.analyze(
            request=request,
            candidates=candidates,
        )

    except LLMConfigurationError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=str(exc),
        ) from exc

    except SpecialistAgentError as exc:
        logger.warning(
            "专业Agent返回结果无效：%s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception("专业多Agent分析失败")

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="专业多Agent分析失败",
        ) from exc

    return MultiAgentSpecialistResponse(
        success=True,
        message="专业Agent分析完成",
        data=result,
    )