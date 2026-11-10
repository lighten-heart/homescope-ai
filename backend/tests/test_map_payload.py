import json
from app.services.map_payload import compact_route_result


def test_compaction_preserves_every_route_and_business_field():
    route = {"duration":"2300", "distance":"15000", "segments":[{
        "walking":{"duration":"200","distance":"300","steps":[{
            "instruction":"walk to station", "polyline":"116.1,39.1;" * 2000}]},
        "bus":{"buslines":[{"name":"test-line","departure_stop":{"name":"station"}}]},
    }]}
    data = {"status":"1", "route":{"transits":[route, dict(route, duration="2500")]}}
    raw = "工具 'maps_direction_transit_integrated' 执行结果:\n" + json.dumps(data, indent=2)
    compact = compact_route_result("amap_maps_direction_transit_integrated", raw)
    parsed = json.loads(compact.split("\n",1)[1])
    routes = parsed["route"]["transits"]
    assert len(routes) == 2
    assert [r["duration"] for r in routes] == ["2300", "2500"]
    assert routes[0]["distance"] == "15000"
    assert routes[0]["segments"][0]["walking"]["duration"] == "200"
    assert routes[0]["segments"][0]["walking"]["steps"][0] == {"instruction":"walk to station"}
    assert routes[0]["segments"][0]["bus"] == route["segments"][0]["bus"]
    assert len(compact) < len(raw) / 10
    assert "polyline" in route["segments"][0]["walking"]["steps"][0]


def test_unknown_and_error_responses_are_not_hidden():
    for raw in ("异步操作失败: error", "not json", "工具 'maps_test' 执行结果:\ninvalid"):
        assert compact_route_result("amap_maps_direction_driving", raw) == raw
    raw = '{"pois": [], "polyline": "keep"}'
    assert compact_route_result("amap_maps_around_search", raw) == raw
    error = {"status":"0", "info":"INVALID_USER_KEY"}
    assert json.loads(compact_route_result("amap_maps_direction_driving", json.dumps(error))) == error
