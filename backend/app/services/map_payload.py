"""缩减模型不使用的路线几何数据，不截断JSON，不修改路线数值。"""
import json

ROUTE_TOOLS = {
    "amap_maps_direction_transit_integrated", "amap_maps_direction_walking",
    "amap_maps_direction_driving", "amap_maps_bicycling",
}


def compact_route_result(tool_name: str, result):
    """只处理已知路线工具的JSON；未知格式、错误文本保持原样。

    删除polyline绘图坐标串，所有路线选项、duration、distance、车站、
    换乘、步行段与错误字段保留。该副本仅用于LLM分析，不用于绘制地图。
    """
    if tool_name not in ROUTE_TOOLS or not isinstance(result, str):
        return result
    prefix, payload = "", result
    # HelloAgents MCPTool在JSON前加一行“工具 ... 执行结果”。
    if result.startswith("工具 '"):
        prefix, sep, payload = result.partition("\n")
        if not sep:
            return result
        prefix += "\n"
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return result
    if not isinstance(data, (dict, list)):
        return result

    def prune(value):
        if isinstance(value, dict):
            return {key: prune(item) for key, item in value.items() if key != "polyline"}
        if isinstance(value, list):
            return [prune(item) for item in value]
        return value

    try:
        return prefix + json.dumps(prune(data), ensure_ascii=False, separators=(",", ":"))
    except RecursionError:
        return result
