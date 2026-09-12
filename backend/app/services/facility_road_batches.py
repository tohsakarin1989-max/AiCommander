"""Budgeted routing of a pre-authorized frozen facility pool, before ranking.

Internal service only: caller freezes facilities/verified entrances from business
records and persists the returned evidence under current source authorization.
"""
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
import time

from app.services.road_calculation_service import calculate_distance_matrix
from app.services.road_network_service import resolve_network
from app.services.scorers.facility_roads_v52 import FacilityEvidence, rank_facilities
from app.services.vehicle_router import RoadLocation, RoadCalculationError


def compare_facility_pool(db, *, origin: RoadLocation, evidence: list[FacilityEvidence],
                          entrances: dict[int, RoadLocation | list[RoadLocation]], network_id: str, analysis_at: datetime,
                          vehicle, artifact_root: Path, source_versions: dict,
                          recall_complete: bool, timeout_seconds: float = 90, cancel_event=None) -> dict:
    if "authorized_area_ids" not in db.info or type(db.info.get("principal_user_id")) is not int:
        raise PermissionError("facility_comparison_scope_required")
    if cancel_event is not None and cancel_event.is_set():
        raise RoadCalculationError("road_calculation_cancelled")
    required = {"case_profile_id", "case_source_hash", "map_snapshot_id", "recall_version"}
    if not required <= source_versions.keys() or any(not source_versions[key] for key in required):
        raise ValueError("facility_comparison_versions_required")
    if any(item.evidence_ref != f"map_asset:{item.asset_id}@snapshot:{source_versions['map_snapshot_id']}" for item in evidence):
        raise ValueError("facility_comparison_map_reference_mismatch")
    if type(timeout_seconds) not in (float, int) or not 0 < timeout_seconds <= 120:
        raise ValueError("facility_comparison_budget_invalid")
    # Validate the whole pool before selecting any batch. No caller-supplied
    # route distances are allowed to enter this computation as fresh results.
    rank_facilities(evidence, recall_complete=recall_complete)
    if any(item.road_state == "calculated" for item in evidence):
        raise ValueError("facility_comparison_requires_uncalculated_pool")
    points = {key: [value] if isinstance(value, RoadLocation) else value for key, value in entrances.items()}
    if (any(type(key) is not int or not isinstance(value, list)
            or any(not isinstance(point, RoadLocation) for point in value) for key, value in points.items())
            or sum(len(value) for value in points.values()) > 1000):
        raise ValueError("facility_comparison_entrances_invalid")
    binding = resolve_network(db, network_id, analysis_at=analysis_at, vehicle=vehicle)
    frozen_scope = db.info["authorized_area_ids"]
    frozen_scope = None if frozen_scope is None else tuple(sorted(frozen_scope))
    actor = db.info["principal_user_id"]
    versions = {**source_versions, "network_id": binding.network_id, "graph_sha256": binding.graph_sha256,
                "policy_revision": binding.policy_revision, "vehicle": vehicle.model_dump(),
                "analysis_at": analysis_at.isoformat(), "user_id": actor, "scope": frozen_scope,
                "engine_version": binding.engine_version}
    rows = list(evidence)
    indices = [index for index, item in enumerate(rows) if item.road_state == "not_calculated"
               and item.entrance_verified and item.passage_allowed and points.get(item.asset_id)]
    for index, item in enumerate(rows):
        if item.road_state == "not_calculated" and not points.get(item.asset_id):
            rows[index] = replace(item, road_state="entrance_unknown", entrance_verified=False)
    targets = [(index, entry_index, point) for index in indices
               for entry_index, point in enumerate(points[rows[index].asset_id])]
    outcomes = {index: [{"state": "not_calculated", "distance_m": None} for _ in points[rows[index].asset_id]]
                for index in indices}
    deadline, batches = time.monotonic() + timeout_seconds, []
    for offset in range(0, len(targets), 10):
        if cancel_event is not None and cancel_event.is_set():
            raise RoadCalculationError("road_calculation_cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        selected = targets[offset:offset + 10]
        try:
            matrix = calculate_distance_matrix(db, network_id=network_id, analysis_at=analysis_at,
                sources=[origin], targets=[point for _, _, point in selected],
                vehicle=vehicle, artifact_root=artifact_root, cancel_event=cancel_event,
                timeout_seconds=remaining)
            if (matrix["network_id"] != versions["network_id"] or matrix["graph_sha256"] != versions["graph_sha256"]
                    or matrix["policy_revision"] != versions["policy_revision"]):
                raise ValueError("facility_comparison_network_changed")
            cells = matrix["cells"]
            if len(cells) != len(selected) or any(cell["source_index"] != 0 or cell["target_index"] != i
                                               for i, cell in enumerate(cells)):
                raise ValueError("facility_comparison_matrix_shape")
            for (index, entry_index, _), cell in zip(selected, cells):
                if cell["status"] not in {"calculated", "no_path_found"}:
                    raise ValueError("facility_comparison_matrix_status")
                replace(rows[index], road_state=cell["status"], road_distance_m=cell["distance_m"])
                outcomes[index][entry_index] = {"state": cell["status"], "distance_m": cell["distance_m"]}
            batches.append({"asset_ids": [rows[index].asset_id for index, _, _ in selected],
                            "entry_indices": [entry_index for _, entry_index, _ in selected], "matrix": matrix})
        except RoadCalculationError as error:
            if str(error) == "road_calculation_cancelled":
                raise
            for index, entry_index, _ in selected:
                outcomes[index][entry_index] = {"state": "calculation_failed", "distance_m": None}
            # A broken engine is not a reason to repeat every remaining batch.
            break
    chosen = {}
    for index, results in outcomes.items():
        states = {item["state"] for item in results}
        if "calculation_failed" in states or "not_calculated" in states:
            # A known route is not the best entrance until all alternatives finish.
            state = "calculation_failed" if "calculation_failed" in states else "not_calculated"
            rows[index] = replace(rows[index], road_state=state)
            continue
        reachable = [(item["distance_m"], entry_index) for entry_index, item in enumerate(results)
                     if item["state"] == "calculated"]
        if reachable:
            distance, entry_index = min(reachable)
            rows[index] = replace(rows[index], road_state="calculated", road_distance_m=distance)
            chosen[rows[index].asset_id] = entry_index
        else:
            rows[index] = replace(rows[index], road_state="no_path_found")
    if cancel_event is not None and cancel_event.is_set():
        raise RoadCalculationError("road_calculation_cancelled")
    current = resolve_network(db, network_id, analysis_at=analysis_at, vehicle=vehicle)
    scope = db.info["authorized_area_ids"]
    scope = None if scope is None else tuple(sorted(scope))
    if (current.graph_sha256 != versions["graph_sha256"] or current.policy_revision != versions["policy_revision"]
            or actor != db.info["principal_user_id"] or scope != frozen_scope):
        raise PermissionError("facility_comparison_authority_changed")
    ranking = rank_facilities(rows, recall_complete=recall_complete)
    from app.services.scorers.registry import resolve_facility_scorer
    from app.services.facility_analysis_versions import SCORING_INPUT_VERSION
    for candidate in ranking["candidates"]:
        candidate["selected_entry_index"] = chosen[candidate["asset_id"]]
        candidate["entrances_compared"] = len(points[candidate["asset_id"]])
    return {**ranking, "versions": versions,
            "scorer_checksum": resolve_facility_scorer(ranking['algorithm_version'])[1],
            "scoring_input_version": SCORING_INPUT_VERSION,
            "scoring_evidence": [asdict(item) for item in rows],
            "entrance_results": [{"asset_id": rows[index].asset_id, "entries": values} for index, values in outcomes.items()],
            "batches": batches, "budget_seconds": timeout_seconds,
            "budget_exhausted": time.monotonic() >= deadline}
