"""诊断必须不改变消息/工具结果，不泄露正文，并可定位失败轮次。"""

import logging
from unittest.mock import Mock
from types import SimpleNamespace

import pytest
from hello_agents.core.exceptions import HelloAgentsException

from app.services.map_diagnostics import MapCallTrace, TracedLLM, TracedMapTool
from app.services.llm_errors import LLMUpstreamError
from app.agents.map_data_agent import MapDataAgent


def test_proxy_preserves_content_and_records_no_secrets(caplog):
    caplog.set_level(logging.INFO)
    trace = MapCallTrace()
    client = Mock()
    client.invoke.return_value = "private-output"
    messages = [{"role": "user", "content": "secret-key private-address"}]
    result = TracedLLM(client, trace).invoke(messages, temperature=0.3)
    assert result == "private-output"
    assert client.invoke.call_args.args[0] is messages
    client.invoke.assert_called_once_with(messages, temperature=0.3)
    tool = Mock(name="fake")
    tool.name = "amap_maps_geo"
    tool.description = "geo"
    tool.run.return_value = "private-location"
    params = {"address": "private-address"}
    assert TracedMapTool(tool, trace).run(params) == "private-location"
    assert tool.run.call_args.args[0] is params
    for secret in ("secret-key", "private-address", "private-output", "private-location"):
        assert secret not in str(trace.snapshot()) + caplog.text


def test_second_round_rejection_identifies_preceding_tool(housing_request, caplog):
    client = Mock()
    client.invoke.side_effect = [
        '[TOOL_CALL:amap_maps_geo:{"address":"private-address"}]',
        HelloAgentsException("Content Exists Risk (request_id: 146c1a88-dea0-4db1-8b5d-1fdca3a08333) secret-key"),
    ]
    tool = Mock()
    tool.name = "amap_maps_geo"
    tool.description = "geo"
    tool.get_parameters.return_value = []
    tool.run.return_value = "private-location"
    parent = Mock()
    parent.get_expanded_tools.return_value = [tool]
    agent = MapDataAgent(SimpleNamespace(client=client), SimpleNamespace(tool=parent, check_key_platform=Mock()))
    with pytest.raises(LLMUpstreamError) as exc:
        agent.enrich_with_llm(housing_request, [])
    detail = exc.value.as_detail()
    diag = detail["diagnostics"]
    assert diag["llm_round"] == 2
    assert diag["rounds"][-1]["status"] == "failed"
    assert diag["rounds"][-1]["tools_completed_before"] == 1
    assert diag["tool_calls"][0]["tool"] == "amap_maps_geo"
    assert client.invoke.call_count == 2
    for secret in ("private-address", "private-location", "secret-key"):
        assert secret not in str(detail) + caplog.text


@pytest.mark.parametrize("response,status", [
    ("异步操作失败: private-error", "error_text"),
    ("{}", "returned_unverified"),
])
def test_tool_status_and_trace_isolation(response, status):
    trace = MapCallTrace()
    other = MapCallTrace()
    tool = Mock()
    tool.name = "amap_maps_geo"
    tool.description = "geo"
    tool.run.return_value = response
    assert TracedMapTool(tool, trace).run({}) == response
    assert trace.tools[0]["status"] == status
    assert other.tools == []
    assert trace.trace_id != other.trace_id


def test_first_round_failure_has_no_tools():
    trace = MapCallTrace()
    client = Mock()
    client.invoke.side_effect = HelloAgentsException("Content Exists Risk")
    with pytest.raises(HelloAgentsException):
        TracedLLM(client, trace).invoke([])
    assert trace.snapshot()["llm_round"] == 1
    assert trace.snapshot()["tool_calls"] == []
    client.invoke.assert_called_once()
