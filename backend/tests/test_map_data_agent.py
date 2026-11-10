"""保留旧enrich_with_llm学习路径的协议测试；默认入口见test_map_collection。"""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from hello_agents.tools.builtin.mcp_wrapper_tool import MCPWrappedTool

from app.agents.map_data_agent import MapDataAgent, MapDataAgentError


def make_agent(output):
    """使用真实SimpleAgent/工具包装器，只替换MCP传输和LLM调用。"""
    parent = Mock()
    parent.run.return_value = '{"return":[{"location":"116.30,39.98"}]}'
    tool = MCPWrappedTool(
        mcp_tool=parent,
        prefix="amap_",
        tool_info={
            "name": "maps_geo",
            "description": "地址转经纬度",
            "input_schema": {
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                    "city": {"type": "string"},
                },
                "required": ["address"],
            },
        },
    )
    parent.get_expanded_tools.return_value = [tool]
    service = SimpleNamespace(tool=parent, check_key_platform=Mock())
    llm = Mock()
    llm.invoke.side_effect = output
    return MapDataAgent(SimpleNamespace(client=llm), service), llm, parent


def test_expanded_tool_is_executed_and_more_than_three_rounds_supported(housing_request):
    call = '[TOOL_CALL:amap_maps_geo:{"address":"北京市海淀区中关村","city":"北京"}]'
    result_json = json.dumps({
        "work_location": {"longitude": 116.30, "latitude": 39.98},
        "candidates": [],
    })
    agent, llm, parent = make_agent([call] * 4 + [result_json])
    result = agent.enrich_with_llm(housing_request, [])

    assert result.work_location.longitude == 116.30
    assert llm.invoke.call_count == 5
    assert parent.run.call_count == 4
    parent.run.assert_called_with({
        "action": "call_tool",
        "tool_name": "maps_geo",
        "arguments": {"address": "北京市海淀区中关村", "city": "北京"},
    })
    assert "amap_maps_geo" in llm.invoke.call_args.args[0][0]["content"]


@pytest.mark.parametrize("output", ["", "查询失败 secret-test-value", '{"bad":}'])
def test_non_json_response_reports_map_stage_without_leaking_content(
    housing_request, caplog, output,
):
    agent, _, _ = make_agent([output])
    with pytest.raises(MapDataAgentError, match="地图Agent最终回复无法解析") as exc:
        agent.enrich_with_llm(housing_request, [])
    assert "secret-test-value" not in str(exc.value)
    assert "secret-test-value" not in caplog.text


def test_empty_tool_discovery_fails_before_llm(housing_request):
    agent, llm, parent = make_agent([])
    parent.get_expanded_tools.return_value = []
    with pytest.raises(MapDataAgentError, match="没有发现可用工具"):
        agent.enrich_with_llm(housing_request, [])
    llm.invoke.assert_not_called()


def test_invalid_location_is_not_replaced_with_invented_coordinates(housing_request):
    agent, _, _ = make_agent(['{"work_location":null,"candidates":[]}'])
    with pytest.raises(MapDataAgentError, match="work_location"):
        agent.enrich_with_llm(housing_request, [])


def test_prose_after_tools_is_finalized_once_with_original_evidence(housing_request):
    call = '[TOOL_CALL:amap_maps_geo:{"address":"test"}]'
    valid = '{"work_location":{"longitude":116.30,"latitude":39.98},"candidates":[]}'
    agent, llm, parent = make_agent([call, "已完成查询，下面说明结果。", valid])
    result = agent.enrich_with_llm(housing_request, [])
    assert result.work_location.longitude == 116.30
    assert llm.invoke.call_count == 3
    assert parent.run.call_count == 1
    assert llm.invoke.call_args.kwargs["response_format"] == {"type": "json_object"}
    messages = llm.invoke.call_args.args[0]
    assert any('116.30,39.98' in m["content"] for m in messages)
    assert all("response_format" not in call.kwargs for call in llm.invoke.call_args_list[:2])


@pytest.mark.parametrize("final", ["仍然不是JSON", "", '{"error":{"code":"insufficient_map_data"}}'])
def test_finalization_failure_does_not_loop_or_fake_data(housing_request, final):
    call = '[TOOL_CALL:amap_maps_geo:{"address":"test"}]'
    agent, llm, parent = make_agent([call, "查询总结", final])
    with pytest.raises(MapDataAgentError):
        agent.enrich_with_llm(housing_request, [])
    assert llm.invoke.call_count == 3
    assert parent.run.call_count == 1


def test_finalization_rejection_is_not_retried(housing_request):
    from hello_agents.core.exceptions import HelloAgentsException
    from app.services.llm_errors import LLMUpstreamError
    call = '[TOOL_CALL:amap_maps_geo:{"address":"test"}]'
    agent, llm, _ = make_agent([call, "查询总结", HelloAgentsException("Content Exists Risk")])
    with pytest.raises(LLMUpstreamError) as exc:
        agent.enrich_with_llm(housing_request, [])
    assert exc.value.code == "llm_content_rejected"
    assert llm.invoke.call_count == 3


def test_failed_tool_is_not_converted_to_success(housing_request):
    call = '[TOOL_CALL:amap_maps_geo:{"address":"test"}]'
    agent, llm, parent = make_agent([call, "查询失败"])
    parent.run.return_value = "异步操作失败: query failed"
    with pytest.raises(MapDataAgentError):
        agent.enrich_with_llm(housing_request, [])
    assert llm.invoke.call_count == 2


def test_finalization_still_validates_coordinates(housing_request):
    call = '[TOOL_CALL:amap_maps_geo:{"address":"test"}]'
    agent, llm, _ = make_agent([call, "查询总结", '{"work_location":null,"candidates":[]}'])
    with pytest.raises(MapDataAgentError, match="work_location"):
        agent.enrich_with_llm(housing_request, [])
    assert llm.invoke.call_count == 3


def test_finalization_cannot_omit_candidates(housing_request):
    from app.services.candidate_service import CandidateService
    candidates = CandidateService().list_candidates("北京")
    call = '[TOOL_CALL:amap_maps_geo:{"address":"test"}]'
    incomplete = '{"work_location":{"longitude":116.30,"latitude":39.98},"candidates":[]}'
    agent, _, _ = make_agent([call, "查询总结", incomplete])
    with pytest.raises(MapDataAgentError, match="与输入不一致"):
        agent.enrich_with_llm(housing_request, candidates)


def test_formatter_releases_private_context():
    from app.services.map_diagnostics import MapCallTrace
    from app.services.map_output import MapOutputLLM
    trace = MapCallTrace()
    client = Mock()
    client.invoke.side_effect = ["summary", '{"error":{}}']
    formatter = MapOutputLLM(client, trace)
    formatter.invoke([{"role":"user", "content":"private-evidence"}])
    trace.tools.append({"status":"returned_unverified"})
    formatter.finalize_json("summary")
    assert formatter._last_messages == []
    assert not formatter.can_finalize("summary")
    assert "private-evidence" not in str(trace.snapshot())


def test_json_tool_call_is_executed_instead_of_validated_as_final_result(housing_request):
    call = json.dumps({"name": "amap_maps_geo", "arguments": {"address": "测试地址"}})
    valid = '{"work_location":{"longitude":116.30,"latitude":39.98},"candidates":[]}'
    agent, llm, parent = make_agent([call, valid])
    result = agent.enrich_with_llm(housing_request, [])
    assert result.work_location.longitude == 116.30
    parent.run.assert_called_once_with({
        "action": "call_tool", "tool_name": "maps_geo",
        "arguments": {"address": "测试地址"},
    })
    assert llm.invoke.call_count == 2


def test_unexpected_json_can_continue_tools_with_existing_context(housing_request):
    call = '[TOOL_CALL:amap_maps_geo:{"address":"test"}]'
    valid = '{"work_location":{"longitude":116.30,"latitude":39.98},"candidates":[]}'
    agent, llm, parent = make_agent([call, '{"progress":"continue"}', call, valid])
    result = agent.enrich_with_llm(housing_request, [])
    assert result.work_location.latitude == 39.98
    assert llm.invoke.call_count == 4
    assert parent.run.call_count == 2
    correction = llm.invoke.call_args_list[2].args[0]
    assert any("116.30,39.98" in message["content"] for message in correction)
    assert "继续当前采集任务" in correction[-1]["content"]


def test_unexpected_json_repair_is_bounded_and_does_not_log_private_values(housing_request, caplog):
    call = '[TOOL_CALL:amap_maps_geo:{"address":"test"}]'
    wrong = '{"progress":"private-progress"}'
    agent, llm, parent = make_agent([call, wrong, wrong])
    with pytest.raises(MapDataAgentError, match="work_location"):
        agent.enrich_with_llm(housing_request, [])
    assert llm.invoke.call_count == 3
    parent.run.assert_called_once()
    assert "private-progress" not in caplog.text
    assert "unexpected_json" in caplog.text


def test_failed_tool_does_not_trigger_protocol_repair(housing_request):
    call = '[TOOL_CALL:amap_maps_geo:{"address":"test"}]'
    agent, llm, parent = make_agent([call, '{"progress":"failed"}'])
    parent.run.return_value = "Geocoding failed: INVALID_USER_KEY"
    with pytest.raises(MapDataAgentError):
        agent.enrich_with_llm(housing_request, [])
    assert llm.invoke.call_count == 2


def test_protocol_repair_rejection_is_not_retried(housing_request):
    from hello_agents.core.exceptions import HelloAgentsException
    from app.services.llm_errors import LLMUpstreamError

    call = '[TOOL_CALL:amap_maps_geo:{"address":"test"}]'
    agent, llm, _ = make_agent([
        call, '{"progress":"continue"}', HelloAgentsException("Content Exists Risk"),
    ])
    with pytest.raises(LLMUpstreamError) as exc:
        agent.enrich_with_llm(housing_request, [])
    assert exc.value.code == "llm_content_rejected"
    assert llm.invoke.call_count == 3


def test_iteration_limit_does_not_parse_pending_tool_arguments_as_result(housing_request):
    call = '[TOOL_CALL:amap_maps_geo:{"address":"test"}]'
    agent, llm, parent = make_agent([call] * 13)
    with pytest.raises(MapDataAgentError, match="工具调用尚未完成"):
        agent.enrich_with_llm(housing_request, [])
    assert llm.invoke.call_count == 13
    assert parent.run.call_count == 12


def test_wrapped_result_still_rejects_invalid_location(housing_request):
    agent, llm, _ = make_agent(['{"data":{"work_location":null,"candidates":[]}}'])
    with pytest.raises(MapDataAgentError, match="work_location"):
        agent.enrich_with_llm(housing_request, [])
    llm.invoke.assert_called_once()
