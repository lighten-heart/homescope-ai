"""区分地图工具指令和最终结果，不把工具参数误当成业务JSON。"""

import json
import re


def parse_map_tool_calls(text: str) -> list[dict]:
    """用JSON解码器读取参数，允许数组及字符串中的右方括号。"""
    decoder = json.JSONDecoder()
    calls = []
    consumed_until = 0
    for match in re.finditer(r"\[TOOL_CALL:\s*([A-Za-z0-9_]+)\s*:\s*", text):
        if match.start() < consumed_until:
            continue
        try:
            parameters, end = decoder.raw_decode(text, match.end())
        except ValueError:
            continue
        if not isinstance(parameters, dict):
            continue
        closing = end
        while closing < len(text) and text[closing].isspace():
            closing += 1
        if closing >= len(text) or text[closing] != "]":
            continue
        consumed_until = closing + 1
        calls.append({
            "tool_name": match.group(1),
            "parameters": json.dumps(parameters, ensure_ascii=False),
            "original": text[match.start():consumed_until],
        })
    return calls


def _decode_reply(raw_output):
    text = raw_output.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except ValueError:
        return None


def _failure(data: dict) -> bool:
    return (
        "error" in data
        or data.get("success") is False
        or data.get("status") in ("error", "failed", "failure")
    )


def _tool_instruction(item, tool_names):
    if not isinstance(item, dict):
        return None
    function = item.get("function", item)
    if not isinstance(function, dict):
        return None
    name = function.get("name", function.get("tool", function.get("tool_name")))
    if not isinstance(name, str):
        return None
    # 只兼容已注册的高德工具，不执行任意名称或代码。
    if name not in tool_names and "amap_" + name in tool_names:
        name = "amap_" + name
    if name not in tool_names:
        return None
    parameters = function.get("arguments", function.get("parameters"))
    if isinstance(parameters, str):
        try:
            parameters = json.loads(parameters)
        except ValueError:
            return None
    if not isinstance(parameters, dict):
        return None
    return f"[TOOL_CALL:{name}:{json.dumps(parameters, ensure_ascii=False)}]"


def normalize_map_reply(raw_output, tool_names=()):
    """返回(回复, 固定分类)，不记录回复正文；不补充任何地图事实。"""
    if not isinstance(raw_output, str):
        return raw_output, "unexpected_type"
    if "[TOOL_CALL:" in raw_output:
        calls = parse_map_tool_calls(raw_output)
        if calls:
            return raw_output, "tool_call"
        return raw_output, "invalid_tool_call"

    data = _decode_reply(raw_output)
    if data is None:
        return raw_output, "text"
    required = {"work_location", "candidates"}
    if isinstance(data, dict):
        if _failure(data):
            if "error" in data:
                return raw_output, "error"
            return '{"error":{"code":"map_collection_failed"}}', "error"
        if required <= data.keys():
            return raw_output, "result"
        # 常见的响应包络只去掉外层，字段值仍由Pydantic校验。
        for key in ("data", "result"):
            nested = data.get(key)
            if isinstance(nested, dict) and _failure(nested):
                return '{"error":{"code":"map_collection_failed"}}', "error"
            if isinstance(nested, dict) and required <= nested.keys():
                return json.dumps(nested, ensure_ascii=False), "wrapped_result"
        if "tool_calls" in data:
            instructions = data["tool_calls"]
        elif "function_call" in data:
            instructions = [data["function_call"]]
        else:
            instructions = [data]
    elif isinstance(data, list):
        instructions = data
    else:
        return raw_output, "unexpected_json"

    if isinstance(instructions, list) and instructions:
        normalized = [_tool_instruction(item, set(tool_names)) for item in instructions]
        # 批次中有任何未知/非法指令都不部分执行，以免丢失任务。
        if all(normalized):
            return "\n".join(normalized), "json_tool_call"
    return raw_output, "unexpected_json"
