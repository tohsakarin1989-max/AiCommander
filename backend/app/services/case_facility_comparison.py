"""Business entry point for automatic facility recall -> routing -> ranking."""
from app.services.case_result_service import CaseResultService
from app.services.facility_candidate_pool import freeze_facility_pool, validate_pool_access, require_current_pool_source
from app.services.facility_road_batches import compare_facility_pool
from app.services.scorers.facility_roads_v52 import FacilityEvidence
from app.services.vehicle_router import RoadLocation
from app.services.facility_analysis_versions import current_versions
from app.services.facility_conditions_v63 import build_condition_comparison, compare_rankings


SCHEMA = "case-facility-comparison-5.2-1"


def _previous_comparison(db, source, current):
    """Use a saved artifact for this actor and permission branch; no fabricated baseline."""
    from app.models.case_road_artifact import CaseRoadArtifact
    from app.services.case_road_artifact_service import read_road_artifact

    rows = db.query(CaseRoadArtifact).filter_by(case_id=source["content"]["case_id"],
        operation="facility", created_by=db.info["principal_user_id"]).order_by(
            CaseRoadArtifact.created_at.desc(), CaseRoadArtifact.id.desc()).limit(20).all()
    for row in rows:
        try:
            saved = read_road_artifact(db, row.id)
        except (PermissionError, ValueError):
            # Do not substitute an older baseline when the latest own artifact
            # is unavailable, or disclose its former conclusions/counts.
            break
        previous = saved["content"]
        calculation = previous.get("calculation") or {}
        if (calculation.get("user_id"), calculation.get("scope")) != (
                current["calculation"].get("user_id"), current["calculation"].get("scope")):
            continue
        before = previous["result"].get("condition_comparison")
        changes = []
        for key, a, b in (
            ("case", previous["content_sha256"], current["content_sha256"]),
            ("network", tuple(calculation.get(k) for k in ("network_id", "graph_sha256", "policy_revision")),
             tuple(current["calculation"].get(k) for k in ("network_id", "graph_sha256", "policy_revision"))),
            ("vehicle", calculation.get("vehicle"), current["calculation"].get("vehicle")),
            ("analysis_time", calculation.get("analysis_at"), current["calculation"].get("analysis_at")),
            ("algorithm", previous.get("algorithm_versions"), current.get("algorithm_versions")),
            ("map", previous["map_snapshot_id"], current["map_snapshot_id"]),
        ):
            if a != b:
                changes.append(key)
        baseline = {"artifact_id": saved["id"], "content_sha256": saved["content_sha256"]}
        if before is None:
            return {**compare_rankings(current["result"]["condition_comparison"], None),
                    "state": "not_comparable", "baseline": baseline,
                    "context_changes": changes}
        return compare_rankings(current["result"]["condition_comparison"], before,
                                baseline=baseline, context_changes=changes)
    return compare_rankings(current["result"]["condition_comparison"], None)


def compare_case_facilities(db, *, result_id, network_id, analysis_at, vehicle, artifact_root, cancel_event=None):
    try:
        pool = freeze_facility_pool(db, result_id=result_id, network_id=network_id,
                                   analysis_at=analysis_at, vehicle=vehicle)
    except ValueError as error:
        if str(error) not in {"facility_recall_map_missing", "facility_recall_origin_missing"}:
            raise
        source = CaseResultService.read(db, result_id)
        return {"schema_version": SCHEMA, "result_id": result_id, "content_sha256": source["content_sha256"],
                "map_snapshot_id": source["content"]["versions"]["map_snapshot_id"],
                "calculation": None, "information_gaps": [str(error)]}
    evidence = [FacilityEvidence(**{**row, "attribute_refs": tuple(row["attribute_refs"])}) for row in pool["evidence"]]
    result = compare_facility_pool(db, origin=RoadLocation(**pool["origin"]), evidence=evidence,
        entrances={int(key): [RoadLocation(**point) for point in value] for key, value in pool["entrances"].items()},
        network_id=network_id, analysis_at=analysis_at, vehicle=vehicle, artifact_root=artifact_root,
        source_versions={**pool["versions"], "pool_sha256": pool["input_sha256"]},
        recall_complete=pool["coverage"]["complete"], cancel_event=cancel_event)
    validate_pool_access(db, pool)
    require_current_pool_source(db, pool)
    names = {item["asset_id"]: item["name"] for item in pool["assets"]}
    for candidate in result["candidates"]:
        candidate["name"] = names[candidate["asset_id"]]
        asset = next(item for item in pool["assets"] if item["asset_id"] == candidate["asset_id"])
        production = asset["production_comparison"]
        candidate["supporting_evidence"].extend(production["support"])
        candidate["counter_evidence"].extend(production["counter"])
        candidate["information_gaps"].extend(production["gaps"])
        history = asset["history_comparison"]
        candidate["supporting_evidence"].extend(history["support"])
        candidate["counter_evidence"].extend(history["counter"])
        candidate["information_gaps"].extend(history["gaps"])
        entries = [entry for entry in asset["entrances"] if entry["eligible"]]
        selected = entries[candidate["selected_entry_index"]]
        candidate["evidence_refs"].append(
            f"internal_road_entrance:{selected['import_id']}:{selected['feature_id']}@review:{selected['review_id']}")
    result["condition_comparison"] = build_condition_comparison(pool, result)
    content = {"schema_version": SCHEMA, "result_id": result_id, "content_sha256": pool["content_sha256"],
            "map_snapshot_id": pool["versions"]["map_snapshot_id"], "pool": pool, "result": result,
            "calculation": result["versions"], "algorithm_versions": current_versions(),
            "boundary": result["boundary"]}
    # DB JSON normalizes tuple scopes; use the same representation before comparing.
    from copy import deepcopy
    content["calculation"] = deepcopy(content["calculation"])
    if content["calculation"]["scope"] is not None:
        content["calculation"]["scope"] = list(content["calculation"]["scope"])
    source = CaseResultService.read(db, result_id)
    result["ranking_changes"] = _previous_comparison(db, source, content)
    return content
