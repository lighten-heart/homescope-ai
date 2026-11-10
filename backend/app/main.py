"""HomeScope AI后端应用入口。"""

from fastapi import FastAPI

from app.api.routes.history import router as history_router

from app.api.routes.decision import (
    router as decision_router,
)
from app.api.routes.workflow import (
    router as workflow_router,
)
from app.api.routes.llm import router as llm_router
from app.api.routes.agents import router as agents_router
from app.core.config import get_settings

from app.api.routes.conversations import (
    router as conversations_router,
)
# 因为get_settings使用了lru_cache（緩存），所以整个进程共用一个实例。
settings = get_settings()

# 使用獲取的配置创建FastAPI应用实例。
# 后面的"路由"、"中间件"和"异常处理"都会注册到这个app对象。
# FastAPI是一个后端框架，用来开发API接口
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="搬家选址与通勤决策系统API",
    debug=settings.debug,
)

# 注册选址决策路由。
# decision.py只管理选址业务，main.py负责将其组装到应用中。
app.include_router(
    decision_router,
    prefix="/api",
)

# 注册LLM路由。
app.include_router(
    llm_router,
    prefix="/api",
)

# 注册业务智能体路由。
app.include_router(
    agents_router,
    prefix="/api",
)

# 注册完整多Agent工作流路由
app.include_router(
    workflow_router,
    prefix="/api",
)

# 注册决策历史路由
app.include_router(
    history_router,
    prefix="/api",
)

# 注册会话查询路由
app.include_router(
    conversations_router,
    prefix="/api",
)
# 瀏覽器發送GET請求，執行兩種函數
# “GET /”操作會執行root函數
@app.get("/")
def root() -> dict[str, str]:
    """返回当前服务的基本信息。"""

    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
    }

@app.get("/health")
def health() -> dict[str, str]:
    """檢查后端服务能否正常响应。"""

    return {
        "status": "healthy",
        "service": settings.app_name,
        "environment": "development" if settings.debug else "production",
    }