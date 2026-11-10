"""业务Agent公共工具。"""
import json

from app.models.schemas import (
    CandidateArea,
    SpecialistOpinion,
)

class SpecialistAgentError(RuntimeError):
    """专业Agent执行或解析失败。"""

def extract_json_object(
    raw_output: str,
) -> dict[str, object]:
    """从大模型文本中提取JSON对象。"""

    text = raw_output.strip()

    if "```json" in text:
        start = text.find("```json") + len("```json")
        end = text.find("```", start)

        if end != -1:
            text = text[start:end].strip()

    elif "```" in text:
        start = text.find("```") + len("```")
        end = text.find("```", start)

        if end != -1:
            text = text[start:end].strip()

    json_start = text.find("{")
    json_end = text.rfind("}")

    if (
        json_start == -1
        or json_end == -1
        or json_end < json_start
    ):
        raise SpecialistAgentError(
            "Agent响应中没有找到JSON对象"
        )

    json_text = text[json_start:json_end + 1]

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise SpecialistAgentError(
            "Agent返回的JSON格式不正确"
        ) from exc

    if not isinstance(data, dict):
        raise SpecialistAgentError(
            "Agent必须返回JSON对象"
        )

    return data

def validate_candidate_ids(
    opinions: list[SpecialistOpinion],
    candidates: list[CandidateArea],
) -> None:
    """检查Agent是否分析了所有候选区域。

    防止大模型遗漏候选区域、重复分析，
    或者凭空生成不存在的candidate_id。
    """
    expected_ids = {
        candidate.id
        for candidate in candidates
    }

    actual_ids = [
        opinion.candidate_id
        for opinion in opinions
    ]

    if len(actual_ids) != len(set(actual_ids)):
        raise SpecialistAgentError(
            "Agent返回了重复的candidate_id"
        )

    if set(actual_ids) != expected_ids:
        raise SpecialistAgentError(
            "Agent返回的候选区域与输入不一致"
        )