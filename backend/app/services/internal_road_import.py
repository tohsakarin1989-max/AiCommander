"""独立线状道路导入预检；不写正式地图，不计算或猜测连接关系。"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import re

MAX_ROAD_UPLOAD_BYTES = 2 * 1024 * 1024


def _position(value):
    return (isinstance(value, list) and len(value) == 2
            and all(type(v) in (int, float) and math.isfinite(v) for v in value)
            and -180 <= value[0] <= 180 and -90 <= value[1] <= 90)


def _conditions(value):
    if not isinstance(value, dict) or set(value) - {
        "direction", "gate", "access", "max_height_m", "max_weight_t", "valid_from", "valid_until",
    }:
        return False
    for key, allowed in {"direction": {"forward", "reverse", "both", "unknown"},
                         "gate": {"open", "closed", "unknown"},
                         "access": {"permitted", "prohibited", "unknown"}}.items():
        if key in value and (not isinstance(value[key], str) or value[key] not in allowed):
            return False
    for key in ("max_height_m", "max_weight_t"):
        if key in value and (type(value[key]) not in (float, int)
                             or not math.isfinite(value[key]) or value[key] <= 0):
            return False
    times = []
    for key in ("valid_from", "valid_until"):
        if key not in value:
            times.append(None)
            continue
        try:
            time = datetime.fromisoformat(value[key])
            if time.tzinfo is None:
                return False
            times.append(time)
        except (TypeError, ValueError):
            return False
    return not all(times) or times[0] < times[1]


def preview_internal_roads(payload: dict) -> dict:
    if (not isinstance(payload, dict) or payload.get("type") != "FeatureCollection"
            or payload.get("coordinate_system") != "EPSG:4326"
            or not isinstance(payload.get("features"), list) or not 1 <= len(payload["features"]) <= 500):
        raise ValueError("需提供明确EPSG:4326坐标系的FeatureCollection，包含1至500个要素")
    # 统一深复制保留原始线形与属性；不修改调用方数据，不对数值做隐式转换。
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > MAX_ROAD_UPLOAD_BYTES:
        raise ValueError("道路导入数据超过2MiB")
    payload = json.loads(encoded)
    counts = {}
    for feature in payload["features"]:
        if isinstance(feature, dict) and isinstance(feature.get("id"), str):
            counts[feature["id"]] = counts.get(feature["id"], 0) + 1
    rows, vertices = [], 0
    for index, feature in enumerate(payload["features"], 1):
        errors = []
        geometry = feature.get("geometry", {}) if isinstance(feature, dict) else {}
        properties = feature.get("properties", {}) if isinstance(feature, dict) else {}
        geometry = geometry if isinstance(geometry, dict) else {}
        properties = properties if isinstance(properties, dict) else {}
        identifier = feature.get("id") if isinstance(feature, dict) else None
        if not isinstance(identifier, str) or not re.fullmatch(r"[\w.:-]{1,100}", identifier):
            errors.append("缺少有效稳定来源编号")
        elif counts[identifier] > 1:
            errors.append("本批来源编号重复，不按名称或位置自动合并")
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            errors.append("要素类型必须为Feature")
        if not isinstance(properties.get("name"), str) or not properties["name"].strip() or len(properties["name"]) > 200:
            errors.append("缺少有效名称")
        kind = properties.get("kind")
        coordinates = geometry.get("coordinates")
        if kind == "road" and geometry.get("type") in ("LineString", "MultiLineString"):
            lines = [coordinates] if geometry["type"] == "LineString" else coordinates
            if (not isinstance(lines, list) or not lines or any(not isinstance(line, list) or len(line) < 2
                or not all(_position(p) for p in line) or all(p == line[0] for p in line) for line in lines)):
                errors.append("道路线形无效、坐标越界或整段长度为零")
            else:
                vertices += sum(len(line) for line in lines)
        elif kind == "entrance" and geometry.get("type") == "Point" and _position(coordinates):
            vertices += 1
            if not isinstance(properties.get("road_id"), str) or not re.fullmatch(r"[\w.:-]{1,100}", properties["road_id"]):
                errors.append("入口需明确关联道路来源编号")
        else:
            errors.append("道路须为LineString/MultiLineString，入口须为Point；不以点代替道路")
        if not _conditions(properties.get("conditions", {})):
            errors.append("通行条件、车型参数或带时区的有效期不合法")
        if "facility_asset_id" in properties and (kind != "entrance"
                or type(properties["facility_asset_id"]) is not int or properties["facility_asset_id"] <= 0):
            errors.append("设施关联仅用于入口，须提供系统稳定设施编号，不按名称自动合并")
        rows.append({"row": index, "source_feature_id": identifier if isinstance(identifier, str) else None,
                     "kind": kind if kind in ("road", "entrance") else None,
                     "status": "invalid" if errors else "pending_verification", "errors": errors,
                     "feature": feature if not errors else None})
    if vertices > 50000:
        raise ValueError("单批道路节点超过50000个")
    roads = {row["source_feature_id"] for row in rows if row["kind"] == "road" and not row["errors"]}
    for row in rows:
        row["warnings"] = []
        if not row["errors"]:
            row["warnings"].append("连接关系和通行许可尚未核验，不自动连路或认定可通行")
            if row["kind"] == "entrance" and row["feature"]["properties"]["road_id"] not in roads:
                row["warnings"].append("本批未找到关联道路，需核对历史道路记录")
            if row["kind"] == "entrance" and "facility_asset_id" not in row["feature"]["properties"]:
                row["warnings"].append("未记录稳定设施关联，不能仅按井名认定该入口属于某设施")
    return {"schema_version": "internal-road-preview-4.1.0-1", "input_sha256": hashlib.sha256(encoded).hexdigest(),
            "coordinate_system": "EPSG:4326", "rows": rows, "total": len(rows),
            "valid": sum(not row["errors"] for row in rows), "vertices": vertices,
            "persisted": False, "routing_available": False}
