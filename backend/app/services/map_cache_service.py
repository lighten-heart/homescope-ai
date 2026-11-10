"""地图增强结果的业务缓存。"""

import hashlib
import json
from functools import lru_cache

from app.core.config import get_settings
from app.core.ttl_cache import TTLCache
from app.models.schemas import (
    CandidateArea,
    HousingDecisionRequest,
    MapEnrichmentResult,
)

class MapCacheService:
    """缓存地图Agent已经完成校验的结果。"""

    def __init__(
        self,
        ttl_seconds: int,
        max_entries: int = 128,
        namespace: str = "map-enrichment-v3-deterministic",
    ) -> None:
        self.namespace = namespace

        self._cache: TTLCache[
            str,
            MapEnrichmentResult,
        ] = TTLCache(
            ttl_seconds=ttl_seconds,
            max_entries=max_entries,
        )

    def build_key(
        self,
        request: HousingDecisionRequest,
        candidates: list[CandidateArea],
    ) -> str:
        """只使用影响地图采集结果的输入构造缓存键。"""

        key_data = {
            "namespace": self.namespace,
            "city": request.city,
            "work_address": request.work_address,
            "transportation": request.preferred_transportation,
            "facilities": sorted(set(request.preferred_facilities)),
            "candidates": sorted(
                [
                    {
                        "id": candidate.id,
                        "name": candidate.name,
                        "address": candidate.address,
                    }
                    for candidate in candidates
                ],
                key=lambda item: item["id"],
            ),
        }

        serialized = json.dumps(
            key_data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest()

    def get(
        self,
        key: str,
    ) -> MapEnrichmentResult | None:
        result = self._cache.get(key)

        if result is None:
            return None

        # 调用者拿到副本，避免修改共享缓存对象。
        return result.model_copy(deep=True)

    def set(
        self,
        key: str,
        value: MapEnrichmentResult,
    ) -> None:
        # 写入时也保存副本，避免调用者随后修改原对象。
        self._cache.set(
            key,
            value.model_copy(deep=True),
        )

    def clear(self) -> None:
        self._cache.clear()

@lru_cache
def get_map_cache_service() -> MapCacheService:
    """返回地图缓存服务。"""

    settings = get_settings()

    # 模型或MCP版本配置改变时使用不同的缓存命名空间。
    # 如果以后修改地图提示词/输出含义，也应升级map-enrichment-v3-deterministic。
    namespace = "|".join(
        [
            "map-enrichment-v3-deterministic",
            settings.llm_provider,
            settings.llm_model_id,
            settings.amap_mcp_package,
        ]
    )

    return MapCacheService(
        ttl_seconds=settings.map_cache_ttl_seconds,
        max_entries=settings.map_cache_max_entries,
        namespace=namespace,
    )