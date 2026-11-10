"""候选区域评分与排序算法。

该模块只负责业务计算，不依赖FastAPI，
也不访问数据库或外部API。
"""

from app.models.schemas import (
    CandidateArea,
    CandidateEvaluation,
    HousingDecisionRequest,
    HousingDecisionResult,
    ScoreBreakdown,
)


# 四个评分维度的默认权重。
# 所有权重之和必须等于1。
DEFAULT_WEIGHTS: dict[str, float] = {
    "rent": 0.30,
    "commute": 0.35,
    "subway": 0.20,
    "facilities": 0.15,
}

def _limit_score(value: float) -> float:
    """把分数限制在0～100之间。

    max负责防止分数低于0，
    min负责防止分数高于100。
    """

    limited_value = max(0.0, min(100.0, value))

    return round(limited_value, 2)

def _upper_bound_score(
    actual: int,
    preferred_maximum: int,
) -> float:
    """计算“不能超过某个上限”类型指标的分数。

    适用于租金和通勤时间。

    规则：
    1. 实际值不超过用户上限，得100分；
    2. 超过用户上限后，根据超出比例扣分；
    3. 最低不会低于0分。
    """

    if actual <= preferred_maximum:
        return 100.0

    over_ratio = (
        actual - preferred_maximum
    ) / preferred_maximum

    score = 100 - over_ratio * 120

    return _limit_score(score)

def _subway_score(
    distance_meters: int,
) -> float:
    """根据地铁距离计算分数。

    当前使用简单线性规则：

    0米 = 100分
    每增加20米扣1分
    2000米及以上接近0分
    """

    score = 100 - distance_meters / 20

    return _limit_score(score)

def _facility_score(
    available: list[str],
    preferred: list[str],
) -> float:
    """计算配套设施匹配率。

    例如：

    用户希望：[地铁站, 健身房]
    区域拥有：[地铁站, 超市]

    匹配1项，共2项，因此得分为50分。
    """

    # 用户没有提出设施偏好时，
    # 不应该因为缺少偏好而惩罚候选区域。
    if not preferred:
        return 100.0

    available_set = set(available)
    preferred_set = set(preferred)

    matched_facilities = (
        available_set & preferred_set
    )

    match_ratio = (
        len(matched_facilities)
        / len(preferred_set)
    )

    return _limit_score(match_ratio * 100)

def _build_reasons_and_warnings(
    candidate: CandidateArea,
    request: HousingDecisionRequest,
    facility_score: float,
) -> tuple[list[str], list[str]]:
    """生成推荐理由和风险提示。"""

    reasons: list[str] = []
    warnings: list[str] = []

    # 判断租金是否满足预算。
    if candidate.monthly_rent <= request.monthly_budget:
        reasons.append(
            f"月租未超过{request.monthly_budget}元预算"
        )
    else:
        exceeded_rent = (
            candidate.monthly_rent
            - request.monthly_budget
        )
        warnings.append(
            f"月租超出预算{exceeded_rent}元"
        )

    # 判断通勤时间是否满足限制。
    if (
        candidate.commute_minutes
        <= request.max_commute_minutes
    ):
        reasons.append(
            f"通勤时间满足"
            f"{request.max_commute_minutes}分钟限制"
        )
    else:
        exceeded_minutes = (
            candidate.commute_minutes
            - request.max_commute_minutes
        )
        warnings.append(
            f"通勤时间超过限制{exceeded_minutes}分钟"
        )

    # 暂时将800米作为地铁步行范围。
    if candidate.subway_distance_meters <= 800:
        reasons.append("步行范围内可以到达地铁站")
    else:
        warnings.append("距离地铁站较远")

    if request.preferred_facilities:
        reasons.append(
            f"偏好设施匹配度为{facility_score:.0f}%"
        )

    return reasons, warnings

def evaluate_candidates(
    request: HousingDecisionRequest,
    candidates: list[CandidateArea],
) -> HousingDecisionResult:
    """评估并排序所有候选区域。

    执行步骤：

    1. 计算四个维度的分项得分；
    2. 根据权重计算综合得分；
    3. 生成推荐理由和风险提示；
    4. 按照综合得分从高到低排序；
    5. 为每个候选区域写入排名；
    6. 使用第一名生成总体推荐。
    """

    evaluations: list[CandidateEvaluation] = []

    for candidate in candidates:
        # 第一步：计算四个维度的标准化分数。
        score_breakdown = ScoreBreakdown(
            rent=_upper_bound_score(
                actual=candidate.monthly_rent,
                preferred_maximum=request.monthly_budget,
            ),
            commute=_upper_bound_score(
                actual=candidate.commute_minutes,
                preferred_maximum=(
                    request.max_commute_minutes
                ),
            ),
            subway=_subway_score(
                candidate.subway_distance_meters
            ),
            facilities=_facility_score(
                available=candidate.facilities,
                preferred=(
                    request.preferred_facilities
                ),
            ),
        )

        # 第二步：使用加权求和计算综合得分。
        total_score = (
            score_breakdown.rent
            * DEFAULT_WEIGHTS["rent"]
            + score_breakdown.commute
            * DEFAULT_WEIGHTS["commute"]
            + score_breakdown.subway
            * DEFAULT_WEIGHTS["subway"]
            + score_breakdown.facilities
            * DEFAULT_WEIGHTS["facilities"]
        )

        total_score = round(total_score, 2)

        # 第三步：生成文字解释。
        reasons, warnings = (
            _build_reasons_and_warnings(
                candidate=candidate,
                request=request,
                facility_score=(
                    score_breakdown.facilities
                ),
            )
        )

        # rank暂时写0。
        # 完成排序后才能知道真实排名。
        evaluation = CandidateEvaluation(
            rank=0,
            candidate=candidate,
            total_score=total_score,
            score_breakdown=score_breakdown,
            reasons=reasons,
            warnings=warnings,
        )

        evaluations.append(evaluation)

    # 第四步：按照总分从高到低排序。
    evaluations.sort(
        key=lambda item: item.total_score,
        reverse=True,
    )

    # 第五步：写入从1开始的排名。
    for rank, evaluation in enumerate(
        evaluations,
        start=1,
    ):
        evaluation.rank = rank

    # 第六步：生成总体推荐。
    if evaluations:
        best_evaluation = evaluations[0]

        recommendation = (
            f"当前推荐"
            f"{best_evaluation.candidate.name}，"
            f"综合得分"
            f"{best_evaluation.total_score}分。"
        )
    else:
        recommendation = (
            "当前没有可以评估的候选区域。"
        )

    uses_hybrid_data = any(
        candidate.data_source == "hybrid"
        for candidate in candidates
    )

    if uses_hybrid_data:
        disclaimer = (
            "通勤、位置和生活配套来自高德地图MCP，"
            "租金仍为模拟数据，仅用于项目学习。"
        )
    else:
        disclaimer = (
            "当前结果基于模拟数据，"
            "仅用于项目框架和评分算法学习。"
        )
    
    return HousingDecisionResult(
        recommendation=recommendation,
        weights=DEFAULT_WEIGHTS,
        evaluations=evaluations,
        disclaimer=disclaimer,
    )