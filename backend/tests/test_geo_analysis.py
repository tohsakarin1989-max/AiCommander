"""
地理分析服务测试
"""
import pytest
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.case import Case
from app.services.geo_analysis_service import GeoAnalysisService
from app.utils.geo import (
    haversine_km,
    bounding_box,
    calculate_bearing,
    calculate_center,
    destination_point,
    create_grid_key,
    km_to_deg,
)


class TestHaversine:
    """Haversine 距离计算测试"""

    def test_same_point_returns_zero(self):
        """相同点距离为 0"""
        dist = haversine_km(39.9, 116.4, 39.9, 116.4)
        assert dist == 0.0

    def test_known_distance(self):
        """已知距离验证（北京到上海约 1068 公里）"""
        # 北京: 39.9042, 116.4074
        # 上海: 31.2304, 121.4737
        dist = haversine_km(39.9042, 116.4074, 31.2304, 121.4737)
        assert 1060 < dist < 1080  # 允许误差

    def test_short_distance(self):
        """短距离计算（约 111 米 = 0.001 度纬度）"""
        dist = haversine_km(39.9, 116.4, 39.901, 116.4)
        assert 0.1 < dist < 0.12  # 约 111 米


class TestBoundingBox:
    """边界框计算测试"""

    def test_bounding_box_center(self):
        """边界框以给定点为中心"""
        min_lat, max_lat, min_lon, max_lon = bounding_box(39.9, 116.4, 1.0)
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2
        assert abs(center_lat - 39.9) < 0.0001
        assert abs(center_lon - 116.4) < 0.0001

    def test_bounding_box_contains_radius(self):
        """边界框应包含指定半径内的所有点"""
        lat, lon, radius_km = 39.9, 116.4, 1.0
        min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, radius_km)

        # 边界框对角线长度应大于直径
        diagonal = haversine_km(min_lat, min_lon, max_lat, max_lon)
        assert diagonal >= radius_km * 2


class TestBearing:
    """方向角计算测试"""

    def test_bearing_north(self):
        """正北方向应为 0 度"""
        bearing = calculate_bearing(39.9, 116.4, 40.0, 116.4)
        assert abs(bearing - 0) < 1  # 允许 1 度误差

    def test_bearing_east(self):
        """正东方向应为 90 度"""
        bearing = calculate_bearing(39.9, 116.4, 39.9, 116.5)
        assert abs(bearing - 90) < 1

    def test_bearing_south(self):
        """正南方向应为 180 度"""
        bearing = calculate_bearing(40.0, 116.4, 39.9, 116.4)
        assert abs(bearing - 180) < 1

    def test_bearing_west(self):
        """正西方向应为 270 度"""
        bearing = calculate_bearing(39.9, 116.5, 39.9, 116.4)
        assert abs(bearing - 270) < 1


class TestCenter:
    """中心点计算测试"""

    def test_center_single_point(self):
        """单点的中心是自身"""
        center = calculate_center([(39.9, 116.4)])
        assert center == (39.9, 116.4)

    def test_center_two_points(self):
        """两点的中心是中点"""
        center = calculate_center([(39.0, 116.0), (40.0, 117.0)])
        assert abs(center[0] - 39.5) < 0.0001
        assert abs(center[1] - 116.5) < 0.0001

    def test_center_empty_raises(self):
        """空列表应抛出异常"""
        with pytest.raises(ValueError):
            calculate_center([])


class TestDestinationPoint:
    """目标点计算测试"""

    def test_destination_north(self):
        """向北移动 111km 约等于 1 度纬度"""
        dest = destination_point(39.0, 116.0, 0, 111)  # 向北
        assert abs(dest[0] - 40.0) < 0.1  # 约 1 度纬度误差
        assert abs(dest[1] - 116.0) < 0.01  # 经度基本不变

    def test_destination_roundtrip(self):
        """往返应回到原点附近"""
        dest1 = destination_point(39.9, 116.4, 45, 10)
        dest2 = destination_point(dest1[0], dest1[1], 225, 10)  # 反向
        assert abs(dest2[0] - 39.9) < 0.01
        assert abs(dest2[1] - 116.4) < 0.01


class TestGridKey:
    """网格键计算测试"""

    def test_grid_key_basic(self):
        """基本网格键计算"""
        key = create_grid_key(40.0, 116.0, 0.1)
        assert key == (400, 1160)

    def test_grid_key_same_grid(self):
        """相近点应在同一网格"""
        key1 = create_grid_key(39.95, 116.45, 0.1)
        key2 = create_grid_key(39.96, 116.46, 0.1)
        assert key1 == key2

    def test_grid_key_different_grids(self):
        """远离点应在不同网格"""
        key1 = create_grid_key(39.0, 116.0, 0.1)
        key2 = create_grid_key(40.0, 117.0, 0.1)
        assert key1 != key2


class TestKmToDeg:
    """公里转度数测试"""

    def test_km_to_deg_latitude(self):
        """111km 约等于 1 度纬度"""
        deg = km_to_deg(111)
        assert abs(deg - 1.0) < 0.01

    def test_km_to_deg_longitude(self):
        """经度转换受纬度影响"""
        deg_eq = km_to_deg(111, for_longitude=True, at_latitude=0)
        deg_45 = km_to_deg(111, for_longitude=True, at_latitude=45)
        # 纬度越高，同样公里数对应的经度越大
        assert deg_45 > deg_eq


class TestGeoAnalysisService:
    """地理分析服务测试"""

    def test_get_all_cases_with_geo_empty(self, db_session: Session):
        """空数据库返回空列表"""
        cases = GeoAnalysisService.get_all_cases_with_geo(db_session)
        assert cases == []

    def test_get_all_cases_with_geo_filters_null(self, db_session: Session):
        """过滤掉无坐标的案件"""
        # 添加一个有坐标的案件
        case_with_geo = Case(
            case_number="GEO-001",
            occurred_time=datetime(2025, 1, 1, 10, 0, 0),
            latitude=39.9,
            longitude=116.4,
            status="pending",
        )
        # 添加一个无坐标的案件
        case_without_geo = Case(
            case_number="NO-GEO-001",
            occurred_time=datetime(2025, 1, 1, 10, 0, 0),
            latitude=None,
            longitude=None,
            status="pending",
        )
        db_session.add_all([case_with_geo, case_without_geo])
        db_session.commit()

        cases = GeoAnalysisService.get_all_cases_with_geo(db_session)
        assert len(cases) == 1
        assert cases[0].case_number == "GEO-001"

    def test_find_hotspots_insufficient_cases(self, db_session: Session):
        """案件数量不足时返回空列表"""
        # 只添加 2 个案件，低于 min_cases=3
        for i in range(2):
            db_session.add(
                Case(
                    case_number=f"HOT-{i}",
                    occurred_time=datetime(2025, 1, 1, 10, 0, 0),
                    latitude=39.9 + i * 0.001,
                    longitude=116.4,
                    status="pending",
                )
            )
        db_session.commit()

        hotspots = GeoAnalysisService.find_hotspots(db_session, radius_km=1.0, min_cases=3)
        assert hotspots == []

    def test_find_hotspots_zero_radius_returns_empty(self, db_session: Session):
        """半径为 0 时不应触发网格除零错误"""
        for i in range(3):
            db_session.add(
                Case(
                    case_number=f"ZERO-RADIUS-{i}",
                    occurred_time=datetime(2025, 1, 1, 10, 0, 0),
                    latitude=39.9 + i * 0.001,
                    longitude=116.4,
                    status="pending",
                )
            )
        db_session.commit()

        hotspots = GeoAnalysisService.find_hotspots(db_session, radius_km=0, min_cases=2)
        assert hotspots == []

    def test_find_hotspots_detects_cluster(self, db_session: Session, sample_cases_with_geo):
        """检测到聚集的案件热点"""
        hotspots = GeoAnalysisService.find_hotspots(
            db_session, radius_km=1.0, min_cases=3
        )
        # 前 5 个案件应该形成一个热点
        assert len(hotspots) >= 1
        assert hotspots[0]["case_count"] >= 3

    def test_find_hotspots_excludes_distant(self, db_session: Session, sample_cases_with_geo):
        """远离的案件不应被归入热点"""
        hotspots = GeoAnalysisService.find_hotspots(
            db_session, radius_km=0.5, min_cases=3
        )
        if hotspots:
            # 远离的案件（GEO-20250101-099）不应在任何热点中
            for hotspot in hotspots:
                assert "GEO-20250101-099" not in [c["case_number"] for c in hotspot["cases"]]

    def test_analyze_serial_cases_empty(self, db_session: Session):
        """空数据库返回空串案列表"""
        serial = GeoAnalysisService.analyze_serial_cases(db_session)
        assert serial == []

    def test_analyze_serial_cases_finds_group(self, db_session: Session, sample_cases_with_geo):
        """检测时空接近的串案组"""
        serial = GeoAnalysisService.analyze_serial_cases(
            db_session,
            max_distance_km=5.0,
            time_window_days=30,
        )
        # 应该检测到串案组
        assert len(serial) >= 1

    def test_analyze_geographic_patterns_insufficient(self, db_session: Session):
        """案件不足时返回提示信息"""
        # 只添加 1 个案件
        db_session.add(
            Case(
                case_number="PAT-001",
                occurred_time=datetime(2025, 1, 1, 10, 0, 0),
                latitude=39.9,
                longitude=116.4,
                status="pending",
            )
        )
        db_session.commit()

        patterns = GeoAnalysisService.analyze_geographic_patterns(db_session)
        assert patterns["total_cases"] == 1
        assert "message" in patterns

    def test_analyze_geographic_patterns_calculates_bounds(
        self, db_session: Session, sample_cases_with_geo
    ):
        """计算地理边界"""
        patterns = GeoAnalysisService.analyze_geographic_patterns(db_session)
        bounds = patterns.get("geographic_bounds", {})

        assert "min_latitude" in bounds
        assert "max_latitude" in bounds
        assert bounds["min_latitude"] < bounds["max_latitude"]
