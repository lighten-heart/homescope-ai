"""用实际MCP输出形状复现缺失距离，不连接高德或模型。"""

import json
from unittest.mock import Mock

import pytest

from app.services.map_tool_evidence import SubwayEvidenceTool, tool_result_metadata
from app.services.map_diagnostics import MapCallTrace, TracedMapTool


def make_tool(name, payload):
    tool = Mock()
    tool.name = name
    tool.description = "test tool"
    tool.get_parameters.return_value = []
    body = payload if isinstance(payload, str) else json.dumps(payload)
    tool.run.return_value = f"工具 '{name}' 执行结果:\n{body}"
    return tool


def make_subway_tool():
    around = make_tool("amap_maps_around_search", {"pois": [
        {"id": "shop", "name": "地铁便利店", "typecode": "060200"},
        {"id": "station", "name": "测试站", "typecode": "150500"},
    ]})
    detail = make_tool("amap_maps_search_detail", {
        "id": "station", "location": "116.31,39.98",
    })
    distance = make_tool("amap_maps_distance", {"results": [
        {"origin_id": "1", "dest_id": "1", "distance": "580", "duration": "420"},
    ]})
    return SubwayEvidenceTool(around, detail, distance), around, detail, distance


PARAMETERS = {"keywords": "地铁站", "location": "116.30,39.98", "radius": "1000"}


def test_missing_poi_distance_is_filled_from_real_detail_and_distance_tools():
    tool, around, detail, distance = make_subway_tool()
    result = json.loads(tool.run(PARAMETERS))
    evidence = result["homescope_subway_evidence"]
    assert evidence["status"] == "verified"
    assert evidence["distance_meters"] == 580
    assert evidence["distance_type"] == "walking"
    assert "not_guaranteed_nearest" in evidence["selection"]
    assert len(result["pois"]) == 2
    detail.run.assert_called_once_with({"id": "station"})
    distance.run.assert_called_once_with({
        "origins": "116.30,39.98", "destination": "116.31,39.98", "type": "3",
    })
    around.run.assert_called_once_with(PARAMETERS)


def test_other_facility_queries_do_not_trigger_extra_calls():
    tool, around, detail, distance = make_subway_tool()
    assert tool.run(dict(PARAMETERS, keywords="公园")) == around.run.return_value
    detail.run.assert_not_called()
    distance.run.assert_not_called()


def test_empty_subway_results_do_not_create_fake_distance():
    tool, around, detail, distance = make_subway_tool()
    around.run.return_value = '{"pois":[]}'
    result = json.loads(tool.run(PARAMETERS))
    assert result["homescope_subway_evidence"] == {
        "status": "insufficient", "code": "no_subway_poi",
    }
    assert "distance_meters" not in result["homescope_subway_evidence"]
    detail.run.assert_not_called()
    distance.run.assert_not_called()


@pytest.mark.parametrize("location", [None, "", "nan,39", "181,39", "116,91", "116,39,4"])
def test_missing_or_invalid_poi_location_is_not_fabricated(location):
    tool, _, detail, distance = make_subway_tool()
    detail.run.return_value = json.dumps({"id": "station", "location": location})
    result = json.loads(tool.run(PARAMETERS))
    assert result["homescope_subway_evidence"]["code"] == "poi_location_missing"
    distance.run.assert_not_called()


@pytest.mark.parametrize("value", [None, -1, True, "580米", "", "NaN"])
def test_invalid_distance_is_not_replaced_with_zero(value):
    tool, _, _, distance = make_subway_tool()
    distance.run.return_value = json.dumps({"results": [
        {"origin_id": "1", "dest_id": "1", "distance": value},
    ]})
    result = json.loads(tool.run(PARAMETERS))
    assert result["homescope_subway_evidence"]["code"] == "distance_value_invalid"


def test_distance_error_is_not_retried_or_converted_to_success():
    tool, _, _, distance = make_subway_tool()
    distance.run.return_value = "Direction Distance failed: INVALID_USER_KEY secret-value"
    result = json.loads(tool.run(PARAMETERS))
    assert result["homescope_subway_evidence"]["code"] == "distance_query_failed"
    distance.run.assert_called_once()
    assert "secret-value" not in json.dumps(result)


@pytest.mark.parametrize("body", [
    "Around Search failed: INVALID_USER_KEY secret-value",
    '{"status":"0","info":"INVALID_USER_KEY","private":"secret-value"}',
    '{"isError":true,"error":"INVALID_USER_KEY secret-value"}',
])
def test_wrapped_mcp_failure_is_visible_without_leaking_body(body, caplog):
    trace = MapCallTrace()
    tool = make_tool("amap_maps_around_search", body)
    assert TracedMapTool(tool, trace).run({}) == tool.run.return_value
    assert trace.tools[0]["status"] == "error_text"
    assert trace.tools[0]["error_code"] == "INVALID_USER_KEY"
    assert "secret-value" not in str(trace.snapshot()) + caplog.text


def test_successful_empty_pois_are_not_an_api_failure():
    assert tool_result_metadata('{"pois": []}') == {
        "status": "returned_unverified", "poi_count": 0,
    }


def test_map_prompt_overrides_framework_coordinate_parameter_format():
    from app.agents.map_data_agent import MapToolAgent, MAP_DATA_AGENT_PROMPT
    agent = MapToolAgent(name="test", llm=Mock(), system_prompt=MAP_DATA_AGENT_PROMPT)
    tool = make_tool("amap_maps_around_search", '{"pois":[]}')
    agent.add_tool(tool, auto_expand=False)
    prompt = agent._get_enhanced_system_prompt()
    assert prompt.rindex("必须是完整JSON对象") > prompt.index("使用 `key=value` 格式")
    assert "homescope_subway_evidence" in prompt
    assert "实际JSON Schema" in prompt


def test_agent_delivers_supplemental_evidence_to_llm(housing_request):
    from types import SimpleNamespace
    from app.agents.map_data_agent import MapDataAgent

    _, around, detail, distance = make_subway_tool()
    parent = Mock()
    parent.get_expanded_tools.return_value = [around, detail, distance]
    llm = Mock()
    llm.invoke.side_effect = [
        '[TOOL_CALL:amap_maps_around_search:' + json.dumps(PARAMETERS) + ']',
        '{"work_location":{"longitude":116.30,"latitude":39.98},"candidates":[]}',
    ]
    agent = MapDataAgent(
        SimpleNamespace(client=llm),
        SimpleNamespace(tool=parent, check_key_platform=Mock()),
    )
    agent.enrich_with_llm(housing_request, [])
    messages = llm.invoke.call_args.args[0]
    assert any('"distance_meters": 580' in message["content"] for message in messages)
    detail.run.assert_called_once()
    distance.run.assert_called_once()


def test_final_error_keeps_safe_diagnostics(housing_request, caplog):
    from types import SimpleNamespace
    from app.agents.map_data_agent import MapDataAgent, MapDataAgentError

    _, around, detail, distance = make_subway_tool()
    parent = Mock()
    parent.get_expanded_tools.return_value = [around, detail, distance]
    llm = Mock()
    llm.invoke.return_value = '{"error":{"code":"private-final-secret"}}'
    agent = MapDataAgent(
        SimpleNamespace(client=llm),
        SimpleNamespace(tool=parent, check_key_platform=Mock()),
    )
    with pytest.raises(MapDataAgentError) as exc:
        agent.enrich_with_llm(housing_request, [])
    assert "trace_id=" in str(exc.value)
    assert "tool_calls=0" in str(exc.value)
    assert "private-final-secret" not in str(exc.value) + caplog.text
    llm.invoke.assert_called_once()
