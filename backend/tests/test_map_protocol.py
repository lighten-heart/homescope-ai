"""地图工具协议兼容与业务结果区分，不调用外部服务。"""

import json

import pytest

from app.services.map_protocol import normalize_map_reply, parse_map_tool_calls


@pytest.mark.parametrize("envelope", [
    {"name": "amap_maps_geo", "arguments": {"address": "测试"}},
    {"tool": "amap_maps_geo", "parameters": {"address": "测试"}},
    {"tool_name": "maps_geo", "arguments": {"address": "测试"}},
    {"function_call": {"name": "amap_maps_geo", "arguments": '{"address":"测试"}'}},
    {"tool_calls": [{"id": "call_1", "type": "function", "function": {
        "name": "amap_maps_geo", "arguments": '{"address":"测试"}',
    }}]},
])
def test_json_tool_requests_become_registered_tool_calls(envelope):
    normalized, kind = normalize_map_reply(json.dumps(envelope), {"amap_maps_geo"})
    assert kind == "json_tool_call"
    calls = parse_map_tool_calls(normalized)
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "amap_maps_geo"
    assert json.loads(calls[0]["parameters"]) == {"address": "测试"}


def test_unregistered_tool_is_not_executed_and_batch_is_not_partially_executed():
    raw = json.dumps({"tool_calls": [
        {"name": "amap_maps_geo", "arguments": {}},
        {"name": "run_shell", "arguments": {"command": "private-input"}},
    ]})
    normalized, kind = normalize_map_reply(raw, {"amap_maps_geo"})
    assert normalized == raw
    assert kind == "unexpected_json"
    assert parse_map_tool_calls(normalized) == []


def test_json_parameters_can_contain_arrays_and_closing_brackets():
    parameters = {"address": "测试]地址", "values": [1, {"x": [2]}]}
    raw = '[TOOL_CALL:amap_maps_geo:' + json.dumps(parameters) + ']'
    calls = parse_map_tool_calls(raw)
    assert len(calls) == 1
    assert json.loads(calls[0]["parameters"]) == parameters
    assert calls[0]["original"] == raw


def test_tool_marker_inside_parameter_is_not_a_second_call():
    nested = '[TOOL_CALL:amap_maps_geo:{"address":"other"}]'
    raw = '[TOOL_CALL:amap_maps_geo:' + json.dumps({"address": nested}) + ']'
    assert len(parse_map_tool_calls(raw)) == 1


@pytest.mark.parametrize("key", ["data", "result"])
def test_result_wrapper_is_removed_without_inventing_fields(key):
    payload = {"work_location": None, "candidates": []}
    normalized, kind = normalize_map_reply(json.dumps({key: payload}))
    assert kind == "wrapped_result"
    assert json.loads(normalized) == payload


def test_failure_wrapper_is_not_unwrapped_into_success():
    raw = json.dumps({"success": False, "data": {"work_location": {}, "candidates": []}})
    normalized, kind = normalize_map_reply(raw)
    assert kind == "error"
    assert "error" in json.loads(normalized)
