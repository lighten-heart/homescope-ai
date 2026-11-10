"""应用配置管理模块。"""

from pydantic import Field, SecretStr
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py位于backend/app/core目录。
# parents[0]是core，parents[1]是app，parents[2]是backend。
BACKEND_DIR = Path(__file__).resolve().parents[2]

# 創建一個配置類，BaseSettings用於讀取配置
class Settings(BaseSettings):
    """HomeScope AI应用配置。

    BaseSettings会按照以下顺序寻找配置：

    1. 创建Settings对象时传入的参数
    2. 系统环境变量
    3. backend/.env文件
    4. 这里定义的默认值

    优先级高的配置会覆盖优先级低的配置。
    """

    app_name: str = "HomeScope AI"
    app_version: str = "0.1.0"
    debug: bool = False

    host: str = "127.0.0.1"
    port: int = 8000

    # 是否启用大模型。
    # 默认关闭，确保没有配置API Key时项目也能正常运行和测试。
    llm_enabled: bool = False

    # custom表示使用兼容OpenAI接口规范的自定义模型服务。
    llm_provider: str = "custom"

    # 服务商提供的模型名称。
    llm_model_id: str = ""

    # SecretStr可以防止API Key被意外打印到日志中。
    llm_api_key: SecretStr = SecretStr("")

    # OpenAI兼容接口的基础地址，通常以/v1结尾。
    llm_base_url: str = ""

    # 网络读取等待时间，不是整个工作流/请求的硬总时限。
    # 显式传入SDK，避免HelloAgents读取无前缀的LLM_TIMEOUT环境变量。
    llm_timeout_seconds: int = Field(default=90, ge=1, le=600)

    # 指定配置文件.env的绝对位置，避免从不同目录启动时找不到配置。
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",

        # 所有环境变量必须使用HOMESCOPE_前缀。
        # 例如app_name对应HOMESCOPE_APP_NAME。
        env_prefix="HOMESCOPE_",

        # 忽略.env中暂时还没有定义到Settings里的字段。
        extra="ignore",
    )

    # 是否启用高德地图MCP。
    amap_enabled: bool = False

    # 学习时可显式关闭地图增强，保留原始模拟候选数据。
    # 与amap_enabled不同：后者控制MCP服务配置，关闭它不会自动跳过工作流。
    # 默认仍走真实地图流程；上游出错时绝不自动切换成模拟模式。
    map_enrichment_enabled: bool = True

    # 高德Web服务Key，不能硬编码真实值。
    amap_api_key: SecretStr = SecretStr("")

    # 官方高德MCP的npm包名。
    amap_mcp_package: str = (
        "@amap/amap-maps-mcp-server"
    )

    # 单次Agent调用的等待时间。
    agent_timeout_seconds: int = 90

    # 首次失败后的重试次数。
    agent_retry_attempts: int = 2

    # 第一次重试前等待时间。
    agent_retry_base_delay_seconds: float = 0.5

    # 是否启用地图增强结果缓存。
    map_cache_enabled: bool = True

    # 缓存有效期：默认30分钟。
    map_cache_ttl_seconds: int = Field(
        default=1800,
        ge=1,
    )

    # 单进程最多保存多少组地图结果，防止内存无限增长。
    map_cache_max_entries: int = Field(
        default=128,
        ge=1,
    )

    # 工作流阶段间检查使用的时间预算。
    # 注意：不是强制中断正在执行的模型请求。
    workflow_budget_seconds: float = Field(
        default=600,
        gt=0,
    )

    # 外部服务失败时是否允许降级。
    allow_degraded_mode: bool = True

    # 决策历史数据库。
    # 默认使用backend目录下的data文件夹。
    history_db_path: Path = (
        BACKEND_DIR / "data" / "homescope.sqlite3"
    )

# 給函數增加緩存
@lru_cache
def get_settings() -> Settings:
    """获取应用配置。

    lru_cache会缓存第一次创建的Settings对象，
    避免每次HTTP请求都重新读取.env文件。
    """

    # 返回settings对象，里面包含了所有配置字段的值。
    return Settings()

