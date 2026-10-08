"""Private subtractive scenario graphs over one already-authorized baseline.

No HTTP path/way-id/engine options are accepted. A private graph remains a
non-published building catalog row, usable only inside an owner-bound worker
context. Every use rechecks the original network, including current permission.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from uuid import uuid4

from sqlalchemy import select

from app.models.road_network import RoadNetworkVersion
from app.services.road_graph_artifact import install_graph_artifact, verify_graph_artifact
from app.services.road_graph_builder import compile_local_graph
from app.services.road_network_contracts import RoadNetworkUnavailable
from app.services.road_retained_source import verify_retained_source
from app.services.road_source_filter import filter_road_source
from app.services.vehicle_router import RoadCalculationError

BUILDER_VERSION = "private-road-exclusion-8.3-1"
CONTEXT_KEY = "private_road_scenario_capability"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise RoadCalculationError("road_calculation_cancelled")


class _BuildBudget:
    """Keep source filtering and compilation within one fenced worker lease."""

    def __init__(self, external):
        self.external = external
        self.deadline = time.monotonic() + 180

    def is_set(self):
        if self.external is not None and self.external.is_set():
            return True
        if time.monotonic() >= self.deadline:
            raise RoadCalculationError("road_graph_build_timeout")
        return False


def _baseline(db, network_id, analysis_at, vehicle):
    from app.services.road_network_service import resolve_network
    row = db.execute(select(RoadNetworkVersion).where(RoadNetworkVersion.id == network_id)
        .execution_options(populate_existing=True)).scalar_one_or_none()
    if (row is None or row.status != "ready" or row.builder_version.startswith("private-road-")
            or not isinstance(row.source_manifest, dict) or row.source_manifest.get("private_scenario")):
        raise RoadNetworkUnavailable("road_scenario_baseline_unavailable")
    binding = resolve_network(db, network_id, analysis_at=analysis_at, vehicle=vehicle)
    return row, binding


def eligible_exclusion_options(db, base_network_id, *, analysis_at, vehicle):
    """Only registered included roads and exact server-frozen OSM mappings."""
    row, _ = _baseline(db, base_network_id, analysis_at, vehicle)
    manifest = row.source_manifest
    plan, filtered = manifest.get("governance_plan") or {}, manifest.get("filter_result") or {}
    if not plan or not filtered.get("output_sha256"):
        return []
    excluded = set(filtered.get("excluded_way_ids", []))
    result = []
    for road in plan.get("inputs", {}).get("included", []):
        aliases = [entry for entry in plan.get("aliases", [])
                   if entry["import_id"] == road["import_id"] and entry["feature_id"] == road["feature_id"] and not entry["excluded"]]
        added = [entry for entry in filtered.get("new_internal_components", [])
                 if entry["source_id"] == road["source_id"] and entry["import_id"] == road["import_id"]
                 and entry["feature_id"] == road["feature_id"]]
        ways = {entry["osm_way_id"] for entry in aliases} | {entry["way_id"] for entry in added}
        if not ways or ways & excluded or any(type(way) is not int or not 0 < way < 2 ** 53 for way in ways):
            continue
        identity = {"source_id": road["source_id"], "import_id": road["import_id"], "feature_id": road["feature_id"]}
        result.append({"registered_road_id": _digest(identity), "label": f"额外排除已登记道路 {road['feature_id']}",
            **identity, "way_ids": sorted(ways), "base_input_sha256": row.input_sha256,
            "source_sha256": filtered["output_sha256"],
            "evidence_refs": [f"internal_road_import:{road['import_id']}",
                              *[f"road_public_alias:{entry['alias_id']}" for entry in aliases]]})
    return sorted(result, key=lambda entry: entry["registered_road_id"])


@contextmanager
def use_private_network(db, network_id, scenario_id):
    """Internal worker-only capability. HTTP routes never set this context."""
    prior = db.info.get(CONTEXT_KEY)
    db.info[CONTEXT_KEY] = {"network_id": network_id, "scenario_id": scenario_id,
                          "owner_id": db.info.get("principal_user_id")}
    try:
        yield
    finally:
        if prior is None:
            db.info.pop(CONTEXT_KEY, None)
        else:
            db.info[CONTEXT_KEY] = prior


def validate_private_network(db, row, *, analysis_at, vehicle):
    """Called by the standard resolver before any private tile can be read."""
    manifest = row["source_manifest"]
    if not isinstance(manifest, dict):
        raise RoadNetworkUnavailable("road_private_network_unavailable")
    private = manifest.get("private_scenario")
    capability = db.info.get(CONTEXT_KEY)
    if (row["builder_version"] != BUILDER_VERSION or row["status"] != "building"
            or manifest.get("build_status") != "ready_private" or not isinstance(private, dict)
            or capability != {"network_id": row["id"], "scenario_id": private.get("scenario_id"),
                              "owner_id": private.get("owner_id")}
            or private.get("owner_id") != db.info.get("principal_user_id") or vehicle is None):
        raise RoadNetworkUnavailable("road_private_network_unavailable")
    parent, binding = _baseline(db, private["parent_network_id"], analysis_at, vehicle)
    if (binding.graph_sha256 != private.get("parent_graph_sha256")
            or binding.cache_key != private.get("parent_cache_key")
            or parent.group_id != row["group_id"] or parent.policy_revision != row["policy_revision"]
            or parent.conditions_sha256 != row["conditions_sha256"]
            or parent.public_bundle_id != row["public_bundle_id"]):
        raise RoadNetworkUnavailable("road_scenario_baseline_changed")
    expected = _digest({"parent": private["parent_cache_key"], "scenario_id": private["scenario_id"],
                        "option": private["option"], "owner_id": private["owner_id"]})
    filtered, built = manifest.get("scenario_filter_result") or {}, manifest.get("scenario_build_result") or {}
    if (expected != row["input_sha256"] or built.get("graph_sha256") != row["graph_sha256"]
            or built.get("source_sha256") != filtered.get("output_sha256")
            or filtered.get("source_sha256") != private["option"]["source_sha256"]
            or filtered.get("requested_excluded_way_ids") != private["option"]["way_ids"]):
        raise RoadNetworkUnavailable("road_network_integrity_metadata_invalid")


def prepare_private_network(db, base_network_id, base_graph_sha256, *, analysis_at: datetime,
                            vehicle, registered_road_id, scenario_id, artifact_root: Path, cancel_event=None):
    """A killed worker releases its OS lock; the next fenced worker can resume."""
    _cancel(cancel_event)
    root = Path(artifact_root)
    locks = root / ".scenario-locks"
    if root.is_symlink() or locks.is_symlink():
        raise ValueError("road_scenario_work_link_forbidden")
    locks.mkdir(parents=True, exist_ok=True)
    key = _digest({"owner": db.info.get("principal_user_id"), "base": base_network_id,
                   "graph": base_graph_sha256, "road": registered_road_id, "scenario": scenario_id})
    descriptor = os.open(locks / key, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"state": "not_ready", "reason": "road_scenario_build_in_progress"}
        return _prepare_private_network(db, base_network_id, base_graph_sha256, analysis_at=analysis_at,
            vehicle=vehicle, registered_road_id=registered_road_id, scenario_id=scenario_id,
            artifact_root=artifact_root, cancel_event=cancel_event)


def _prepare_private_network(db, base_network_id, base_graph_sha256, *, analysis_at: datetime,
                             vehicle, registered_road_id, scenario_id, artifact_root: Path, cancel_event=None):
    """Dedicated worker session; only administrator-configured artifact_root."""
    if db.new or db.dirty or db.deleted:
        raise ValueError("road_scenario_requires_clean_session")
    if not isinstance(scenario_id, str) or not 1 <= len(scenario_id) <= 300:
        raise ValueError("road_scenario_identity_invalid")
    cancel_event = _BuildBudget(cancel_event)
    _cancel(cancel_event)
    parent, binding = _baseline(db, base_network_id, analysis_at, vehicle)
    if binding.graph_sha256 != base_graph_sha256:
        raise RoadNetworkUnavailable("road_scenario_baseline_changed")
    options = eligible_exclusion_options(db, base_network_id, analysis_at=analysis_at, vehicle=vehicle)
    option = next((entry for entry in options if entry["registered_road_id"] == registered_road_id), None)
    if option is None:
        raise RoadNetworkUnavailable("road_scenario_registered_road_unavailable")
    retained = parent.source_manifest.get("retained_source")
    if retained is None:
        return {"state": "not_ready", "reason": "road_scenario_source_not_retained"}
    if retained.get("source_sha256") != option["source_sha256"]:
        raise ValueError("road_retained_source_binding_invalid")
    try:
        source = verify_retained_source(artifact_root, retained)
    except FileNotFoundError:
        return {"state": "not_ready", "reason": "road_scenario_source_unavailable"}
    verify_graph_artifact(artifact_root, binding)
    owner = db.info["principal_user_id"]
    identity = _digest({"parent": binding.cache_key, "scenario_id": scenario_id, "option": option, "owner_id": owner})
    existing = db.query(RoadNetworkVersion).filter_by(input_sha256=identity, builder_version=BUILDER_VERSION).first()
    if existing is not None and existing.source_manifest.get("build_status") == "ready_private":
        with use_private_network(db, existing.id, scenario_id):
            from app.services.road_network_service import resolve_network
            checked = resolve_network(db, existing.id, analysis_at=analysis_at, vehicle=vehicle)
            verify_graph_artifact(artifact_root, checked)
        return {"state": "ready", "network_id": existing.id, "graph_sha256": existing.graph_sha256, "created": False}
    if existing is not None and (existing.status, existing.source_manifest.get("build_status")) not in {
            ("failed", "failed_private"), ("building", "building_private")}:
        return {"state": "not_ready", "reason": "road_scenario_build_incomplete"}
    identifier = existing.id if existing is not None else str(uuid4())
    frozen_manifest = deepcopy(parent.source_manifest)
    values = dict(group_id=parent.group_id, policy_revision=parent.policy_revision,
        public_bundle_id=parent.public_bundle_id, input_sha256=identity, conditions_sha256=parent.conditions_sha256,
        source_manifest={**frozen_manifest, "build_status": "building_private", "private_scenario": {
            "scenario_id": scenario_id, "owner_id": owner, "parent_network_id": parent.id,
            "parent_graph_sha256": binding.graph_sha256, "parent_cache_key": binding.cache_key, "option": option}},
        engine_version=parent.engine_version, builder_version=BUILDER_VERSION, status="building",
        valid_from=parent.valid_from, valid_until=parent.valid_until)
    if existing is None:
        row = RoadNetworkVersion(id=identifier, **values)
        db.add(row)
    else:
        row = existing
        for key, value in values.items():
            setattr(row, key, value)
        row.graph_sha256, row.artifact_key = None, None
    db.commit()
    root = Path(artifact_root)
    work = root / ".scenario-work"
    try:
        if root.is_symlink() or work.is_symlink():
            raise ValueError("road_scenario_work_link_forbidden")
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="exclude-", dir=work) as name:
            output = Path(name)
            _cancel(cancel_event)
            filtered = filter_road_source(source, output / "filtered", excluded_way_ids=set(option["way_ids"]),
                expected_source_sha256=option["source_sha256"], vehicle_kind=vehicle.kind, cancel_event=cancel_event)
            _cancel(cancel_event)
            built = compile_local_graph(output / "filtered" / "eligible.osm.pbf", output / "compiled",
                expected_source_sha256=filtered["output_sha256"], cancel_event=cancel_event, timeout_seconds=120)
            _cancel(cancel_event)
            # Reuse the exact baseline binding; never silently switch graphs.
            from app.services.road_network_service import recheck_network
            recheck_network(db, binding, analysis_at=analysis_at, vehicle=vehicle)
            if option not in eligible_exclusion_options(db, base_network_id, analysis_at=analysis_at, vehicle=vehicle):
                raise RoadNetworkUnavailable("road_scenario_registered_road_changed")
            db.commit()
            key = install_graph_artifact(output / "compiled" / "tiles", artifact_root, expected_sha256=built["graph_sha256"])
            recheck_network(db, binding, analysis_at=analysis_at, vehicle=vehicle)
            _cancel(cancel_event)
            row = db.get(RoadNetworkVersion, identifier, populate_existing=True)
            row.graph_sha256, row.artifact_key = built["graph_sha256"], key
            row.source_manifest = {**row.source_manifest, "build_status": "ready_private",
                                   "scenario_filter_result": filtered, "scenario_build_result": built}
            db.commit()
            return {"state": "ready", "network_id": identifier, "graph_sha256": row.graph_sha256, "created": True}
    except Exception:
        db.rollback()
        row = db.get(RoadNetworkVersion, identifier, populate_existing=True)
        if row is not None:
            row.status = "failed"
            row.source_manifest = {**row.source_manifest, "build_status": "failed_private"}
            db.commit()
        raise
