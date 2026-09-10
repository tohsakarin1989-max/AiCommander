"""报告地图的冻结输入和受权来源；此模块不生成图片，不使用current回退。"""
from __future__ import annotations

import json
import math
import re

from sqlalchemy.orm import Session

from app.services.case_result_service import CaseResultService
from app.services.offline_map_service import OfflineMapService


def _coordinate(value: object, maximum: int) -> bool:
    return type(value) in (float, int) and math.isfinite(value) and abs(value) <= maximum


def frozen_result_map_input(content: dict) -> dict:
    """仅调用方已校验的冻结content；不向数据库补齐缺失坐标或图例。"""
    facts = content["related_conditions"]
    latitude, longitude = facts.get("latitude"), facts.get("longitude")
    warnings = []
    marker = None
    if _coordinate(latitude, 90) and _coordinate(longitude, 180):
        title = content["facts_summary"]["recorded_fields"].get("location")
        marker = {"case_id": content["case_id"], "latitude": latitude, "longitude": longitude,
                  "title": title if isinstance(title, str) else "案件记录位置"}
    else:
        warnings.append("冻结案件坐标缺失或异常，待核验；不补零或猜测位置。")
    snapshot_id = content["versions"]["map_snapshot_id"]
    asset_ids = set()
    candidates = []
    for item in content["candidates"]:
        candidates.append({key: item[key] for key in (
            "id", "rank", "category", "title", "region", "score", "score_kind", "evidence_refs", "boundary",
        )})
        for ref in item["evidence_refs"]:
            match = re.fullmatch(r"map_asset:([1-9][0-9]*)@snapshot:([A-Za-z0-9_-]{1,36})", ref)
            if match:
                if match[2] != snapshot_id:
                    raise ValueError("result_map_version_mismatch")
                asset_ids.add(int(match[1]))
    if len(asset_ids) > 50:
        raise ValueError("result_map_too_many_assets")
    if snapshot_id is None:
        warnings.append("成果未绑定地图快照，不使用当前地图替代历史底图。")
    # JSON深复制：后续渲染处理不能反向改写成果或共享region/引用列表。
    return json.loads(json.dumps({
        "schema": "case-result-map-4.1.0-1", "map_snapshot_id": snapshot_id,
        "case_marker": marker, "candidates": candidates,
        "production_asset_ids": sorted(asset_ids), "warnings": warnings,
    }, ensure_ascii=False, allow_nan=False))


def load_result_map_context(db: Session, result_id: str) -> dict:
    """按当前权限重读成果，取其固定底图清单和仅被引用的生产图层。"""
    result = CaseResultService.read(db, result_id)
    spec = frozen_result_map_input(result["content"])
    context = {"result_id": result_id, "content_sha256": result["content_sha256"], "map": spec,
               "basemap": None, "production": None}
    snapshot_id = spec["map_snapshot_id"]
    if snapshot_id is None:
        return context
    snapshot = OfflineMapService.resolve_snapshot(db, snapshot_id)
    if snapshot.id != snapshot_id:
        raise ValueError("result_map_version_mismatch")
    manifest = OfflineMapService.resolved_manifest(db, snapshot)
    # 仅取显示能力字段，不向渲染器传递存储路径或任意清单扩展字段。
    context["basemap"] = {key: manifest[key] for key in (
        "snapshot_id", "version", "renderer", "style_url", "tile_url", "bounds",
        "min_zoom", "max_zoom", "display_max_zoom", "attribution", "network_required",
    ) if key in manifest}
    production = OfflineMapService.read_layers(db, snapshot_id, asset_ids=spec["production_asset_ids"], limit=50)
    if production["truncated"] or len(production["features"]) != len(spec["production_asset_ids"]):
        raise ValueError("result_map_incomplete_production_layer")
    context["production"] = production
    return context
