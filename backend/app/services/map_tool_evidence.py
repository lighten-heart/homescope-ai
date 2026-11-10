"""适配高德MCP缺失的地铁距离证据；只使用实际工具返回的数据。"""

import json
import math
import re

from hello_agents.tools.base import Tool


FAILURE_PREFIXES = (
    "异步操作失败", "错误", "MCP操作失败", "❌",
    "Geocoding failed:", "RGeocoding failed:", "IP Location failed:",
    "Get weather failed:", "Get poi detail failed:",
    "Direction bicycling failed:", "Direction Walking failed:",
    "Direction Driving failed:", "Direction Transit Integrated failed:",
    "Direction Distance failed:", "Text Search failed:", "Around Search failed:",
)
SAFE_ERROR_CODES = {
    "INVALID_USER_KEY", "USERKEY_PLAT_NOMATCH", "INVALID_PARAMS",
    "DAILY_QUERY_OVER_LIMIT", "USER_DAILY_QUERY_OVER_LIMIT",
    "ACCESS_TOO_FREQUENT", "SERVICE_NOT_AVAILABLE", "INSUFFICIENT_PRIVILEGES",
}


def unwrap_tool_text(result) -> str:
    text = str(result).strip()
    # 当前HelloAgents为MCP结果增加一行标题。
    if text.startswith("工具 '"):
        _, separator, payload = text.partition("\n")
        if separator:
            return payload.strip()
    return text


def parse_map_payload(result) -> dict | None:
    try:
        data = json.loads(unwrap_tool_text(result))
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def tool_result_metadata(result) -> dict:
    """仅返回固定状态/白名单错误码，不记录输入、URL或原始错误正文。"""
    text = unwrap_tool_text(result)
    data = parse_map_payload(result)
    failed = text.startswith(FAILURE_PREFIXES)
    if data is not None:
        failed = failed or (
            data.get("isError") is True
            or data.get("status") in ("0", 0)
            or bool(data.get("error"))
        )
    metadata = {"status": "error_text" if failed else "returned_unverified"}
    if failed:
        metadata["error_code"] = next(
            (code for code in sorted(SAFE_ERROR_CODES)
             if re.search(r"\b" + code + r"\b", text)),
            "upstream_tool_error",
        )
    elif data is not None and isinstance(data.get("pois"), list):
        metadata["poi_count"] = len(data["pois"])
    return metadata


def valid_location(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        longitude, latitude = [float(part) for part in value.split(",")]
    except (ValueError, TypeError):
        return None
    if (
        not math.isfinite(longitude) or not math.isfinite(latitude)
        or not -180 <= longitude <= 180 or not -90 <= latitude <= 90
    ):
        return None
    return value.strip()


class SubwayEvidenceTool(Tool):
    """包装周边搜索：地铁查询额外执行一次详情和一次步行距离查询。

    原MCP周边结果丢弃location和distance，不能直接提供评分所需距离。
    仅选择首个明确属于地铁类别的POI，不声称它是全城最近站点。
    """

    def __init__(self, around_tool, detail_tool, distance_tool):
        super().__init__(
            name=around_tool.name,
            description=(around_tool.description +
                         "。地铁关键词查询会附加homescope_subway_evidence，"
                         "提供一个查询到的地铁POI的实际步行距离或缺失原因。"),
        )
        self.around_tool = around_tool
        self.detail_tool = detail_tool
        self.distance_tool = distance_tool

    def get_parameters(self):
        return self.around_tool.get_parameters()

    def run(self, parameters):
        raw = self.around_tool.run(parameters)
        keywords = str(parameters.get("keywords", ""))
        if "地铁" not in keywords and "subway" not in keywords.lower():
            return raw
        payload = parse_map_payload(raw)
        if payload is None or tool_result_metadata(raw)["status"] == "error_text":
            return raw
        if not isinstance(payload.get("pois"), list):
            return raw

        evidence = {"status": "insufficient", "code": "no_subway_poi"}
        payload["homescope_subway_evidence"] = evidence

        def missing(code):
            evidence["code"] = code
            return json.dumps(payload, ensure_ascii=False)

        # 1505xx为地铁相关POI；不把名称带“地铁”的商店当成地铁站。
        poi = next((
            item for item in payload["pois"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
            and item["id"] and str(item.get("typecode", "")).startswith("1505")
        ), None)
        if poi is None:
            return missing("no_subway_poi")
        origin = valid_location(parameters.get("location"))
        if origin is None:
            return missing("invalid_origin")
        if self.detail_tool is None or self.distance_tool is None:
            return missing("missing_distance_tools")

        detail_raw = self.detail_tool.run({"id": poi["id"]})
        detail = parse_map_payload(detail_raw)
        if detail is None or tool_result_metadata(detail_raw)["status"] == "error_text":
            return missing("poi_detail_failed")
        if detail.get("id") != poi["id"]:
            return missing("poi_identity_mismatch")
        destination = valid_location(detail.get("location"))
        if destination is None:
            return missing("poi_location_missing")

        distance_raw = self.distance_tool.run({
            "origins": origin, "destination": destination, "type": "3",
        })
        distance = parse_map_payload(distance_raw)
        if distance is None or tool_result_metadata(distance_raw)["status"] == "error_text":
            return missing("distance_query_failed")
        rows = distance.get("results")
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            return missing("distance_result_missing")
        row = rows[0]
        if row.get("origin_id") not in (1, "1") or row.get("dest_id") not in (1, "1"):
            return missing("distance_identity_mismatch")
        value = row.get("distance")
        # 不把空值、布尔值、带单位文本或错误哨兵当成真实距离。
        if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
            return missing("distance_value_invalid")

        payload["homescope_subway_evidence"] = {
            "status": "verified", "poi_id": poi["id"],
            "distance_meters": int(value), "distance_type": "walking",
            "selection": "first_matching_subway_poi_not_guaranteed_nearest",
        }
        return json.dumps(payload, ensure_ascii=False)
