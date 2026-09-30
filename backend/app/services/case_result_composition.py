"""Immutable, identity-bound base -> road attachment -> result composition DAG.

This module only composes already frozen data. It never schedules work, calls
a model/router, or changes the original case, base snapshot or road attachment.
"""
from copy import deepcopy
import hashlib
import json

from sqlalchemy import select

from app.models.case_result import CaseResultSnapshot
from app.services.case_result_snapshot import RESULT_SCHEMA_VERSION, _canonical

COMPOSITION_SCHEMA_VERSION = "case-result-composition-6.0.0-1"
PURPOSE = "current_conditions_reference"


def branch_for(db):
    if "authorized_area_ids" not in db.info or type(db.info.get("principal_user_id")) is not int:
        raise PermissionError("case_result_composition_scope_required")
    scope = db.info["authorized_area_ids"]
    return {"principal_user_id": db.info["principal_user_id"],
            "area_ids": None if scope is None else sorted(set(scope)), "purpose": PURPOSE}


def assemble_composition(base, artifact, branch):
    from app.services.facility_document_map import facility_map_input

    road = artifact["content"]
    if (base["content"]["schema_version"] != RESULT_SCHEMA_VERSION
            or road["schema_version"] != "case-facility-comparison-5.2-1"
            or (road["result_id"], road["content_sha256"], road["map_snapshot_id"]) != (
                base["id"], base["content_sha256"], base["content"]["versions"]["map_snapshot_id"])):
        raise ValueError("case_result_composition_inputs_mismatch")
    calculation = road["calculation"]
    calculation_scope = calculation.get("scope")
    if (calculation.get("user_id") != branch["principal_user_id"]
            or (None if calculation_scope is None else sorted(calculation_scope)) != branch["area_ids"]):
        raise PermissionError("case_result_composition_road_scope_mismatch")
    content = deepcopy(base["content"])
    ranked = road["result"]
    content["schema_version"] = COMPOSITION_SCHEMA_VERSION
    content["composition"] = {
        "base_result_id": base["id"], "base_content_sha256": base["content_sha256"],
        "road_artifact_id": artifact["id"], "road_content_sha256": artifact["content_sha256"],
        "branch": branch,
    }
    # Old geometric candidates remain in the base snapshot, never mixed into
    # the v5.2 ranking or relabeled as a road-informed conclusion.
    content["candidate_source"] = "facility_roads_v52"
    content["road_versions"] = deepcopy(road["calculation"])
    content["road_algorithm_versions"] = deepcopy(road.get("algorithm_versions"))
    content["road_coverage"] = deepcopy(ranked["coverage"])
    content["road_unresolved"] = deepcopy(ranked["unresolved"])
    # Additive only: the absence of these keys preserves old content hashes.
    if ranked.get("condition_comparison") is not None:
        content["candidate_source"] = "facility_roads_v63"
        content["road_condition_comparison"] = deepcopy(ranked["condition_comparison"])
        content["road_ranking_changes"] = deepcopy(ranked.get("ranking_changes"))
    content["road_map"] = {**facility_map_input(road, case_id=content["case_id"]),
                           "road_artifact_id": artifact["id"],
                           "road_artifact_sha256": artifact["content_sha256"]}
    content["candidates"] = [{
        **deepcopy(item), "id": f"{artifact['id']}:{item['asset_id']}",
        "category": "source", "title": item["name"],
        "claim": "已知道路和生产条件下的来源候选，须人工核验；不确认实际来源。",
        "region": None, "score_components": item["components"],
        "boundary": ranked["boundary"], "status": "pending_review", "is_official_fact": False,
    } for item in ranked["candidates"]]
    content["analysis_status"] = "completed" if ranked["coverage"]["complete"] else "partial"
    content["information_gaps"]["analysis"] = ([] if ranked["coverage"]["complete"] else [
        "道路召回或计算尚未全部完成；缺失、受限和失败对象不按低风险处理，不代表全域最优。"])
    content["boundary"].extend([
        "本组合仅采用道路前置设施候选；原空间候选保存在基础成果，不混合评分。",
        "通行条件计算时刻不等于案发时刻，本成果不还原实际行驶路线。",
    ])
    encoded = _canonical(content)
    return {"content": json.loads(encoded), "content_sha256": hashlib.sha256(encoded.encode()).hexdigest()}


def require_composition_access(db, snapshot):
    """Re-authorize both immutable parents and verify the entire composition."""
    from app.services.case_result_service import CaseResultService
    from app.services.case_road_artifact_service import read_road_artifact

    reference = snapshot["content"]["composition"]
    if reference["branch"] != branch_for(db):
        raise PermissionError("case_result_composition_scope_changed")
    # Check the parent schema before recursive reads: malformed/cyclic saved
    # references cannot recurse into another composition or itself.
    schema = db.scalar(select(CaseResultSnapshot.content["schema_version"].as_string())
                       .where(CaseResultSnapshot.id == reference["base_result_id"]))
    if schema != RESULT_SCHEMA_VERSION:
        raise ValueError("case_result_composition_base_invalid")
    base = CaseResultService.read(db, reference["base_result_id"])
    artifact = read_road_artifact(db, reference["road_artifact_id"])
    if (base["content_sha256"] != reference["base_content_sha256"]
            or artifact["content_sha256"] != reference["road_content_sha256"]):
        raise ValueError("case_result_composition_parent_changed")
    expected = assemble_composition(base, artifact, reference["branch"])
    if expected["content_sha256"] != snapshot["content_sha256"]:
        raise ValueError("case_result_composition_content_changed")


def is_current_composition(db, result, base):
    """Historical readability is distinct from current condition applicability."""
    from app.services.case_road_artifact_service import read_road_artifact
    from app.services.case_road_vehicle import frozen_road_vehicle
    from app.services.facility_candidate_pool import require_current_pool_source
    from app.services.facility_analysis_versions import current_versions
    from app.services.road_network_service import select_network, _now

    content = result["content"]
    if (base.get("freshness") != "current"
            or content["composition"]["base_result_id"] != base["id"]):
        return False
    vehicle = frozen_road_vehicle(base["content"])
    calculation = content["road_versions"]
    if vehicle is None or vehicle.model_dump() != calculation["vehicle"]:
        return False
    if content.get("road_algorithm_versions") != current_versions():
        return False
    artifact = read_road_artifact(db, content["composition"]["road_artifact_id"])
    if artifact["content"]["result"]["algorithm_version"] != current_versions()["scorer"]:
        return False
    require_current_pool_source(db, artifact["content"]["pool"])
    # Today's default composition must not claim an expired or superseded
    # network is current; historical ID reads still retain their own timestamp.
    binding = select_network(db, analysis_at=_now(), vehicle=vehicle,
                             engine_version=calculation["engine_version"])
    return (binding.network_id, binding.graph_sha256, binding.policy_revision) == (
        calculation["network_id"], calculation["graph_sha256"], calculation["policy_revision"])


def resolve_result_components(db, result_id, road_artifact_id=None):
    """One bridge for report/map consumers; attachments always point to base."""
    from app.services.case_result_service import CaseResultService
    from app.services.case_road_document import load_document_road

    result = CaseResultService.read(db, result_id)
    reference = result["content"].get("composition")
    base = CaseResultService.read(db, reference["base_result_id"]) if reference else result
    selected = reference["road_artifact_id"] if reference else road_artifact_id
    if reference and road_artifact_id is not None and selected != road_artifact_id:
        raise ValueError("case_result_composition_attachment_mismatch")
    artifact = load_document_road(db, base["id"], base["content_sha256"],
        base["content"]["versions"]["map_snapshot_id"], selected) if selected else None
    return result, base, artifact
