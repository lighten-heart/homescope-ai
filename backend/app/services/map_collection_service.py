"""按候选区域完整采集MCP事实；不依赖模型决定何时结束或生成JSON。"""

import logging
import math
import re

from app.models.schemas import (
    CandidateArea, HousingDecisionRequest, MapEnrichmentResult,
)
from app.services.map_diagnostics import MapCallTrace, TracedMapTool
from app.services.map_tool_evidence import (
    SubwayEvidenceTool, parse_map_payload, tool_result_metadata, valid_location,
)

logger = logging.getLogger(__name__)

ROUTE_TOOLS = {
    "公共交通": "amap_maps_direction_transit_integrated",
    "驾车": "amap_maps_direction_driving",
    "步行": "amap_maps_direction_walking",
    "骑行": "amap_maps_bicycling",
}
BASE_FACILITIES = ("地铁站", "超市", "医院", "公园", "健身房", "商场")


class MapCollectionError(RuntimeError):
    """可安全返回的采集错误，只含固定步骤、序号和原因码。"""


def _integer(value) -> int | None:
    # MCP距离单位是米、时间单位是秒。拒绝布尔值、负数和带单位猜测。
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
        return None
    return int(value)


def _transit_distance(route: dict, transit: dict) -> tuple[int | None, str]:
    distance = _integer(transit.get("distance"))
    if distance is not None:
        return distance, "所选公交方案distance"
    distance = _integer(route.get("distance"))
    if distance is not None:
        return distance, "公交接口route.distance（接口级距离）"

    # 当前MCP会省略transit.distance，但保留walking_distance和公交分段。
    # 公交分段内的buslines是备选线路，选第一条，不能把所有备选距离相加。
    walking = _integer(transit.get("walking_distance"))
    segments = transit.get("segments")
    if walking is None or not isinstance(segments, list) or not segments:
        return None, ""
    total = walking
    for segment in segments:
        if not isinstance(segment, dict):
            return None, ""
        railway = segment.get("railway", {})
        if not isinstance(railway, dict) or any(railway.values()):
            # MCP未保留铁路里程，不能把铁路段当作0米。
            return None, ""
        bus = segment.get("bus")
        lines = bus.get("buslines") if isinstance(bus, dict) else None
        if not isinstance(lines, list):
            return None, ""
        if lines:
            length = _integer(lines[0].get("distance")) if isinstance(lines[0], dict) else None
            if length is None:
                return None, ""
            total += length
        else:
            step = segment.get("walking")
            if not isinstance(step, dict) or _integer(step.get("distance")) is None:
                return None, ""
    return total, "walking_distance加各公交段首条线路distance"


class MapCollectionService:
    """每次请求独立实例。固定步骤完成所有候选区域后才返回结果。"""

    def __init__(self, tools, trace: MapCallTrace):
        self.trace = trace
        self.tools = {tool.name: TracedMapTool(tool, trace) for tool in tools}
        around = self.tools.get("amap_maps_around_search")
        if around is not None:
            self.tools[around.name] = SubwayEvidenceTool(
                around, self.tools.get("amap_maps_search_detail"),
                self.tools.get("amap_maps_distance"),
            )

    def _fail(self, step: str, code: str):
        raise MapCollectionError(
            f"地图采集失败：step={step} reason={code} trace_id={self.trace.trace_id}"
        )

    def _call(self, name: str, parameters: dict, step: str) -> dict:
        tool = self.tools.get(name)
        if tool is None:
            self._fail(step, "missing_tool")
        try:
            raw = tool.run(parameters)
        except Exception as exc:
            # MCP异常可能带请求URL和密钥，不直接拼接原文。
            raise MapCollectionError(
                f"地图采集失败：step={step} reason=tool_exception "
                f"trace_id={self.trace.trace_id}"
            ) from exc
        metadata = tool_result_metadata(raw)
        if metadata["status"] == "error_text":
            self._fail(step, metadata.get("error_code", "upstream_tool_error"))
        payload = parse_map_payload(raw)
        if payload is None:
            self._fail(step, "invalid_tool_json")
        return payload

    def _geo(self, address: str, city: str, step: str) -> str:
        # 已安装MCP的geo实现没有把city传入HTTP请求，因此补全地址城市前缀。
        query = address if address.startswith(city) else city + address
        data = self._call("amap_maps_geo", {"address": query, "city": city}, step)
        rows = data.get("return", data.get("geocodes"))
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            self._fail(step, "geocode_empty_or_ambiguous")
        location = valid_location(rows[0].get("location"))
        if location is None:
            self._fail(step, "invalid_coordinates")
        return location

    def _route(self, request, origin, destination, step):
        parameters = {"origin": origin, "destination": destination}
        transit = request.preferred_transportation == "公共交通"
        if transit:
            parameters.update(city=request.city, cityd=request.city)
        data = self._call(ROUTE_TOOLS[request.preferred_transportation], parameters, step)
        route = data.get("data" if request.preferred_transportation == "骑行" else "route")
        if not isinstance(route, dict):
            self._fail(step, "route_missing")
        paths = route.get("transits" if transit else "paths")
        if not isinstance(paths, list) or not paths:
            self._fail(step, "no_route")
        choices = []
        for path in paths:
            if not isinstance(path, dict):
                continue
            seconds = _integer(path.get("duration"))
            distance, basis = (
                _transit_distance(route, path) if transit
                else (_integer(path.get("distance")), "所选路线path.distance")
            )
            if seconds is not None and distance is not None:
                choices.append((seconds, distance, basis))
        if not choices:
            self._fail(step, "route_duration_or_distance_missing")
        seconds, distance, basis = min(choices, key=lambda item: item[0])
        return math.ceil(seconds / 60), distance, basis

    def _around(self, location, keyword, radius, step):
        data = self._call("amap_maps_around_search", {
            "location": location, "keywords": keyword, "radius": str(radius),
        }, step)
        pois = data.get("pois")
        if not isinstance(pois, list) or any(
            not isinstance(poi, dict) or not poi.get("id") or not poi.get("name")
            for poi in pois
        ):
            self._fail(step, "invalid_poi_list")
        return data

    def collect(self, request: HousingDecisionRequest,
                candidates: list[CandidateArea]) -> MapEnrichmentResult:
        work = self._geo(request.work_address, request.city, "work_geocode")
        enriched = []
        keywords = list(dict.fromkeys([*BASE_FACILITIES, *request.preferred_facilities]))
        for index, candidate in enumerate(candidates, start=1):
            step = f"candidate_{index}"
            origin = self._geo(candidate.address, request.city, step + ".geocode")
            minutes, distance, basis = self._route(request, origin, work, step + ".route")
            facilities = []
            evidence = [
                "高德地理编码提供区域代表点，不代表具体房源门口。",
                f"在返回且字段完整的路线中选择最短耗时方案，通勤{minutes}分钟；距离依据：{basis}。",
            ]
            subway_distance = None
            for keyword_index, keyword in enumerate(keywords, start=1):
                poi_step = step + f".facility_{keyword_index}"
                radius = 1000
                data = self._around(origin, keyword, radius, poi_step)
                if keyword == "地铁站":
                    proof = data.get("homescope_subway_evidence", {})
                    # 只对成功查询但没找到地铁的情况扩大一次范围；API失败不伪装为空。
                    if proof.get("code") == "no_subway_poi":
                        radius = 3000
                        data = self._around(origin, keyword, radius, poi_step)
                        proof = data.get("homescope_subway_evidence", {})
                    subway_distance = _integer(proof.get("distance_meters"))
                    if proof.get("status") != "verified" or subway_distance is None:
                        self._fail(poi_step, "subway_walking_evidence_missing")
                    evidence.append(
                        f"地铁搜索半径{radius}米；所选站点步行距离{subway_distance}米，不保证为最近站。"
                    )
                if data["pois"]:
                    facilities.append(keyword)
                else:
                    evidence.append(f"{keyword}在{radius}米搜索范围内未返回POI，不代表整个区域不存在。")
            enriched.append({
                "candidate_id": candidate.id, "location": origin,
                "commute_minutes": minutes, "route_distance_meters": distance,
                "subway_distance_meters": subway_distance, "facilities": facilities,
                "evidence": evidence, "source": "amap_mcp",
            })
            logger.info(
                "map_candidate_completed trace_id=%s candidate_index=%d facilities_queried=%d",
                self.trace.trace_id, index, len(keywords),
            )
        result = MapEnrichmentResult.model_validate({"work_location": work, "candidates": enriched})
        logger.info("map_collection_completed trace_id=%s candidates=%d tool_calls=%d",
                    self.trace.trace_id, len(enriched), len(self.trace.tools))
        return result
