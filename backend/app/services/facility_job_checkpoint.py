"""Outbox-owned continuation; contains derived data only, never formal writes."""
from copy import deepcopy
from datetime import datetime, timezone
import json

from sqlalchemy import update

from app.models.case_pipeline import OutboxEvent
from app.services.facility_candidate_pool import digest, freeze_facility_pool
from app.services.facility_dependency_guard import require_dependencies
from app.services.facility_road_batches import compare_facility_pool
from app.services.outbox_claim_service import OutboxClaimLostError
from app.services.scorers.facility_roads_v63 import FacilityEvidence
from app.services.vehicle_router import RoadCalculationError, RoadLocation

VERSION = "facility-checkpoint-7.5-1"
SCAN_LIMIT = 100
ROAD_BATCH_LIMIT = 3


class ComparisonPending(Exception):
    """Ordinary budget yield, not a failure or a partial published result."""


def check_checkpoint(value):
    if (not isinstance(value, dict) or value.get("version") != VERSION
            or digest({key: item for key, item in value.items() if key != "sha256"}) != value.get("sha256")):
        raise ValueError("facility_checkpoint_integrity_invalid")
    return deepcopy(value)


def progress(checkpoint):
    value = check_checkpoint(checkpoint)
    scan, roads, pool = value.get("scan") or {}, value.get("roads") or {}, value.get("pool")
    total = len(scan.get("heap", []))
    return {"phase": "roads" if pool else "entrances" if scan.get("scan_complete") else "scan",
        "scanned": scan.get("scanned", 0), "scan_complete": bool(scan.get("scan_complete")),
        "candidate_pool_size": total, "candidate_pool_limit": 100,
        "entrance_facilities_checked": scan.get("entrance_cursor", 0), "entrance_facilities_total": total,
        "entrance_check_complete": bool(pool), "road_targets_completed": roads.get("next_offset", 0),
        "road_targets_total": roads.get("targets_total") if pool else None,
        "road_complete": bool(roads.get("complete")), "dependency_policy": value["dependencies"]["policy"],
        "boundary": "最多展示三项不等于只计算三个设施；候选池上限100，未选尽时不宣称全域最优。"}


def advance_comparison(db, *, event_id, worker_id, payload, authorize, at, vehicle,
                       artifact_root, cancel_event=None):
    state = (check_checkpoint(payload["facility_checkpoint"]) if payload.get("facility_checkpoint") else
             {"version": VERSION, "dependencies": payload["dependencies"]})
    if state["dependencies"] != payload["dependencies"]:
        raise ValueError("facility_checkpoint_dependencies_changed")
    require_dependencies(db, state["dependencies"])

    def save(key, value):
        nonlocal state
        if cancel_event is not None and cancel_event.is_set():
            raise RoadCalculationError("road_calculation_cancelled")
        authorize()
        require_dependencies(db, state["dependencies"])
        state = {**state, key: value}
        body = json.loads(json.dumps({name: item for name, item in state.items() if name != "sha256"}))
        state = {**body, "sha256": digest(body)}
        payload["facility_checkpoint"] = state
        payload["ordinary_failures"] = 0
        count = db.execute(update(OutboxEvent).where(OutboxEvent.id == event_id,
            OutboxEvent.status == "processing", OutboxEvent.worker_id == worker_id,
            OutboxEvent.lease_until > datetime.now(timezone.utc)).values(payload=deepcopy(payload))
            .execution_options(synchronize_session=False)).rowcount
        if count != 1:
            raise OutboxClaimLostError("outbox_claim_lost")
        db.commit()  # Completed native work and continuation cursor survive restarts together.

    if state.get("pool") is None:
        pool = freeze_facility_pool(db, result_id=payload["result_id"], network_id=payload["network_id"],
            analysis_at=at, vehicle=vehicle, scan_state=state.get("scan"), scan_limit=SCAN_LIMIT,
            on_scan_checkpoint=lambda value: save("scan", value))
        if pool.get("pending"):
            raise ComparisonPending()
        pool = {key: value for key, value in pool.items() if key != "input_sha256"}
        pool["dependency_context"] = {key: state["dependencies"][key] for key in
            ("schema", "sha256", "scope", "user_id", "policy", "next_transition_at", "boundary")}
        pool["input_sha256"] = digest(pool)
        save("pool", pool)
    pool = state["pool"]
    evidence = [FacilityEvidence(**{**row, "attribute_refs": tuple(row["attribute_refs"])})
                for row in pool["evidence"]]
    result = compare_facility_pool(db, origin=RoadLocation(**pool["origin"]), evidence=evidence,
        entrances={int(key): [RoadLocation(**point) for point in value] for key, value in pool["entrances"].items()},
        network_id=payload["network_id"], analysis_at=at, vehicle=vehicle, artifact_root=artifact_root,
        source_versions={**pool["versions"], "pool_sha256": pool["input_sha256"]},
        recall_complete=pool["coverage"]["complete"], cancel_event=cancel_event,
        timeout_seconds=30, max_batches=ROAD_BATCH_LIMIT, resume_state=state.get("roads"),
        on_batch_checkpoint=lambda value: save("roads", value))
    if not result["road_completion"]["complete"]:
        raise ComparisonPending()
    from app.services.case_facility_comparison import complete_case_facility_comparison
    return complete_case_facility_comparison(db, pool, result)


def fence_lease(db, event_id, token):
    # Lock ownership before the artifact+terminal transition, including expiry
    # without another worker having claimed the row yet.
    count = db.execute(update(OutboxEvent).where(OutboxEvent.id == event_id,
        OutboxEvent.worker_id == token, OutboxEvent.status == "processing",
        OutboxEvent.lease_until > datetime.now(timezone.utc)).values(worker_id=token)
        .execution_options(synchronize_session=False)).rowcount
    if count != 1:
        raise OutboxClaimLostError("outbox_claim_lost")
