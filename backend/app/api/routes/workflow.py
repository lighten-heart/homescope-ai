"""完整多Agent工作流API。"""

import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from app.agents.agent_utils import (
    SpecialistAgentError,
)
from app.agents.decision_agent import (
    DecisionAgentError,
)
from app.agents.housing_orchestrator import (
    HousingDecisionOrchestrator,
    NoCandidateAreasError,
    get_housing_orchestrator,
)
from app.agents.requirement_agent import (
    RequirementAgentError,
)
from app.models.schemas import (
    HousingDecisionRequest,
    MultiAgentDecisionResponse,
)
from app.services.llm_service import (
    LLMConfigurationError,
)
from app.services.llm_errors import LLMUpstreamError
from app.agents.map_data_agent import (
    MapDataAgentError,
)
from app.services.amap_mcp_service import (
    AmapConfigurationError,
)
from app.core.workflow_execution import WorkflowBudgetExceeded
from app.repositories.decision_history_repository import (
    DecisionHistoryRepository,
    HistoryStorageError,
    get_decision_history_repository,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workflows",
    tags=["多Agent工作流"],
)

@router.post(
    "/housing-decision",
    response_model=MultiAgentDecisionResponse,
    summary="执行完整多Agent选址决策",
)
def run_housing_decision_workflow(
    request: HousingDecisionRequest,
    orchestrator: HousingDecisionOrchestrator = Depends(
        get_housing_orchestrator
    ),
    history: DecisionHistoryRepository = Depends(
        get_decision_history_repository
    ),
) -> MultiAgentDecisionResponse:
    """执行需求理解、专业分析、评分和决策解释。"""
    
    try:
        # HomeScope AI完整多Agent工作流编排器完成完整分析任务
        result = orchestrator.run(request)

    except NoCandidateAreasError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except (
        LLMConfigurationError,
        AmapConfigurationError,
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=str(exc),
        ) from exc

    except LLMUpstreamError as exc:
        # 只记录经过筛选的字段，不将上游响应或异常链打印到日志。
        logger.warning(
            "模型上游调用失败：stage=%s code=%s request_id=%s diagnostics=%s",
            exc.stage,
            exc.code,
            exc.request_id,
            exc.diagnostics,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.as_detail(),
        ) from exc

    except (
        RequirementAgentError,
        MapDataAgentError,
        SpecialistAgentError,
        DecisionAgentError,
    ) as exc:
        logger.warning(
            "Agent结构化输出无效：%s",
            exc,
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    except WorkflowBudgetExceeded as exc:
        logger.warning(
            "工作流预算超限 stage=%s elapsed_ms=%.2f",
            exc.stage,
            exc.elapsed_ms,
        )

        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": "workflow_budget_exceeded",
                "message": (
                    "工作流在阶段边界发现已超出时间预算，"
                    "已停止后续执行，未自动重试。"
                ),
                "stage": exc.stage,
                "elapsed_ms": exc.elapsed_ms,
                "stage_durations_ms": exc.stage_durations_ms,
            },
        ) from exc
    
    except Exception as exc:
        logger.exception("多Agent工作流执行失败")

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail="多Agent工作流执行失败",
        ) from exc

    # 只有工作流成功后才保存；存储失败不重新执行模型分析。
    history_id = None
    history_warning = None

    try:
        history_id = history.save(
            request=request,
            result=result,
        )
    except HistoryStorageError:
        logger.warning("decision_history_save_failed")
        history_warning = (
            "本次分析已完成，但历史记录保存失败。"
            "请保留当前响应，不要仅为保存历史而重复提交分析。"
        )

    return MultiAgentDecisionResponse(
        success=True,
        message=(
            "学习模式决策完成：已跳过真实地图增强，使用模拟地图数据"
            if result.map_enrichment is None
            else "多Agent选址决策完成"
        ),
        data=result,
        history_id=history_id,
        history_warning=history_warning,
    )
