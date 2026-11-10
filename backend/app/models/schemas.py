"""HomeScope AI数据模型。

模型层负责定义数据结构、字段类型和校验规则，

不负责读取数据库、调用地图或计算评分。
"""

import json
import math
import re
from typing import Annotated, Any, Literal
from pydantic import BaseModel, Field, field_validator


def _normalize_map_location(value: Any) -> Any:
    """把高德常见坐标格式转换成Location可校验的字典。"""

    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]

        if len(parts) == 2:
            try:
                return {
                    "longitude": float(parts[0]),
                    "latitude": float(parts[1]),
                }
            except ValueError:
                return value

    if isinstance(value, (list, tuple)) and len(value) == 2:
        return {
            "longitude": value[0],
            "latitude": value[1],
        }

    if isinstance(value, dict):
        if "location" in value:
            normalized = _normalize_map_location(
                value["location"]
            )

            if isinstance(normalized, dict):
                return normalized

        if "lng" in value and "lat" in value:
            return {
                "longitude": value["lng"],
                "latitude": value["lat"],
            }

    return value


def _extract_number(value: Any) -> float | None:
    """从数值或带单位文本中提取第一个数字。"""

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)

        if match is not None:
            return float(match.group())

    return None


def _normalize_minutes(value: Any) -> Any:
    """把秒、分钟文本或小时文本转换成整数分钟。"""

    if isinstance(value, str) and "小时" in value:
        hour_match = re.search(
            r"(\d+(?:\.\d+)?)\s*小时",
            value,
        )
        minute_match = re.search(
            r"(\d+(?:\.\d+)?)\s*分",
            value,
        )
        hours = (
            float(hour_match.group(1))
            if hour_match is not None
            else 0.0
        )
        minutes = (
            float(minute_match.group(1))
            if minute_match is not None
            else 0.0
        )
        return math.ceil(hours * 60 + minutes)

    number = _extract_number(value)

    if number is None:
        return value

    if isinstance(value, str) and "秒" in value:
        number /= 60

    return math.ceil(number)


def _normalize_distance_meters(value: Any) -> Any:
    """把米或公里文本转换成整数米。"""

    number = _extract_number(value)

    if number is None:
        return value

    if isinstance(value, str):
        normalized_text = value.lower()

        if "公里" in normalized_text or "km" in normalized_text:
            number *= 1000

    return math.ceil(number)


def _normalize_string_list(value: Any) -> Any:
    """把文本或POI对象转换成字符串列表。"""

    if isinstance(value, str):
        return [
            item.strip()
            for item in re.split(r"[,，、;；]", value)
            if item.strip()
        ]

    if isinstance(value, list):
        normalized: list[str] = []

        for item in value:
            if isinstance(item, str):
                normalized.append(item)
            elif isinstance(item, dict):
                display_value = (
                    item.get("name")
                    or item.get("type")
                )
                normalized.append(
                    str(display_value)
                    if display_value is not None
                    else json.dumps(
                        item,
                        ensure_ascii=False,
                    )
                )
            else:
                normalized.append(str(item))

        return normalized

    return value

class HousingDecisionRequest(BaseModel):
    """用户提交的搬家选址需求。

    FastAPI收到JSON后，会自动尝试将它转换成这个模型。
    如果字段缺失、类型错误或数值超出范围，将直接返回HTTP 422。
    """
    # BaseModel提供類型檢查、參數驗證、JSON轉換、自動生成文檔的功能
    # Annotated用於給字段類型添加驗證規則、描述信息、示例等額外信息
    city: Annotated[
        str,
        Field(
            min_length=1,
            max_length=40,
            description="准备租房的城市",
            examples=["北京"],
        ),
    ]

    work_address: Annotated[
        str,
        Field(
            min_length=1,
            max_length=200,
            description="工作地点或通勤目的地",
            examples=["北京市海淀区中关村"],
        ),
    ]

    monthly_budget: Annotated[
        int,
        Field(
            ge=500,
            le=100_000,
            description="每月租金预算，单位为元",
            examples=[5000],
        ),
    ]

    max_commute_minutes: Annotated[
        int,
        Field(
            ge=5,
            le=240,
            description="能够接受的最大单程通勤时间",
            examples=[45],
        ),
    ]

    # default_factory=list表示每个请求都创建自己的新列表。
    # 不建议直接写成preferred_facilities: list[str] = []。
    preferred_facilities: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="希望附近拥有的生活设施",
        examples=[["地铁站", "健身房", "超市"]],
    )

    # Literal表示只能选择下面四个值之一。
    preferred_transportation: Literal[
        "公共交通",
        "驾车",
        "骑行",
        "步行",
    ] = "公共交通"

    free_text_input: Annotated[
        str,
        Field(
            max_length=1000,
            description="用户补充的自然语言要求",
            examples=["希望环境安静，附近最好有公园"],
        ),
    ] = ""

    @field_validator("city", "work_address", "free_text_input")
    @classmethod
    def strip_text(cls, value: str) -> str:
        """清除文本字段首尾的空格。"""

        return value.strip()

    @field_validator("preferred_facilities")
    @classmethod
    def normalize_facilities(cls, values: list[str]) -> list[str]:
        """清除空设施、首尾空格和重复项目。

        dict.fromkeys可以在去重的同时保留原来的输入顺序。
        """

        cleaned_values = (
            value.strip()
            for value in values
            if value.strip()
        )

        return list(dict.fromkeys(cleaned_values))

class Location(BaseModel):
    """经纬度坐标。

    后续无论坐标来自模拟数据、数据库还是高德地图，
    都统一转换成这个结构。
    """

    longitude: Annotated[
        float,
        Field(
            ge=-180,
            le=180,
            description="经度",
            examples=[116.397],
        ),
    ]

    latitude: Annotated[
        float,
        Field(
            ge=-90,
            le=90,
            description="纬度",
            examples=[39.916],
        ),
    ]

class CandidateArea(BaseModel):
    """进入决策系统的标准化候选区域。

    数据源可以变化，但后面的评分算法只接收CandidateArea，
    不需要理解数据库或高德API的原始格式。
    """

    id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=100,
            description="候选区域唯一标识",
        ),
    ]

    city: str
    name: str
    address: str
    location: Location

    monthly_rent: Annotated[
        int,
        Field(
            ge=0,
            description="每月租金，单位为元",
        ),
    ]

    commute_minutes: Annotated[
        int,
        Field(
            ge=0,
            description="到工作地点的预计通勤时间",
        ),
    ]

    subway_distance_meters: Annotated[
        int,
        Field(
            ge=0,
            description="到所选地铁站的步行距离（米）；真实查询不保证为全局最近站",
        ),
    ]

    facilities: list[str] = Field(
        default_factory=list,
        description="区域附近的生活配套",
    )

    # Literal可以防止系统把模拟数据误认为真实数据。
    data_source: Literal[
    "mock",
    "hybrid",
    ] = "mock"


class CandidateListResponse(BaseModel):
    """候选区域列表接口响应。"""

    success: bool = True
    message: str = "候选区域查询成功"
    data: list[CandidateArea]


class ScoreBreakdown(BaseModel):
    """候选区域的分项得分。

    所有指标都转换成0～100分，
    这样不同单位的指标才能进行加权计算。
    """

    rent: float
    commute: float
    subway: float
    facilities: float


class CandidateEvaluation(BaseModel):
    """单个候选区域的完整评估结果。"""

    # 排名从1开始。
    rank: int

    # 候选区域原始信息。
    candidate: CandidateArea

    # 加权后的综合得分。
    total_score: float

    # 四个维度的详细得分。
    score_breakdown: ScoreBreakdown

    # 推荐该区域的原因。
    reasons: list[str] = Field(default_factory=list)

    # 该区域存在的风险。
    warnings: list[str] = Field(default_factory=list)


class HousingDecisionResult(BaseModel):
    """选址决策的核心业务结果。"""

    recommendation: str

    # 返回实际使用的权重，让结果更容易解释。
    weights: dict[str, float]

    # 排序后的候选区域。
    evaluations: list[CandidateEvaluation]

    # 提醒用户当前数据的真实性。
    disclaimer: str


class HousingDecisionResponse(BaseModel):
    """选址评估API的统一响应。"""

    success: bool = True
    message: str = "选址评估完成"
    data: HousingDecisionResult


class LLMStatusResponse(BaseModel):
    """LLM配置状态响应。

    出于安全考虑，该模型绝不能返回API Key。
    """

    enabled: bool
    configured: bool
    provider: str
    model_id: str

class LLMChatRequest(BaseModel):
    """最小LLM聊天请求。"""

    message: Annotated[
        str,
        Field(
            min_length=1,
            max_length=2000,
            description="发送给大模型的测试消息",
            examples=["请用一句话介绍HomeScope AI"],
        ),
    ]

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        """清除消息首尾空格。"""

        return value.strip()

class LLMChatResponse(BaseModel):
    """最小LLM聊天响应。"""

    success: bool = True
    provider: str
    model_id: str
    answer: str

# 定义pydantic模型的原因：大模型返回的是不可信文本，可能出现少字段、字段名称错误等问题，不能直接把LLM输出的内容交给Agent，必须经过校验后才能进入系统
class RequirementAnalysis(BaseModel):
    """需求分析Agent输出的结构化结果。"""
    city: str
    work_address: str
    monthly_budget: int
    max_commute_minutes: int

    preferred_transportation: Literal[
        "公共交通",
        "驾车",
        "骑行",
        "步行",
    ]

    # 用户明确表示“必须拥有”的设施。
    required_facilities: list[str] = Field(
        default_factory=list
    )

    # 用户表示“希望、最好拥有”的设施。
    optional_facilities: list[str] = Field(
        default_factory=list
    )

    # 例如：安静、适合养宠物、生活便利。
    lifestyle_tags: list[str] = Field(
        default_factory=list
    )

    # 不能违反的条件，例如预算和最大通勤时间。
    hard_constraints: list[str] = Field(
        default_factory=list
    )

    # 可以用于排序，但不是绝对限制的偏好。
    soft_preferences: list[str] = Field(
        default_factory=list
    )

    # 信息不足时，Agent需要向用户追问的问题。
    clarification_questions: list[str] = Field(
        default_factory=list
    )

    # 对用户整体需求的简短总结。
    summary: str

class RequirementAnalysisResponse(BaseModel):
    """需求分析接口响应。"""

    success: bool = True
    message: str = "需求分析完成"
    data: RequirementAnalysis

class SpecialistOpinion(BaseModel):
    """专业Agent对单个候选区域的分析意见。"""

    candidate_id: str

    risk_level: Literal[
        "低",
        "中",
        "高",
    ]

    advantages: list[str] = Field(
        default_factory=list
    )

    risks: list[str] = Field(
        default_factory=list
    )

    conclusion: str

class CommuteAnalysisResult(BaseModel):
    """通勤分析Agent的完整输出。"""

    agent_name: Literal["commute_agent"] = (
        "commute_agent"
    )

    opinions: list[SpecialistOpinion]

class FacilityAnalysisResult(BaseModel):
    """配套设施Agent的完整输出。"""

    agent_name: Literal["facility_agent"] = (
        "facility_agent"
    )

    opinions: list[SpecialistOpinion]

class MultiAgentSpecialistResult(BaseModel):
    """两个专业Agent的聚合结果。"""

    commute_analysis: CommuteAnalysisResult
    facility_analysis: FacilityAnalysisResult

    # 是否使用了降级结果。
    degraded: bool = False

    # 具体发生了哪些降级。
    degradation_warnings: list[str] = Field(
        default_factory=list
    )

    # 每个阶段的执行时间，单位毫秒。
    stage_durations_ms: dict[str, float] = Field(
        default_factory=dict
    )

    # 哪些数据来自缓存。
    cache_hits: list[str] = Field(
        default_factory=list
    )

class MultiAgentSpecialistResponse(BaseModel):
    """专业Agent协作接口响应。"""

    success: bool = True
    message: str = "专业Agent分析完成"
    data: MultiAgentSpecialistResult

class MapCandidateEnrichment(BaseModel):
    """单个候选区域的高德地图增强数据。"""

    candidate_id: str

    location: Location

    commute_minutes: Annotated[
        int,
        Field(ge=0),
    ]

    route_distance_meters: Annotated[
        int,
        Field(ge=0),
    ]

    subway_distance_meters: Annotated[
        int,
        Field(ge=0),
    ]

    facilities: list[str] = Field(
        default_factory=list
    )

    # 记录地图工具返回了哪些事实证据。
    evidence: list[str] = Field(
        default_factory=list
    )

    source: Literal["amap_mcp"] = "amap_mcp"

    @field_validator("location", mode="before")
    @classmethod
    def normalize_location(cls, value: Any) -> Any:
        return _normalize_map_location(value)

    @field_validator("commute_minutes", mode="before")
    @classmethod
    def normalize_commute_minutes(cls, value: Any) -> Any:
        return _normalize_minutes(value)

    @field_validator(
        "route_distance_meters",
        "subway_distance_meters",
        mode="before",
    )
    @classmethod
    def normalize_distance(cls, value: Any) -> Any:
        return _normalize_distance_meters(value)

    @field_validator("facilities", "evidence", mode="before")
    @classmethod
    def normalize_text_list(cls, value: Any) -> Any:
        return _normalize_string_list(value)

    @field_validator("source", mode="before")
    @classmethod
    def normalize_source(cls, value: Any) -> Any:
        if value is None:
            return "amap_mcp"

        normalized = str(value).lower()

        if "amap" in normalized or "高德" in normalized:
            return "amap_mcp"

        return value

class MapEnrichmentResult(BaseModel):
    """所有候选区域的高德增强结果。"""

    work_location: Location

    candidates: list[MapCandidateEnrichment]

    @field_validator("work_location", mode="before")
    @classmethod
    def normalize_work_location(cls, value: Any) -> Any:
        return _normalize_map_location(value)

class CandidateDecisionExplanation(BaseModel):
    """综合决策Agent对单个候选区域的解释。"""

    candidate_id: str

    recommendation_level: Literal[
        "优先推荐",
        "可以考虑",
        "谨慎选择",
    ]

    explanation: str

    main_advantages: list[str] = Field(
        default_factory=list
    )

    main_tradeoffs: list[str] = Field(
        default_factory=list
    )

class DecisionNarrative(BaseModel):
    """综合决策Agent生成的自然语言解释。"""

    executive_summary: str

    candidate_explanations: list[
        CandidateDecisionExplanation
    ]

    overall_risks: list[str] = Field(
        default_factory=list
    )

    next_actions: list[str] = Field(
        default_factory=list
    )

class MultiAgentDecisionResult(BaseModel):
    """完整多Agent选址决策结果。"""

    # 最终推荐ID由确定性评分算法决定。
    recommended_candidate_id: str

    requirement_analysis: RequirementAnalysis

    specialist_analysis: MultiAgentSpecialistResult

    scoring_result: HousingDecisionResult
    
    narrative: DecisionNarrative

    # 显式跳过地图阶段时返回null，不伪造坐标或amap_mcp来源。
    map_enrichment: MapEnrichmentResult | None = None

    # 简单记录工作流经过了哪些步骤。
    pipeline_trace: list[str]

        # 每个阶段的耗时，单位毫秒。
    stage_durations_ms: dict[str, float] = Field(
        default_factory=dict,
    )

    # 整个工作流截至结果组装前的耗时。
    total_duration_ms: float = Field(
        default=0.0,
        ge=0,
    )

    # 本次工作流中哪些模块使用了缓存。
    cache_hits: list[str] = Field(
        default_factory=list,
    )

class MultiAgentDecisionResponse(BaseModel):
    """完整多Agent决策接口响应。"""

    success: bool = True
    message: str = "多Agent选址决策完成"
    data: MultiAgentDecisionResult

    # 保存成功才有ID。
    history_id: str | None = None

    # 分析成功但保存失败时，明确告知调用者。
    history_warning: str | None = None
