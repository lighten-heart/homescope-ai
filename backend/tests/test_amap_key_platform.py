"""高德 Key 平台错误回归测试，不连接网络、不调用真实 LLM。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.agents.map_data_agent import MapDataAgent
from app.core.config import Settings
from app.services.amap_mcp_service import AmapConfigurationError, AmapMCPService


def make_service(response: str) -> AmapMCPService:
    service = AmapMCPService(Settings(_env_file=None))
    service._tool = Mock()
    service._tool.run.return_value = response
    return service


def test_key_platform_mismatch_has_actionable_safe_message():
    service = make_service(
        "异步操作失败: Geocoding failed: USERKEY_PLAT_NOMATCH key=secret-test-key"
    )
    with pytest.raises(AmapConfigurationError) as exc:
        service.check_key_platform("北京市海淀区中关村", "北京")

    assert "USERKEY_PLAT_NOMATCH" in str(exc.value)
    assert "Web服务" in str(exc.value)
    assert "HOMESCOPE_AMAP_API_KEY" in str(exc.value)
    assert "secret-test-key" not in str(exc.value)


def test_key_platform_check_allows_successful_query():
    service = make_service('{"geocodes": [{"location": "116.30,39.98"}]}')
    service.check_key_platform("北京市海淀区中关村", "北京")
    service._tool.run.assert_called_once_with({
        "action": "call_tool",
        "tool_name": "maps_geo",
        "arguments": {"address": "北京市海淀区中关村", "city": "北京"},
    })


def test_map_agent_rejects_bad_key_before_creating_llm_agent(
    housing_request, monkeypatch,
):
    service = make_service("异步操作失败: Geocoding failed: USERKEY_PLAT_NOMATCH")
    factory = Mock()
    monkeypatch.setattr("app.agents.map_data_agent.SimpleAgent", factory)
    agent = MapDataAgent(llm_service=SimpleNamespace(), amap_service=service)

    with pytest.raises(AmapConfigurationError):
        agent.enrich(housing_request, [])
    factory.assert_not_called()
