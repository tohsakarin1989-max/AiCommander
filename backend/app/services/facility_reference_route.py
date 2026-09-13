"""Expand a saved top-three candidate using its frozen, verified entrance."""
from datetime import datetime

from app.models.case_road_artifact import CaseRoadArtifact
from app.services.road_access_policy import VehicleAssumption
from app.services.road_calculation_service import calculate_reference_route
from app.services.vehicle_router import RoadLocation


def read_facility_comparison(db, artifact_id, content_sha256):
    # Check the schema before following a parent reference: no recursive routes.
    row = db.query(CaseRoadArtifact).populate_existing().filter_by(id=artifact_id).first()
    if row is None:
        raise PermissionError("facility_comparison_unavailable")
    if row.content.get("schema_version") != "case-facility-comparison-5.2-1":
        raise ValueError("facility_comparison_required")
    from app.services.case_road_artifact_service import read_road_artifact
    parent = read_road_artifact(db, artifact_id)
    if parent["content_sha256"] != content_sha256:
        raise ValueError("facility_comparison_version_changed")
    return parent["content"]


def selected_entrance(content, asset_id):
    candidate = next((item for item in content["result"]["candidates"] if item["asset_id"] == asset_id), None)
    asset = next((item for item in content["pool"]["assets"] if item["asset_id"] == asset_id), None)
    if candidate is None or asset is None:
        raise ValueError("facility_candidate_not_selected")
    entries = [item for item in asset["entrances"] if item["eligible"]]
    index = candidate.get("selected_entry_index")
    if type(index) is not int or not 0 <= index < len(entries):
        raise ValueError("facility_entrance_not_available")
    return candidate, entries[index]


def route_facility_candidate(db, *, comparison_id, comparison_sha256, asset_id,
                             analysis_at, vehicle, artifact_root, cancel_event=None):
    content = read_facility_comparison(db, comparison_id, comparison_sha256)
    calculation = content["calculation"]
    if (analysis_at != datetime.fromisoformat(calculation["analysis_at"])
            or vehicle != VehicleAssumption.model_validate(calculation["vehicle"])):
        raise ValueError("facility_route_conditions_changed")
    candidate, entrance = selected_entrance(content, asset_id)
    route = calculate_reference_route(db, network_id=calculation["network_id"],
        analysis_at=analysis_at, vehicle=vehicle, artifact_root=artifact_root, cancel_event=cancel_event,
        start=RoadLocation(**content["pool"]["origin"]), end=RoadLocation(**entrance["point"]))
    if any(route[key] != calculation[key] for key in ("network_id", "graph_sha256", "policy_revision")):
        raise ValueError("facility_route_network_changed")
    read_facility_comparison(db, comparison_id, comparison_sha256)
    return {"schema_version": "case-road-route-4.2.0-1", "result_id": content["result_id"],
        "content_sha256": content["content_sha256"], "map_snapshot_id": content["map_snapshot_id"],
        "facility_comparison": {"id": comparison_id, "content_sha256": comparison_sha256},
        "target": {"asset_id": asset_id, "name": candidate["name"], "entrance": entrance,
                   "evidence_refs": candidate["evidence_refs"]},
        "route": route, "boundary": "采用已保存候选的可信入口、车型和通行条件；参考路径不是实际行驶轨迹，不确认设施内部连通。"}
