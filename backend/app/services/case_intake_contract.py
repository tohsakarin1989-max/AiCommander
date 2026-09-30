"""Typed source input. Unknown is data, never an invented date or unit."""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

OIL_UNITS = frozenset({"tonne", "liter", "kg", "m3", "unknown"})
TIME_FIELDS = ("occurred_time", "occurred_from", "occurred_to", "discovered_at", "report_time")


def _date(value, zone):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("时间格式无效")
    return (value.replace(tzinfo=zone) if value.tzinfo is None else value).astimezone(timezone.utc)


def validate_geometry(geometry):
    if geometry is None:
        return
    if not isinstance(geometry, dict) or set(geometry) - {"type", "coordinates"}:
        raise ValueError("地点仅接受本地 GeoJSON 几何，不接受地址或扩展执行参数")
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    if kind not in {"Point", "LineString", "Polygon"}:
        raise ValueError("地点几何仅支持点、线、面")
    points = []
    if kind == "Point":
        points = [coords]
    elif kind == "LineString":
        if not isinstance(coords, list) or len(coords) < 2:
            raise ValueError("线至少需要两个坐标")
        points = coords
    else:
        if not isinstance(coords, list) or not coords:
            raise ValueError("区域缺少边界")
        for ring in coords:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("区域边界必须闭合且至少四个坐标")
            points.extend(ring)
    if len(points) > 5000:
        raise ValueError("地点几何超过 5000 个坐标")
    for point in points:
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            raise ValueError("坐标必须按经度、纬度组成一对数值")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) for v in point):
            raise ValueError("坐标必须为有限数值")
        if not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90:
            raise ValueError("坐标超出经纬度范围")


def normalize_intake(values: dict, existing=None) -> dict:
    """Validate merged scalar state, returning only supplied fields and inferred precision."""
    result = dict(values)

    def get(key, default=None):
        return result.get(key, getattr(existing, key, default))

    try:
        zone = ZoneInfo(get("time_timezone") or "Asia/Shanghai")
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("请选择有效时区") from exc
    for field in TIME_FIELDS:
        if field in result:
            result[field] = _date(result[field], zone)
    # New naive input is local wall time; persisted naive values are UTC (SQLite
    # drops tzinfo). Reinterpreting an unchanged field in the input zone can
    # incorrectly accept a reversed interval during a partial update.
    def merged_date(field):
        if field in result:
            return result[field]
        return _date(getattr(existing, field, None), timezone.utc)

    exact = merged_date("occurred_time")
    start, end = merged_date("occurred_from"), merged_date("occurred_to")
    if "time_precision" not in result and (existing is None or getattr(existing, "time_precision", None) is None or "occurred_time" in result or "occurred_from" in result or "occurred_to" in result):
        result["time_precision"] = "exact" if exact else "interval" if start or end else "unknown"
    precision = get("time_precision") or "unknown"
    if precision not in {"exact", "interval", "unknown"}:
        raise ValueError("时间精度仅支持精确、区间或未知")
    if precision == "exact" and (exact is None or start is not None or end is not None):
        raise ValueError("精确时间需要发生时刻，不能同时填写区间")
    if precision == "interval" and (exact is not None or start is None or end is None or end < start):
        raise ValueError("时间区间需完整且结束不早于开始，不能冒充精确时刻")
    if precision == "unknown" and any(v is not None for v in (exact, start, end)):
        raise ValueError("时间未知时请保留原文表达，勿填写假定时刻")
    for field, bound in (("latitude", 90), ("longitude", 180)):
        value = get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or not -bound <= value <= bound):
            raise ValueError("经纬度数值无效")
    if (get("latitude") is None) != (get("longitude") is None):
        raise ValueError("经纬度必须同时填写或同时留空")
    if get("oil_volume_unit") not in OIL_UNITS | {None}:
        raise ValueError("油量单位无效，不允许自动吨升换算")
    amount = get("oil_volume")
    if amount is not None and (isinstance(amount, bool) or not isinstance(amount, (float, int)) or not isfinite(amount) or amount < 0):
        raise ValueError("油量须为非负有限数")
    for location in result.get("initial_locations") or []:
        if location.get("role") not in {"incident", "discovery", "mentioned", "source_candidate", "custody"}:
            raise ValueError("地点角色无效")
        if location.get("precision", "unknown") not in {"exact", "area", "unknown"}:
            raise ValueError("地点精度无效")
        validate_geometry(location.get("geometry"))
        if location.get("precision") == "exact" and (location.get("geometry") or {}).get("type") != "Point":
            raise ValueError("精确地点需要点坐标；区域不能作为精确道路端点")
    for measurement in result.get("initial_measurements") or []:
        if measurement.get("stage", "unknown") not in {"involved", "seized", "transferred", "recovered", "unknown"}:
            raise ValueError("测量环节无效")
        value = measurement.get("value")
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value) or value < 0:
            raise ValueError("测量数值须为非负有限数")
        if measurement.get("unit") not in OIL_UNITS:
            raise ValueError("测量必须明确单位或标为未知")
        if measurement.get("water_cut") is not None and not 0 <= measurement["water_cut"] <= 100:
            raise ValueError("含水率应在 0–100 之间")
        if measurement.get("measured_at") is not None:
            measurement["measured_at"] = _date(measurement["measured_at"], zone)
    return result
