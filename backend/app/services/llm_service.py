"""统一大语言模型服务。

该模块负责：

1. 检查LLM配置；
2. 创建并缓存HelloAgentsLLM客户端(模型实例)；
3. 为上层Agent提供统一模型实例；
4. 提供一个最小聊天方法用于连通性验证。

"""

from functools import lru_cache

from hello_agents import HelloAgentsLLM, SimpleAgent
import httpx
from openai import OpenAI

from app.core.config import Settings, get_settings
from threading import Lock

class LLMConfigurationError(RuntimeError):
    """LLM配置缺失或未启用时抛出的异常。"""


class ControlledHelloAgentsLLM(HelloAgentsLLM):
    """适配已安装的HelloAgents：其构造函数未向SDK透传max_retries。

    只重写客户端创建，保留invoke和Agent协议，不修改site-packages。
    关闭SDK自动重试，避免一次长请求在用户不知情时重复发送。
    网络读取超时限制两次数据接收之间的等待，不保证墙钟总耗时。
    """

    def _create_client(self):
        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=httpx.Timeout(
                float(self.timeout), connect=10.0, write=30.0, pool=10.0,
            ),
            max_retries=0,
        )

class LLMService:
    """统一管理HelloAgents模型客户端。"""
    def __init__(self, settings: Settings) -> None:
        """保存配置，但暂时不连接模型。

        这种方式叫作延迟初始化：

        只有真正调用大模型时，
        才创建HelloAgentsLLM对象。

        因此即使用户没有配置API Key，
        FastAPI仍然可以正常启动，
        原有自动化测试也可以正常运行。
        """
        self.settings = settings
        self._client: HelloAgentsLLM | None = None
        self._client_lock = Lock()

    def _validate_configuration(self) -> None:
        """检查调用大模型所需的配置是否完整。"""
        if not self.settings.llm_enabled:
            raise LLMConfigurationError(
                "LLM尚未启用，请设置"
                "HOMESCOPE_LLM_ENABLED=true"
            )
        missing_fields: list[str] = []

        if not self.settings.llm_model_id:
            missing_fields.append(
                "HOMESCOPE_LLM_MODEL_ID"
            )
        if not self.settings.llm_api_key.get_secret_value():
            missing_fields.append(
                "HOMESCOPE_LLM_API_KEY"
            )

        if not self.settings.llm_base_url:
            missing_fields.append(
                "HOMESCOPE_LLM_BASE_URL"
            )

        if missing_fields:
            field_names = ", ".join(missing_fields)

            raise LLMConfigurationError(
                f"缺少LLM配置：{field_names}"
            )

    @property
    def client(self) -> HelloAgentsLLM:
        """并发访问时，只初始化一次客户端。"""

        # 同一时间只允许一个线程执行锁内部的代码。 
        # 这把锁仅解决“重复客户端初始化”问题，不会把整个专家分析变成串行
        with self._client_lock:
            if self._client is None:
                self._validate_configuration()

                self._client = ControlledHelloAgentsLLM(
                    provider=self.settings.llm_provider,
                    model=self.settings.llm_model_id,
                    api_key=(
                        self.settings
                        .llm_api_key
                        .get_secret_value()
                    ),
                    base_url=self.settings.llm_base_url,
                    timeout=self.settings.llm_timeout_seconds,
                )

            return self._client

    def chat(self, message: str) -> str:
        """发送一条最小聊天请求。"""

        # 最简单的聊天测试agent
        test_agent = SimpleAgent(
            name="LLM连接测试助手",
            llm=self.client,
            system_prompt=(
                "你是HomeScope AI的连接测试助手。"
                "请使用简体中文简洁回答用户问题。"
            ),
        )
        answer = test_agent.run(message)
        return str(answer).strip()

@lru_cache
def get_llm_service() -> LLMService:
    """返回整个应用共享的LLMService实例。"""

    return LLMService(settings=get_settings())

def reset_llm_service() -> None:
    """清除LLM服务缓存。

    主要用于自动化测试或运行时重新加载配置。
    """

    get_llm_service.cache_clear()
