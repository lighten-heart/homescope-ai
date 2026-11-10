"""地图调用链脱敏诊断；路线结果另做几何字段精简，不记录正文。"""

import logging
from time import monotonic
from uuid import uuid4

from hello_agents.tools.base import Tool
from app.services.map_payload import compact_route_result
from app.services.map_tool_evidence import tool_result_metadata

logger = logging.getLogger(__name__)

# 只记录已知工具标识，避免模型/外部工具名称夹带任意内容。
KNOWN_TOOLS = {
    "amap_maps_geo", "amap_maps_regeocode", "amap_maps_ip_location",
    "amap_maps_weather", "amap_maps_search_detail", "amap_maps_bicycling",
    "amap_maps_direction_walking", "amap_maps_direction_driving",
    "amap_maps_direction_transit_integrated", "amap_maps_distance",
    "amap_maps_text_search", "amap_maps_around_search",
}


class MapCallTrace:
    """每次enrich创建独立实例，不能挂到共享单例上，防止并发请求串线。"""

    def __init__(self):
        self.trace_id = uuid4().hex
        self.rounds = []
        self.tools = []

    def snapshot(self):
        return {
            "trace_id": self.trace_id,
            "llm_round": len(self.rounds),
            "rounds": [dict(item) for item in self.rounds],
            "tool_calls": [dict(item) for item in self.tools],
        }


class TracedLLM:
    """代理原模型，不重试、不删减消息、不修改模型参数。"""

    def __init__(self, client, trace):
        self.client = client
        self.trace = trace

    def __getattr__(self, name):
        return getattr(self.client, name)

    def invoke(self, messages, **kwargs):
        event = {
            "round": len(self.trace.rounds) + 1,
            "message_count": len(messages),
            "input_chars": sum(len(str(m.get("content", ""))) for m in messages),
            "tools_completed_before": len(self.trace.tools),
            "status": "started",
        }
        self.trace.rounds.append(event)
        started = monotonic()
        try:
            result = self.client.invoke(messages, **kwargs)
        except Exception:
            event["status"] = "failed"
            raise
        else:
            event["status"] = "returned"
            event["output_chars"] = len(str(result))
            return result
        finally:
            event["elapsed_ms"] = round((monotonic() - started) * 1000)
            logger.info("map_llm trace_id=%s event=%s", self.trace.trace_id, event)


class TracedMapTool(Tool):
    """保持参数定义；路线结果只去除绘图字段，状态不代表业务数据有效。"""

    def __init__(self, tool, trace):
        super().__init__(name=tool.name, description=tool.description)
        self.tool = tool
        self.trace = trace

    def get_parameters(self):
        return self.tool.get_parameters()

    def run(self, parameters):
        started = monotonic()
        event = {
            "after_llm_round": len(self.trace.rounds),
            "tool": self.name if self.name in KNOWN_TOOLS else "unknown_tool",
            "status": "started",
        }
        try:
            result = self.tool.run(parameters)
        except Exception:
            event["status"] = "exception"
            raise
        else:
            text = str(result)
            # MCPTool会把异常变成字符串。只识别其错误前缀，不记录错误正文。
            event.update(tool_result_metadata(result))
            event["raw_output_chars"] = len(text)
            result = compact_route_result(self.name, result)
            event["output_chars"] = len(str(result))
            return result
        finally:
            event["elapsed_ms"] = round((monotonic() - started) * 1000)
            self.trace.tools.append(event)
            logger.info("map_tool trace_id=%s event=%s", self.trace.trace_id, event)
