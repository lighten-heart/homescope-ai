"""候选区域数据服务。

服务层负责解决“数据从哪里来”，
但不负责判断哪个区域最好。
"""
from app.models.schemas import CandidateArea, Location

class CandidateService:
    """候选区域查询服务。

    当前使用北京的模拟数据。
    后续可以保持list_candidates接口不变，
    将内部实现替换成CSV、数据库或真实API。
    """
    def list_candidates(self, city: str) -> list[CandidateArea]:
        """根据城市返回候选区域。

        Args:
        city: 用户准备租房的城市。

        Returns:
            标准化后的候选区域列表。
        """
        normalized_city = city.strip()
        if normalized_city != "北京":
            return []

        return [
            CandidateArea(
                id="beijing-area-a",
                city="北京",
                name="回龙观",
                address="北京市昌平区回龙观",
                location=Location(
                    longitude=116.397,
                    latitude=39.916,
                ),
                monthly_rent=4600,
                commute_minutes=38,
                subway_distance_meters=420,
                facilities=[
                    "地铁站",
                    "健身房",
                    "超市",
                    "公园",
                ],
                data_source="mock",
            ),
            CandidateArea(
                id="beijing-area-b",
                city="北京",
                name="天通苑",
                address="北京市昌平区天通苑",
                location=Location(
                    longitude=116.407,
                    latitude=39.926,
                ),
                monthly_rent=5200,
                commute_minutes=29,
                subway_distance_meters=760,
                facilities=[
                    "地铁站",
                    "医院",
                    "商场",
                    "餐厅",
                ],
                data_source="mock",
            ),
            CandidateArea(
                id="beijing-area-c",
                city="北京",
                name="望京",
                address="北京市朝阳区望京",
                location=Location(
                    longitude=116.387,
                    latitude=39.906,
                ),
                monthly_rent=3900,
                commute_minutes=54,
                subway_distance_meters=1150,
                facilities=[
                    "学校",
                    "超市",
                    "公园",
                    "健身房",
                ],
                data_source="mock",
            ),
        ]

def get_candidate_service() -> CandidateService:
    """创建候选区域服务。

    后续FastAPI会通过Depends调用这个函数，
    将CandidateService注入API路由。
    """

    return CandidateService()