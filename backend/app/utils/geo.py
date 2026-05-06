"""
地理计算工具模块
提供经纬度距离计算、方向角、网格索引等通用地理函数
"""
import math
from typing import Tuple, List, Dict, Any


# 地球半径（公里）
EARTH_RADIUS_KM = 6371.0

# 1度纬度约等于的公里数
DEG_TO_KM = 111.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    计算两点之间的球面距离（单位：公里）
    使用 Haversine 公式
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def bounding_box(lat: float, lon: float, radius_km: float) -> Tuple[float, float, float, float]:
    """
    根据中心点和半径（公里）计算近似经纬度边界框
    返回 (min_lat, max_lat, min_lon, max_lon)
    """
    delta_lat = radius_km / DEG_TO_KM
    delta_lon = radius_km / (DEG_TO_KM * math.cos(math.radians(lat)) or 1e-6)

    return (
        lat - delta_lat,
        lat + delta_lat,
        lon - delta_lon,
        lon + delta_lon,
    )


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    计算从点1到点2的方向角（方位角）

    Args:
        lat1, lon1: 起点坐标
        lat2, lon2: 终点坐标

    Returns:
        方向角（0-360度，0为正北，顺时针增加）
    """
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)

    y = math.sin(dlon) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)
    bearing = math.degrees(math.atan2(y, x))

    return (bearing + 360) % 360


def calculate_center(points: List[Tuple[float, float]]) -> Tuple[float, float]:
    """
    计算多个点的几何中心

    Args:
        points: 坐标列表 [(lat1, lon1), (lat2, lon2), ...]

    Returns:
        中心点坐标 (center_lat, center_lon)
    """
    if not points:
        raise ValueError("点列表不能为空")

    total_lat = sum(p[0] for p in points)
    total_lon = sum(p[1] for p in points)
    n = len(points)

    return (total_lat / n, total_lon / n)


def destination_point(lat: float, lon: float, bearing_deg: float, distance_km: float) -> Tuple[float, float]:
    """
    从给定点沿指定方向移动一定距离后的目标点

    Args:
        lat, lon: 起点坐标
        bearing_deg: 方向角（度）
        distance_km: 距离（公里）

    Returns:
        目标点坐标 (lat, lon)
    """
    lat_rad = math.radians(lat)
    bearing_rad = math.radians(bearing_deg)
    angular_dist = distance_km / EARTH_RADIUS_KM

    lat_dest = math.asin(
        math.sin(lat_rad) * math.cos(angular_dist) +
        math.cos(lat_rad) * math.sin(angular_dist) * math.cos(bearing_rad)
    )
    lon_dest = math.radians(lon) + math.atan2(
        math.sin(bearing_rad) * math.sin(angular_dist) * math.cos(lat_rad),
        math.cos(angular_dist) - math.sin(lat_rad) * math.sin(lat_dest)
    )

    return (math.degrees(lat_dest), math.degrees(lon_dest))


def create_grid_key(lat: float, lon: float, grid_size_deg: float) -> Tuple[int, int]:
    """
    根据坐标和网格大小计算网格键

    Args:
        lat, lon: 坐标
        grid_size_deg: 网格大小（度）

    Returns:
        网格键 (grid_x, grid_y)
    """
    return (int(lat / grid_size_deg), int(lon / grid_size_deg))


def km_to_deg(km: float, for_longitude: bool = False, at_latitude: float = 0.0) -> float:
    """
    将公里转换为度数

    Args:
        km: 距离（公里）
        for_longitude: 是否用于经度（受纬度影响）
        at_latitude: 参考纬度（仅用于经度转换）

    Returns:
        度数
    """
    if for_longitude:
        return km / (DEG_TO_KM * math.cos(math.radians(at_latitude)) or 1e-6)
    return km / DEG_TO_KM


