"""Existing road queue, fenced checkpoints and owner-bound scenario results."""
from copy import deepcopy
from contextlib import nullcontext
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.case_pipeline import OutboxEvent
from app.services.case_road_jobs import _identity
from app.services import case_road_scenarios as service
from app.services.facility_candidate_pool import digest
from app.services.facility_conditions_v63 import entrance_state
from app.services.facility_job_checkpoint import ComparisonPending, fence_lease
from app.services.facility_road_batches import compare_facility_pool
from app.services.outbox_claim_service import OutboxClaimService, OutboxClaimLostError
from app.services.road_access_policy import VehicleAssumption
from app.services.scorers.facility_roads_v63 import FacilityEvidence
from app.services.vehicle_router import RoadCalculationError, RoadLocation
from app.services.road_network_service import resolve_network

EVENT_TYPE = "case.roads.scenarios"


def enqueue(db, artifact_id, expected_hash, option_ids):
    actor, scope = db.info.get("principal_user_id"), db.info.get("authorized_area_ids", ())
    _identity(db, actor, None if scope is None else list(scope))
    inputs = service.freeze_inputs(db, artifact_id, expected_hash, option_ids)
    scope = db.info["authorized_area_ids"]
    payload = {"user_id": actor, "scope": None if scope is None else sorted(scope),
               "inputs": inputs, "inputs_sha256": digest(inputs)}
    if len(json.dumps(payload, ensure_ascii=False).encode()) > 8 * 1024 * 1024:
        raise ValueError("scenario_inputs_too_large")
    fingerprint = digest(payload)
    payload["request_fingerprint"] = fingerprint
    previous = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == EVENT_TYPE,
        or_(OutboxEvent.idempotency_key == fingerprint,
            OutboxEvent.payload["request_fingerprint"].as_string() == fingerprint))
        .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc()).limit(1))
    retryable_partial = previous is not None and previous.status == "completed" and any(
        scenario.get("execution") in {"network_not_ready", "road_service_unavailable"}
        for scenario in (previous.payload.get("artifact") or {}).get("scenarios", []))
    if previous is not None and not retryable_partial:
        # Only an explicit POST can restart a cancelled or failed run.
        restarted = db.execute(update(OutboxEvent).where(OutboxEvent.id == previous.id,
            OutboxEvent.status.in_(["failed", "cancelled"])).values(status="pending", payload=payload,
                available_at=datetime.now(timezone.utc), worker_id=None, lease_until=None,
                processed_at=None, error=None, attempts=0).execution_options(synchronize_session=False))
        return {"event_id": previous.id, "created": restarted.rowcount == 1, "execution_task_created": False}
    key = fingerprint
    if retryable_partial:
        if digest(previous.payload["artifact"]) != previous.payload.get("artifact_sha256"):
            raise ValueError("scenario_artifact_integrity_invalid")
        # Keep the former partial snapshot readable. Concurrent/repeated POSTs
        # share the same child retry identity, rather than creating two runs.
        payload["retry_of"] = previous.id
        key = digest({"request": fingerprint, "retry_of": previous.id})
    dialect = db.get_bind().dialect.name
    if dialect not in {"sqlite", "postgresql"}:
        raise ValueError("scenario_database_unsupported")
    insert = sqlite_insert if dialect == "sqlite" else pg_insert
    identifier = db.scalar(insert(OutboxEvent).values(id=str(uuid4()), event_type=EVENT_TYPE,
        aggregate_type="case_road_artifact", aggregate_id=artifact_id, payload=payload,
        idempotency_key=key, status="pending", attempts=0, created_at=datetime.now(timezone.utc)).on_conflict_do_nothing(
            index_elements=["idempotency_key"]).returning(OutboxEvent.id))
    created = identifier is not None
    if identifier is None:
        identifier = db.scalar(select(OutboxEvent.id).where(OutboxEvent.idempotency_key == key))
    return {"event_id": identifier, "created": created, "execution_task_created": False}


def _authorize(db, payload, *, current=False):
    current_scope = db.info.get("authorized_area_ids")
    ceiling = payload["scope"]
    if current_scope is not None:
        ceiling = sorted(set(current_scope) if ceiling is None else set(current_scope).intersection(ceiling))
    _identity(db, payload["user_id"], ceiling)
    scope = db.info["authorized_area_ids"]
    if (None if scope is None else sorted(scope)) != payload["scope"]:
        raise PermissionError("scenario_scope_changed")
    if digest(payload["inputs"]) != payload["inputs_sha256"]:
        raise ValueError("scenario_inputs_integrity_invalid")
    return service.authorize_inputs(db, payload["inputs"], current=current)[0]


def _variant_pool(content, variant):
    pool = deepcopy(content["pool"])
    pool["assets"] = deepcopy(variant["assets"])
    return pool


def _calculate_variant(db, content, variant, payload, state, save, artifact_root, cancel_event):
    option, calculation = variant["option"], deepcopy(content["calculation"])
    pool = _variant_pool(content, variant)
    if option["kind"] not in {"reference_vehicle", "extra_road_exclusion"}:
        evidence = (service.exclude_frozen_entrance(content, variant)
                    if option["kind"] == "extra_entrance_exclusion" else variant["evidence"])
        return service.summarize_scenario(pool, evidence, option, calculation)
    parameters = option["parameters"]
    private_context = nullcontext()
    if option["kind"] == "extra_road_exclusion":
        from app.services.road_scenario_networks import prepare_private_network, use_private_network
        scenario_id = f"{payload['inputs']['artifact_id']}:{option['id']}"
        prepared = state.get("networks", {}).get(option["id"])
        if prepared is None:
            prepared = prepare_private_network(db, calculation["network_id"], calculation["graph_sha256"],
                analysis_at=service._at(calculation["analysis_at"]), vehicle=VehicleAssumption.model_validate(calculation["vehicle"]),
                registered_road_id=parameters["registered_road_id"], scenario_id=scenario_id,
                artifact_root=artifact_root, cancel_event=cancel_event)
            save("networks", {**state.get("networks", {}), option["id"]: prepared})
            if prepared["state"] == "ready":
                # Graph preparation has its own budget. Matrix batches resume
                # under a fresh lease, not in the tail of a compilation call.
                raise ComparisonPending()
        if prepared["state"] != "ready":
            missing = [{**row, "road_state": "network_missing", "road_distance_m": None}
                       if row["road_state"] in {"calculated", "no_path_found", "not_calculated", "calculation_failed"}
                       else row for row in variant["evidence"]]
            return {**service.summarize_scenario(pool, missing, option, calculation, execution="network_not_ready"),
                    "availability": "not_ready", "unavailable_reason": prepared["reason"]}
        parameters = {**prepared, "vehicle": calculation["vehicle"]}
        private_context = use_private_network(db, prepared["network_id"], scenario_id)
    vehicle = VehicleAssumption.model_validate(parameters["vehicle"])
    evidence, entrances = [], {}
    assets = {row["asset_id"]: row for row in pool["assets"]}
    for item in variant["evidence"]:
        asset = assets[item["asset_id"]]
        road_state = entrance_state(asset["entrances"], source_verified=asset["source_verified"])
        ready = road_state == "not_calculated"
        evidence.append(FacilityEvidence(**{**item, "road_state": road_state, "road_distance_m": None,
            "entrance_verified": ready, "passage_allowed": True if ready else False if road_state == "restricted" else None,
            "attribute_refs": tuple(item["attribute_refs"])}))
        if ready:
            entrances[item["asset_id"]] = [RoadLocation(**entry["point"]) for entry in asset["entrances"] if entry["eligible"]]
    roads = state.get("roads", {}).get(option["id"])
    try:
        with private_context:
            binding = resolve_network(db, parameters["network_id"], analysis_at=service._at(calculation["analysis_at"]), vehicle=vehicle)
            if binding.graph_sha256 != parameters["graph_sha256"]:
                raise ValueError("scenario_graph_changed")
            result = compare_facility_pool(db, origin=RoadLocation(**pool["origin"]), evidence=evidence,
                entrances=entrances, network_id=parameters["network_id"], analysis_at=service._at(calculation["analysis_at"]),
                vehicle=vehicle, artifact_root=artifact_root, source_versions={**pool["versions"], "pool_sha256": pool["input_sha256"],
                    "scenario_option_id": option["id"]}, recall_complete=pool["coverage"]["complete"],
                timeout_seconds=30, max_batches=3, cancel_event=cancel_event, resume_state=roads,
                on_batch_checkpoint=lambda value: save("roads", {**state.get("roads", {}), option["id"]: value}))
    except RoadCalculationError as error:
        if str(error) == "road_calculation_cancelled":
            raise
        # Preserve the baseline and known hard exclusions. A service failure is
        # not a no-path outcome, nor is a straight-line estimate substituted.
        failure = [asdict(replace(row, road_state="calculation_failed")) if row.road_state == "not_calculated"
                   else asdict(row) for row in evidence]
        return service.summarize_scenario(pool, failure, option,
            {**calculation, **parameters}, execution="road_service_unavailable")
    if not result["road_completion"]["complete"]:
        raise ComparisonPending()
    return service.summarize_scenario(pool, result["scoring_evidence"], option, result["versions"], execution="recalculated_same_frozen_pool")


def process(db, event_id, *, artifact_root, cancel_event=None):
    if db.new or db.dirty or db.deleted:
        raise ValueError("scenario_requires_clean_session")
    previous_info, token = dict(db.info), None
    try:
        event = db.get(OutboxEvent, event_id, populate_existing=True)
        if event and event.status in {"pending", "retry"} and OutboxClaimService._aware(event.available_at) > datetime.now(timezone.utc):
            return {"event_id": event_id, "status": event.status, "claimed": False}
        event, claimed = OutboxClaimService.claim(db, event_id, expected_type=EVENT_TYPE)
        if not claimed:
            return {"event_id": event_id, "status": event.status, "claimed": False}
        token, payload = event.worker_id, deepcopy(event.payload)
        from app.services.coverage_road_jobs import DurableCancellation
        cancel_event = DurableCancellation(sessionmaker(bind=db.get_bind()), event_id, token, cancel_event, event_type=EVENT_TYPE)
        content = _authorize(db, payload, current=True)
        db.rollback()
        state = payload.get("checkpoint", {})
        if state and digest(state) != payload.get("checkpoint_sha256"):
            raise ValueError("scenario_checkpoint_integrity_invalid")

        def save(key, value):
            nonlocal state
            if cancel_event is not None and cancel_event.is_set():
                raise RoadCalculationError("road_calculation_cancelled")
            _authorize(db, payload, current=True)
            fence_lease(db, event_id, token)
            state = {**state, key: deepcopy(value)}
            payload.update(checkpoint=state, checkpoint_sha256=digest(state), ordinary_failures=0)
            db.execute(update(OutboxEvent).where(OutboxEvent.id == event_id, OutboxEvent.worker_id == token,
                OutboxEvent.status == "processing").values(payload=deepcopy(payload)).execution_options(synchronize_session=False))
            db.commit()

        if not state.get("scenarios"):
            base = service.summarize_scenario(content["pool"], content["result"]["scoring_evidence"],
                {"id": "baseline", "kind": "baseline", "label": "冻结基准条件"}, content["calculation"])
            save("scenarios", [base])
        index = len(state["scenarios"]) - 1
        variants = payload["inputs"]["variants"]
        if index < len(variants):
            scenario = _calculate_variant(db, content, variants[index], payload, state, save, artifact_root, cancel_event)
            save("scenarios", [*state["scenarios"], scenario])
        if len(state["scenarios"]) != len(variants) + 1:
            raise ComparisonPending()
        artifact = service.combine(payload["inputs"], state["scenarios"])
        _authorize(db, payload, current=True)
        fence_lease(db, event_id, token)
        if cancel_event is not None and cancel_event.is_set():
            raise RoadCalculationError("road_calculation_cancelled")
        db.execute(update(OutboxEvent).where(OutboxEvent.id == event_id, OutboxEvent.worker_id == token,
            OutboxEvent.status == "processing").values(payload={**payload, "artifact": artifact,
                "artifact_sha256": digest(artifact)}).execution_options(synchronize_session=False))
        OutboxClaimService.finish(db, event_id=event_id, worker_id=token, status="completed")
        db.commit()
        return {"event_id": event_id, "status": "completed", "outcome": artifact["state"]}
    except Exception as error:
        db.rollback()
        if token is None or isinstance(error, OutboxClaimLostError):
            raise
        row = db.get(OutboxEvent, event_id, populate_existing=True)
        if row is not None and row.status == "cancelled":
            return {"event_id": event_id, "status": "cancelled"}
        pending = isinstance(error, ComparisonPending)
        cancelled = isinstance(error, RoadCalculationError) and str(error) == "road_calculation_cancelled"
        failures = row.payload.get("ordinary_failures", 0) + (0 if pending or cancelled else 1)
        terminal = isinstance(error, (ValueError, PermissionError))
        status = "pending" if pending else "cancelled" if cancelled else "superseded" if terminal else "failed" if failures >= 3 else "retry"
        fence_lease(db, event_id, token)
        db.execute(update(OutboxEvent).where(OutboxEvent.id == event_id, OutboxEvent.worker_id == token).values(
            payload={**row.payload, "ordinary_failures": failures}).execution_options(synchronize_session=False))
        OutboxClaimService.finish(db, event_id=event_id, worker_id=token, status=status,
            error=None if pending else "scenario_cancelled" if cancelled else "scenario_inputs_unavailable" if terminal else "scenario_calculation_failed",
            available_at=datetime.now(timezone.utc) + timedelta(seconds=1 if pending else min(60, 2 ** failures)))
        db.commit()
        return {"event_id": event_id, "status": status}
    finally:
        db.info.clear()
        db.info.update(previous_info)


def read_job(db, event_id):
    event = db.get(OutboxEvent, event_id, populate_existing=True)
    if event is None or event.event_type != EVENT_TYPE or event.payload.get("user_id") != db.info.get("principal_user_id"):
        raise PermissionError("scenario_unavailable")
    payload = event.payload
    _authorize(db, payload)
    checkpoint = payload.get("checkpoint", {})
    if checkpoint and digest(checkpoint) != payload.get("checkpoint_sha256"):
        raise ValueError("scenario_checkpoint_integrity_invalid")
    artifact = payload.get("artifact") if event.status == "completed" else None
    if artifact is not None and digest(artifact) != payload.get("artifact_sha256"):
        raise ValueError("scenario_artifact_integrity_invalid")
    from app.services.road_scenario_networks import use_private_network
    calculation = payload["inputs"]["calculation"]
    for option_id, prepared in checkpoint.get("networks", {}).items():
        if prepared["state"] == "ready":
            with use_private_network(db, prepared["network_id"], f"{payload['inputs']['artifact_id']}:{option_id}"):
                binding = resolve_network(db, prepared["network_id"], analysis_at=service._at(calculation["analysis_at"]),
                    vehicle=VehicleAssumption.model_validate(calculation["vehicle"]))
                if binding.graph_sha256 != prepared["graph_sha256"]:
                    raise ValueError("scenario_graph_changed")
    roads = list(checkpoint.get("roads", {}).values())
    return {"event_id": event.id, "artifact_id": payload["inputs"]["artifact_id"], "status": event.status,
        "artifact": artifact, "error": event.error, "execution_task_created": False,
        "progress": {"scenarios_completed": len(checkpoint.get("scenarios", [])),
            "scenarios_total": len(payload["inputs"]["variants"]) + 1,
            "road_targets_completed": sum(row.get("next_offset", 0) for row in roads),
            "road_targets_total": sum(row.get("targets_total", 0) for row in roads)}, "boundary": service.BOUNDARY}


def latest_job(db, artifact_id):
    service.read_baseline(db, artifact_id)
    identifier = db.scalar(select(OutboxEvent.id).where(OutboxEvent.event_type == EVENT_TYPE,
        OutboxEvent.aggregate_id == artifact_id, OutboxEvent.payload["user_id"].as_integer() == db.info.get("principal_user_id"))
        .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc()).limit(1))
    return {"job": read_job(db, identifier) if identifier else None}


def cancel(db, event_id):
    event = db.get(OutboxEvent, event_id, populate_existing=True)
    if event is None or event.event_type != EVENT_TYPE or event.payload.get("user_id") != db.info.get("principal_user_id"):
        raise PermissionError("scenario_unavailable")
    db.execute(update(OutboxEvent).where(OutboxEvent.id == event_id, OutboxEvent.status.in_(["pending", "retry", "processing"]))
        .values(status="cancelled", worker_id=None, lease_until=None, processed_at=datetime.now(timezone.utc),
                error="scenario_cancelled").execution_options(synchronize_session=False))
    db.commit()
    return {"event_id": event_id, "status": db.get(OutboxEvent, event_id, populate_existing=True).status}
