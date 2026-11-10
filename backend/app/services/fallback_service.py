"""多Agent工作流确定性降级方案。"""

from app.models.schemas import (
    CandidateDecisionExplanation,
    DecisionNarrative,
    HousingDecisionResult,
)

def build_decision_fallback(
    scoring_result: HousingDecisionResult,
) -> DecisionNarrative:
    """不调用LLM，根据评分结果生成基础解释。"""

    explanations: list[
        CandidateDecisionExplanation
    ] = []
    for evaluation in (
        scoring_result.evaluations
    ):
        if evaluation.rank == 1:
            recommendation_level = "优先推荐"
        elif evaluation.rank == 2:
            recommendation_level = "可以考虑"
        else:
            recommendation_level = "谨慎选择"

        explanation = (
            f"{evaluation.candidate.name}"
            f"综合得分为"
            f"{evaluation.total_score}分，"
            f"当前排名第{evaluation.rank}。"
        )

        explanations.append(
            CandidateDecisionExplanation(
                candidate_id=(
                    evaluation.candidate.id
                ),
                recommendation_level=(
                    recommendation_level
                ),
                explanation=explanation,
                main_advantages=(
                    evaluation.reasons
                ),
                main_tradeoffs=(
                    evaluation.warnings
                ),
            )
        )

    return DecisionNarrative(
        executive_summary=(
            scoring_result.recommendation
        ),
        candidate_explanations=explanations,
        overall_risks=[
            "综合决策Agent暂时不可用，"
            "当前说明由确定性规则生成"
        ],
        next_actions=[
            "核实真实租金",
            "查看实时通勤路线",
            "安排实地看房",
        ],
    )