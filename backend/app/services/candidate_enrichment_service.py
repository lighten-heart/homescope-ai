"""此服务作用为将高德地图数据合并到候选区域。"""
from app.models.schemas import (
    CandidateArea,
    MapEnrichmentResult,
)
def apply_map_enrichment(
    candidates: list[CandidateArea],
    enrichment: MapEnrichmentResult,
) -> list[CandidateArea]:
    """使用高德数据生成新的候选区域列表。

    不直接修改原对象，避免产生隐藏副作用。
    """

    enrichment_by_id = {
        item.candidate_id: item
        for item in enrichment.candidates
    }

    enriched_candidates: list[CandidateArea] = []

    for candidate in candidates:
        map_data = enrichment_by_id.get(candidate.id)

        if map_data is None:
            raise ValueError(
                f"缺少候选区域{candidate.id}的地图数据"
            )

        # 真实地图已完整查询设施，应覆盖模拟设施。
        # 合并两者会把“真实查询未返回”的项目重新加入评分。
        facilities = list(dict.fromkeys(map_data.facilities))

        enriched_candidate = candidate.model_copy(
            update={
                "location": map_data.location,
                "commute_minutes": (
                    map_data.commute_minutes
                ),
                "subway_distance_meters": (
                    map_data
                    .subway_distance_meters
                ),
                "facilities": facilities,
                "data_source": "hybrid",
            }
        )

        enriched_candidates.append(
            enriched_candidate
        )

    return enriched_candidates
