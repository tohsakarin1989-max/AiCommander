import math
from typing import Tuple


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  """
  计算两点之间的球面距离（单位：公里）
  使用 Haversine 公式，假设地球半径约 6371km
  """
  R = 6371.0
  phi1 = math.radians(lat1)
  phi2 = math.radians(lat2)
  d_phi = math.radians(lat2 - lat1)
  d_lambda = math.radians(lon2 - lon1)

  a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
  c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
  return R * c


def bounding_box(lat: float, lon: float, radius_km: float) -> Tuple[float, float, float, float]:
  """
  根据中心点和半径（公里）计算近似经纬度边界框：
  返回 (min_lat, max_lat, min_lon, max_lon)
  """
  # 1 度纬度约等于 111km
  delta_lat = radius_km / 111.0
  # 1 度经度约等于 111km * cos(lat)
  delta_lon = radius_km / (111.0 * math.cos(math.radians(lat)) or 1e-6)

  return (
    lat - delta_lat,
    lat + delta_lat,
    lon - delta_lon,
    lon + delta_lon,
  )


