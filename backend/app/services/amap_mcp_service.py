"""高德地图MCP服务。

负责：

1. 验证高德配置；
2. 启动官方高德MCP Server；
3. 创建共享MCPTool；
4. 将高德Key安全传给子进程。
"""

import os
from functools import lru_cache

from hello_agents.tools import MCPTool

from app.core.config import Settings, get_settings

class AmapConfigurationError(RuntimeError):
    """高德地图配置缺失或未启用。"""

class AmapMCPService:
    """统一管理高德地图MCP工具。"""
    def __init__(
        self,
        settings: Settings,
    ) -> None:
        self.settings = settings
        self._tool: MCPTool | None = None

    def _validate_configuration(self) -> None:
        """检查高德地图配置。"""

        if not self.settings.amap_enabled:
            raise AmapConfigurationError(
                "高德地图MCP尚未启用，请设置"
                "HOMESCOPE_AMAP_ENABLED=true"
            )
        if not (
            self.settings
            .amap_api_key
            .get_secret_value()
        ):
            raise AmapConfigurationError(
                "缺少HOMESCOPE_AMAP_API_KEY"
            )

    def _build_server_command(self) -> list[str]:
        """根据操作系统创建MCP启动命令。"""

        package_name = (
            self.settings.amap_mcp_package
        )

        if os.name == "nt":
            # Windows中的npx通常是npx.cmd，
            # 通过cmd /c启动兼容性更好。
            return [
                "cmd",
                "/c",
                "npx",
                "-y",
                package_name,
            ]

        return [
            "npx",
            "-y",
            package_name,
        ]

    def check_key_platform(self, address: str, city: str) -> None:
        """用实际地理编码请求检查 Key 平台，而非只检查 MCP 能否连接。

        MCPTool 会把查询异常转换成字符串，LLM 可能继续生成无效坐标。
        因此在调用地图 Agent 前，确定性地拦截已知的平台配置错误。
        此检查只针对平台不匹配，不代表其他地图功能一定可用。
        每次调用会额外执行一次地理编码请求；不缓存以免掩盖配置变化。
        """
        response = self.tool.run({
            "action": "call_tool",
            "tool_name": "maps_geo",
            "arguments": {"address": address, "city": city},
        })
        if "USERKEY_PLAT_NOMATCH" in str(response):
            # 不透传原始响应，避免请求 URL 或密钥进入 HTTP 响应和日志。
            raise AmapConfigurationError(
                "高德 Key 平台不匹配（USERKEY_PLAT_NOMATCH）："
                "请在高德控制台创建服务平台为 Web服务 的 Key，"
                "更新 HOMESCOPE_AMAP_API_KEY 后重启后端。"
            )

    @property
    def tool(self) -> MCPTool:
        """延迟创建高德MCPTool。"""

        if self._tool is None:
            self._validate_configuration()

            self._tool = MCPTool(
                name="amap",
                description=(
                    "高德地图位置、路线和POI服务"
                ),
                server_command=(
                    self._build_server_command()
                ),
                env={
                    "AMAP_MAPS_API_KEY": (
                        self.settings
                        .amap_api_key
                        .get_secret_value()
                    )
                },
                auto_expand=True,
            )

        return self._tool

@lru_cache
def get_amap_mcp_service() -> AmapMCPService:
    """返回应用共享的高德MCP服务。"""

    return AmapMCPService(
        settings=get_settings()
    )

def reset_amap_mcp_service() -> None:
    """清理高德MCP服务缓存。"""

    get_amap_mcp_service.cache_clear()
