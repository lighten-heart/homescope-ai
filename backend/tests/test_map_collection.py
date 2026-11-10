"""默认地图路径回归：真实MCP数据形状、完整覆盖、无模型和无网络。"""

import copy
import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.agents.map_data_agent import MapDataAgent, MapDataAgentError
from app.services.candidate_service import CandidateService
from app.services.map_collection_service import BASE_FACILITIES, ROUTE_TOOLS


def make_agent(request, overrides=None):
    candidates = CandidateService().list_candidates("北京")
    locations = {request.work_address: "116.30,39.98"}
    locations.update({c.address: f"116.{40 + i},40.01" for i, c in enumerate(candidates)})
    calls = []
    overrides = overrides or {}

    def run(name, params):
        calls.append((name, dict(params)))
        if name in overrides:
            response = overrides[name](params)
        elif name == "amap_maps_geo":
            response = {"return": [{"location": locations[params["address"]]}]}
        elif name == "amap_maps_direction_transit_integrated":
            response = {"route": {"distance": "12345", "transits": [
                {"duration": "3600"}, {"duration": "1801"},
            ]}}
        elif name in ROUTE_TOOLS.values():
            key = "data" if name == "amap_maps_bicycling" else "route"
            response = {key: {"paths": [{"distance": "8000", "duration": "1201"}]}}
        elif name == "amap_maps_around_search":
            response = {"pois": [{"id": "subway-1", "name": "测试地铁站", "typecode": "150500"}]}
        elif name == "amap_maps_search_detail":
            response = {"id": "subway-1", "location": "116.41,40.02"}
        elif name == "amap_maps_distance":
            response = {"results": [{"origin_id": "1", "dest_id": "1", "distance": "650"}]}
        else:
            raise AssertionError(name)
        return response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)

    names = {"amap_maps_geo", "amap_maps_around_search", "amap_maps_search_detail",
             "amap_maps_distance", *ROUTE_TOOLS.values()}
    tools = []
    for name in names:
        tool = Mock()
        tool.name = name
        tool.description = "fake MCP transport"
        tool.run.side_effect = lambda params, name=name: run(name, params)
        tools.append(tool)
    parent = Mock()
    parent.get_expanded_tools.return_value = tools
    service = SimpleNamespace(tool=parent, check_key_platform=Mock())

    class NoModel:
        @property
        def client(self):
            raise AssertionError("默认地图采集不应请求LLM")

    return MapDataAgent(NoModel(), service), candidates, calls


def test_default_path_collects_every_candidate_and_facility(housing_request, caplog):
    caplog.set_level(logging.INFO)
    agent, candidates, calls = make_agent(housing_request)
    original = copy.deepcopy(candidates)
    result = agent.enrich(housing_request, candidates)
    assert [item.candidate_id for item in result.candidates] == [c.id for c in candidates]
    assert [item.commute_minutes for item in result.candidates] == [31, 31, 31]
    assert all(item.route_distance_meters == 12345 for item in result.candidates)
    assert all(item.subway_distance_meters == 650 for item in result.candidates)
    assert sum(name == "amap_maps_geo" for name, _ in calls) == 4
    assert sum(name == "amap_maps_direction_transit_integrated" for name, _ in calls) == 3
    for i in range(3):
        location = f"116.{40 + i},40.01"
        keywords = [p["keywords"] for n, p in calls
                    if n == "amap_maps_around_search" and p["location"] == location]
        assert keywords == list(BASE_FACILITIES)
    assert candidates == original
    assert "map_collection_completed" in caplog.text
    assert "candidates=3" in caplog.text
    assert housing_request.work_address not in caplog.text


@pytest.mark.parametrize("mode", ["驾车", "步行", "骑行"])
def test_transport_uses_matching_mcp_shape(housing_request, mode):
    request = housing_request.model_copy(update={"preferred_transportation": mode})
    agent, candidates, calls = make_agent(request)
    result = agent.enrich(request, candidates[:1])
    assert result.candidates[0].commute_minutes == 21
    assert result.candidates[0].route_distance_meters == 8000
    assert any(name == ROUTE_TOOLS[mode] for name, _ in calls)
    assert not any(name == ROUTE_TOOLS["公共交通"] for name, _ in calls)


def test_transit_distance_uses_actual_segments_not_all_alternatives(housing_request):
    payload = {"route": {"transits": [{"duration": "1800", "walking_distance": "500",
        "segments": [{"walking": {"distance": "500"}, "railway": {},
                      "bus": {"buslines": [{"distance": "7000"}, {"distance": "9000"}]}}]}]}}
    agent, candidates, _ = make_agent(housing_request, {
        ROUTE_TOOLS["公共交通"]: lambda _: payload,
    })
    result = agent.enrich(housing_request, candidates[:1])
    assert result.candidates[0].route_distance_meters == 7500


@pytest.mark.parametrize("payload", [
    {"route": {"transits": []}},
    {"route": {"transits": [{"duration": "1800"}]}},
    {"route": {"distance": "1000", "transits": [{"duration": True}]}},
    {"route": {"transits": [{"duration": "1800", "walking_distance": "500",
        "segments": [{"railway": {"name": "铁路"}, "bus": {"buslines": []}}]}]}},
])
def test_missing_route_evidence_fails_explicitly(housing_request, payload):
    agent, candidates, _ = make_agent(housing_request, {ROUTE_TOOLS["公共交通"]: lambda _: payload})
    with pytest.raises(MapDataAgentError, match=r"candidate_1.route"):
        agent.enrich(housing_request, candidates[:1])


def test_empty_optional_pois_are_not_api_failure_and_custom_preference_is_queried(housing_request):
    from app.services.candidate_enrichment_service import apply_map_enrichment
    request = housing_request.model_copy(update={"preferred_facilities": ["图书馆"]})
    def around(params):
        return {"pois": [{"id": "subway-1", "name": "站点", "typecode": "150500"}]
                if params["keywords"] == "地铁站" else []}
    agent, candidates, calls = make_agent(request, {"amap_maps_around_search": around})
    result = agent.enrich(request, candidates[:1])
    assert result.candidates[0].facilities == ["地铁站"]
    assert any(p.get("keywords") == "图书馆" for _, p in calls)
    assert any("未返回POI" in text for text in result.candidates[0].evidence)
    enriched = apply_map_enrichment(candidates[:1], result)
    assert enriched[0].facilities == ["地铁站"]
    assert candidates[0].facilities != enriched[0].facilities


def test_subway_empty_result_expands_once(housing_request):
    def around(params):
        return {"pois": [] if params["radius"] == "1000" else [
            {"id": "subway-1", "name": "站点", "typecode": "150500"}]}
    agent, candidates, calls = make_agent(housing_request, {"amap_maps_around_search": around})
    result = agent.enrich(housing_request, candidates[:1])
    radii = [p["radius"] for n, p in calls if n == "amap_maps_around_search" and p["keywords"] == "地铁站"]
    assert radii == ["1000", "3000"]
    assert result.candidates[0].subway_distance_meters == 650


@pytest.mark.parametrize("reply,reason", [
    ({"pois": []}, "subway_walking_evidence_missing"),
    ("Around Search failed: INVALID_USER_KEY secret-key", "INVALID_USER_KEY"),
    ({"pois": "secret-key"}, "invalid_poi_list"),
])
def test_no_fake_subway_result_and_no_unbounded_retry(housing_request, reply, reason, caplog):
    agent, candidates, calls = make_agent(housing_request, {"amap_maps_around_search": lambda _: reply})
    with pytest.raises(MapDataAgentError, match=reason) as exc:
        agent.enrich(housing_request, candidates)
    assert sum(n == "amap_maps_around_search" for n, _ in calls) <= 2
    assert "secret-key" not in str(exc.value) + caplog.text
    assert "map_collection_completed" not in caplog.text


@pytest.mark.parametrize("rows", [[], [{"location": "bad"}],
    [{"location": "116,40"}, {"location": "117,40"}]])
def test_invalid_or_ambiguous_geocode_stops_before_routes(housing_request, rows):
    agent, candidates, calls = make_agent(housing_request, {"amap_maps_geo": lambda _: {"return": rows}})
    with pytest.raises(MapDataAgentError, match="work_geocode"):
        agent.enrich(housing_request, candidates)
    assert len(calls) == 1


def test_tool_exception_does_not_leak_or_become_empty_results(housing_request, caplog):
    def fail(_):
        raise RuntimeError("secret-key private-address")
    agent, candidates, _ = make_agent(housing_request, {"amap_maps_geo": fail})
    with pytest.raises(MapDataAgentError, match="tool_exception") as exc:
        agent.enrich(housing_request, candidates)
    assert "secret-key" not in str(exc.value) + caplog.text


def test_second_candidate_failure_cannot_return_partial_success(housing_request, caplog):
    def around(params):
        if params["location"] == "116.41,40.01":
            return "Around Search failed: ACCESS_TOO_FREQUENT"
        return {"pois": [{"id": "subway-1", "name": "站点", "typecode": "150500"}]}
    agent, candidates, _ = make_agent(housing_request, {"amap_maps_around_search": around})
    with pytest.raises(MapDataAgentError, match="candidate_2.facility_1"):
        agent.enrich(housing_request, candidates)
    assert "map_collection_completed" not in caplog.text
