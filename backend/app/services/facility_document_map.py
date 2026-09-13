"""Frozen top-three entrance figure shared by report composition and rendering."""
from copy import deepcopy

from app.services.case_result_map import _coordinate
from app.services.facility_reference_route import read_facility_comparison, selected_entrance


def facility_map_input(content: dict, *, case_id: int) -> dict:
    pool = content["pool"]
    origin = pool.get("origin", {})
    if not _coordinate(origin.get("latitude"), 85) or not _coordinate(origin.get("longitude"), 180):
        raise ValueError("facility_map_origin_invalid")
    points, ids = [], []
    candidates = content["result"]["candidates"]
    if len(candidates) > 3:
        raise ValueError("facility_map_candidates_invalid")
    for rank, candidate in enumerate(candidates, 1):
        asset_id = candidate["asset_id"]
        if type(asset_id) is not int or asset_id <= 0 or asset_id in ids or candidate["rank"] != rank:
            raise ValueError("facility_map_candidates_invalid")
        _, entry = selected_entrance(content, asset_id)
        point = entry["point"]
        positions = pool.get("entrances", {}).get(str(asset_id), [])
        index = candidate["selected_entry_index"]
        if (index >= len(positions) or positions[index] != point
                or not _coordinate(point.get("latitude"), 85) or not _coordinate(point.get("longitude"), 180)):
            raise ValueError("facility_map_entrance_invalid")
        ids.append(asset_id)
        points.append({"id": str(asset_id), "rank": rank, **point,
                       "title": f"{rank}. {candidate['name']}（可信入口）"})
    return deepcopy({
        "schema": "case-facility-map-5.2-1", "map_snapshot_id": content["map_snapshot_id"],
        "case_marker": {"case_id": case_id, **origin, "title": "案件记录位置"},
        "candidates": [], "reference_points": points, "production_asset_ids": ids,
        "warnings": ["入口编号与道路候选排序一致；入口点不等于设施中心，不确认设施内部连通。",
                     "本图不绘制直线或圆形作为道路；实际参考路径见已保存的路径附件。"],
    })


def resolve_facility_map_input(db, artifact: dict, *, case_id: int) -> dict | None:
    content = artifact["content"]
    if content["schema_version"] == "case-facility-comparison-5.2-1":
        comparison = content
    elif content["schema_version"] == "case-road-route-4.2.0-1" and content.get("facility_comparison"):
        parent = content["facility_comparison"]
        comparison = read_facility_comparison(db, parent["id"], parent["content_sha256"])
    else:
        return None
    if (comparison["result_id"], comparison["content_sha256"], comparison["map_snapshot_id"]) != (
            content["result_id"], content["content_sha256"], content["map_snapshot_id"]):
        raise ValueError("facility_map_source_mismatch")
    return {**facility_map_input(comparison, case_id=case_id),
            "road_artifact_id": artifact["id"], "road_artifact_sha256": artifact["content_sha256"]}
