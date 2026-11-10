"""候选区域地图增强测试。"""

from app.models.schemas import (
    Location,
    MapCandidateEnrichment,
    MapEnrichmentResult,
)
from app.services.candidate_enrichment_service import (
    apply_map_enrichment,
)
from app.services.candidate_service import (
    CandidateService,
)


def test_apply_map_enrichment() -> None:
    """高德数据应覆盖模拟地理数据。"""

    candidates = CandidateService().list_candidates(
        "北京"
    )

    first_candidate = candidates[0]

    enrichment = MapEnrichmentResult(
        work_location=Location(
            longitude=116.30,
            latitude=39.98,
        ),
        candidates=[
            MapCandidateEnrichment(
                candidate_id=candidate.id,
                location=candidate.location,
                commute_minutes=(
                    20
                    if candidate.id == first_candidate.id
                    else candidate.commute_minutes
                ),
                route_distance_meters=10000,
                subway_distance_meters=(
                    candidate.subway_distance_meters
                ),
                facilities=candidate.facilities,
                evidence=["测试证据"],
            )
            for candidate in candidates
        ],
    )

    result = apply_map_enrichment(
        candidates=candidates,
        enrichment=enrichment,
    )

    assert result[0].commute_minutes == 20
    assert result[0].data_source == "hybrid"

    # 原对象没有被直接修改。
    assert (
        first_candidate.commute_minutes
        != result[0].commute_minutes
    )
    assert first_candidate.data_source == "mock"


def test_map_enrichment_normalizes_amap_formats() -> None:
    """高德常见字符串和POI格式应被规范化。"""

    result = MapEnrichmentResult.model_validate(
        {
            "work_location": "116.30,39.98",
            "candidates": [
                {
                    "candidate_id": "beijing-area-a",
                    "location": {
                        "location": "116.31,40.07",
                    },
                    "commute_minutes": "1小时5分钟",
                    "route_distance_meters": "15.2公里",
                    "subway_distance_meters": "680米",
                    "facilities": [
                        {"name": "地铁站"},
                        {"name": "超市"},
                    ],
                    "evidence": "公交65分钟，附近有地铁站",
                    "source": "高德地图MCP",
                }
            ],
        }
    )

    candidate = result.candidates[0]

    assert result.work_location.longitude == 116.30
    assert candidate.location.latitude == 40.07
    assert candidate.commute_minutes == 65
    assert candidate.route_distance_meters == 15200
    assert candidate.subway_distance_meters == 680
    assert candidate.facilities == ["地铁站", "超市"]
    assert candidate.source == "amap_mcp"
