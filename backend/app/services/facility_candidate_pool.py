"""Authorized facility recall and explicitly reviewed entrances, never nearest gates."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import heapq
import json
import time

from sqlalchemy import and_, func

from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.internal_roads import InternalRoadFeatureVersion, InternalRoadImport, InternalRoadReview
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import (
    FacilityIdentityDecision, FacilitySourceIdentity, JurisdictionAssetVersion,
    MapSnapshot, MapSnapshotFeature, MapSource,
)
from app.models.road_network import RoadNetworkVersion
from app.services.case_result_service import CaseResultService
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_source_service import CaseSourceService
from app.services.facility_production_conditions import production_comparison, VERSION as PRODUCTION_VERSION
from app.services.facility_history_conditions import history_context, facility_history_match, validate_history_access
from app.services.road_access_policy import InternalRoadConditions, internal_road_eligibility
from app.services.road_network_service import resolve_network
from app.services.scorers.facility_roads_v52 import FacilityEvidence
from app.services.scorers.dual_domain_v34 import SOURCE_TYPES
from app.services.vehicle_router import RoadLocation
from app.services.facility_identity_service import FacilityIdentityService
from app.services.facility_conditions_v63 import entrance_state
from app.services.facility_temporal_conditions import case_window, resolve_conditions, group_match, validate_temporal_access
from app.utils.geo import bounding_box, haversine_km


RECALL_VERSION = "facility-recall-7.5-1"
SOURCE_EXCLUDED = frozenset({"public_map", "osm", "openstreetmap", "public_reference"})
FACILITY_TERMS = {"well": {"油井", "采油井", "井口"}, "valve": {"阀门"},
                  "station": {"站库", "集油站"}, "pipeline_node": {"管线", "输油管线"}}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _utc(value):
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _require_current_case_profile(db, case, profile, versions):
    """Content equality does not identify a revision after an A -> B -> A edit."""
    if (case is None or profile is None or not profile.is_current
            or profile.source_hash != versions["case_source_hash"]
            or CasePipelineService.source_hash(db, case) != profile.source_hash):
        raise ValueError("facility_recall_source_outdated")
    latest = CaseSourceService.latest_revision(db, case.id)
    revision_id = latest.id if latest is not None else None
    if (profile.source_revision_id != revision_id
            or ("source_revision_id" in versions and versions["source_revision_id"] != revision_id)
            or (latest is not None and latest.source_hash != profile.source_hash)):
        raise ValueError("facility_recall_source_outdated")
    return revision_id


def _production_context(db, asset_id, *, valid_at=None, valid_from=None, valid_to=None, known_at,
                        knowledge_mode="retrospective"):
    """Resolve declared historical production; never backfill from today's map."""
    if valid_at is None and valid_from is None:
        return {"state": "unknown", "asset_id": asset_id, "valid_at": None,
                "known_at": known_at.isoformat(), "version_id": None, "snapshot": None,
                "gaps": ["案件缺少明确发生时间，未用当前生产资料填补历史条件"]}
    try:
        context = resolve_conditions(db, asset_id, valid_at=valid_at, valid_from=valid_from, valid_to=valid_to,
                                     known_at=known_at, knowledge_mode=knowledge_mode, frozen=True)
        source_id = ((context.get("snapshot") or {}).get("attributes") or {}).get("source_id")
        source_ids = {identifier for group in context.get("groups", {}).values() for segment in group.get("segments", [])
                      for identifier in segment.get("source_ids", [])}
        if source_id is not None:
            source_ids.add(source_id)
        for source_id in source_ids:
            source = db.query(MapSource).populate_existing().filter_by(id=source_id, status="active").first()
            if source is None or source.source_type in SOURCE_EXCLUDED:
                raise LookupError("facility_production_source_unavailable")
        return context
    except (PermissionError, LookupError):
        return {"state": "unavailable", "asset_id": asset_id, "valid_at": valid_at.isoformat() if valid_at else None,
                "known_at": known_at.isoformat(), "version_id": None, "snapshot": None,
                "gaps": ["该时点生产资料的来源不可用，未借用其他或当前来源"]}


def _production_signature(context):
    return digest({key: value for key, value in context.items() if key != "known_at"})


def _production_refs(context):
    refs = []
    for key, prefix in (("version_id", "asset_version"), ("source_claim_id", "map_claim"),
                        ("source_identity_id", "facility_identity"), ("identity_decision_id", "facility_identity_decision")):
        if context.get(key) is not None:
            refs.append(f"{prefix}:{context[key]}")
    refs.extend(ref for group in context.get("groups", {}).values() for segment in group.get("segments", [])
                for ref in segment.get("evidence_refs", []))
    return sorted(set(refs))


def _current_source_guard(db, snapshot_asset, current_asset, analysis_at):
    """Gate new calculations only; do not rewrite or delete historical results."""
    saved = snapshot_asset.attributes if isinstance(snapshot_asset.attributes, dict) else {}
    current = current_asset.attributes if isinstance(current_asset.attributes, dict) else {}
    stamp = {"asset_id": current_asset.id, "status": current_asset.status,
             "verified": bool(current_asset.verified), "verification_state": current_asset.verification_state,
             "asset_type": current_asset.asset_type,
             "valid_from": _utc(current_asset.valid_from).isoformat() if current_asset.valid_from else None,
             "valid_to": _utc(current_asset.valid_to).isoformat() if current_asset.valid_to else None,
             "current_references": {key: current.get(key) for key in ("source_id", "source_identity_id", "identity_decision_id")},
             "snapshot_references": {key: saved.get(key) for key in ("source_id", "source_identity_id", "identity_decision_id")}}

    def result(state, reason):
        return {"state": state, "reason": reason, "sha256": digest({**stamp, "state": state})}

    if current_asset.verification_state in {"identity_revoked", "temporal_not_current"}:
        return result(current_asset.verification_state, "当前来源身份已撤销或资料不属于当前有效状态；旧快照不恢复核验")
    if current_asset.status != "active" or current_asset.asset_type != snapshot_asset.asset_type:
        return result("source_changed", "当前设施状态或类别已变化，需重新核对地图来源")
    if not current_asset.verified:
        return result("unverified", "当前设施资料未核验，旧快照核验状态不能覆盖当前状态")
    if ((current_asset.valid_from and analysis_at < _utc(current_asset.valid_from))
            or (current_asset.valid_to and analysis_at >= _utc(current_asset.valid_to))):
        return result("outside_validity", "当前设施资料未生效或已过期，未作为该时点的已核验候选")
    if snapshot_asset.asset_version_id is not None:
        version = db.query(JurisdictionAssetVersion).filter_by(
            id=snapshot_asset.asset_version_id, asset_id=current_asset.id).first()
        if version is None:
            return result("version_unavailable", "快照引用的设施来源版本不可用")
        if ((version.valid_from and analysis_at < _utc(version.valid_from))
                or (version.valid_to and analysis_at >= _utc(version.valid_to))):
            return result("outside_validity", "快照所引来源资料不覆盖当前计算时点")
    for key in ("source_id", "source_identity_id", "identity_decision_id"):
        if saved.get(key) != current.get(key):
            return result("snapshot_source_changed", "快照与当前来源身份或映射决定不一致，需重新发布地图")
    source_id = saved.get("source_id")
    if source_id is not None:
        source = db.query(MapSource).populate_existing().filter_by(
            id=source_id, operational_area_id=current_asset.operational_area_id, status="active").first()
        if source is None or source.source_type == "public_map":
            return result("source_unavailable", "生产来源当前不可用，不借用公共参考或受限来源")
    identity_id = saved.get("source_identity_id")
    if identity_id is not None:
        identity = db.query(FacilitySourceIdentity).populate_existing().filter_by(id=identity_id,
            operational_area_id=current_asset.operational_area_id, source_id=source_id,
            asset_type=current_asset.asset_type).first()
        if identity is None:
            return result("identity_unavailable", "当前来源身份不可访问或与设施类型不符")
        decision = db.query(FacilityIdentityDecision).populate_existing().filter_by(identity_id=identity_id).order_by(
            FacilityIdentityDecision.sequence.desc()).first()
        stamp["latest_decision_id"] = decision.id if decision else None
        stamp["latest_target_id"] = decision.target_asset_id if decision else identity.native_asset_id
        if decision and decision.action == "revoke":
            return result("identity_revoked", "快照来源身份对应已被撤销，不再用于新候选")
        if (stamp["latest_target_id"] != current_asset.id
                or stamp["latest_decision_id"] != saved.get("identity_decision_id")):
            return result("snapshot_identity_changed", "当前身份对应已变化，旧快照不是当前依据")
    return result("ready", "当前设施来源状态与已保存快照引用一致")


def verified_entrances(db, *, assets: dict, network_id, analysis_at, vehicle) -> dict:
    binding = resolve_network(db, network_id, analysis_at=analysis_at, vehicle=vehicle)
    network = db.query(RoadNetworkVersion).populate_existing().filter_by(id=network_id).one()
    manifest = network.source_manifest or {}
    inputs = (manifest.get("governance_plan") or {}).get("inputs") or {}
    source_ids = inputs.get("source_ids", [])
    if not source_ids:
        return {}  # Public road points are not trusted facility entrances.
    included = {(row["source_id"], row["feature_id"]): row for row in inputs.get("included", [])}
    all_roads = {**{(row["source_id"], row["feature_id"]): row for row in inputs.get("excluded", [])}, **included}
    version = InternalRoadFeatureVersion
    latest = db.query(version.source_id.label("source_id"), version.feature_id.label("feature_id"),
        func.max(version.import_id).label("import_id")).filter(version.source_id.in_(source_ids))\
        .group_by(version.source_id, version.feature_id).subquery()
    versions = db.query(version).join(latest, and_(version.source_id == latest.c.source_id,
        version.feature_id == latest.c.feature_id, version.import_id == latest.c.import_id))\
        .filter(version.kind == "entrance").order_by(version.source_id, version.feature_id).limit(10001).all()
    if len(versions) > 10000:
        raise ValueError("facility_entrance_catalog_requires_partition")
    ids = {row.import_id for row in versions}
    batches = {row.id: row for row in db.query(InternalRoadImport).filter(InternalRoadImport.id.in_(ids)).all()}
    reviews = {}
    for row in db.query(InternalRoadReview).filter(InternalRoadReview.import_id.in_(ids))\
            .order_by(InternalRoadReview.sequence).all():
        reviews[(row.import_id, row.feature_id)] = row
    result = {}
    for row in versions:
        batch = batches.get(row.import_id)
        if batch is None or _utc(batch.created_at) > analysis_at:
            continue
        feature = next((item for item in batch.features if item["id"] == row.feature_id), None)
        if feature is None:
            raise ValueError("facility_entrance_source_integrity")
        properties = feature["properties"]
        asset_id = properties.get("facility_asset_id")
        if type(asset_id) is not int or asset_id not in assets or assets[asset_id]["area_id"] != row.operational_area_id:
            continue
        review = reviews.get((row.import_id, row.feature_id))
        connection = review.connection_evidence if review else None
        road_key = (row.source_id, properties["road_id"])
        road = all_roads.get(road_key)
        if (not review or review.decision != "verified" or _utc(review.created_at) > analysis_at
                or not connection or connection.get("status") != "connected"
                or connection.get("facility_asset_id") != asset_id or road is None
                or road["import_id"] != connection.get("road_import_id")
                or road["input_sha256"] != connection.get("road_source_sha256")):
            continue
        conditions = InternalRoadConditions.model_validate_json(json.dumps(properties.get("conditions", {})))
        eligible = internal_road_eligibility(conditions=conditions, vehicle=vehicle, verified=True,
            traversal_permitted=road_key in included, at=analysis_at)
        geometry = feature["geometry"]
        if geometry.get("type") != "Point":
            raise ValueError("facility_entrance_geometry_invalid")
        point = RoadLocation(longitude=geometry["coordinates"][0], latitude=geometry["coordinates"][1])
        # Keep every verified entrance; distance comparison happens downstream.
        result.setdefault(asset_id, []).append({"point": point.model_dump(), "source_id": row.source_id,
            "import_id": row.import_id, "feature_id": row.feature_id, "input_sha256": batch.input_sha256,
            "review_id": review.id, "road_import_id": road["import_id"], "road_feature_id": road["feature_id"],
            "graph_sha256": binding.graph_sha256, "eligible": eligible.include,
            "reason": eligible.reason if road_key in included else road.get("reason", "road_not_in_effective_graph")})
    return result


def freeze_facility_pool(db, *, result_id: str, network_id: str, analysis_at: datetime, vehicle,
                         scan_state=None, on_scan_checkpoint=None, scan_limit=None,
                         scan_budget_seconds=5) -> dict:
    if "authorized_area_ids" not in db.info or type(db.info.get("principal_user_id")) is not int:
        raise PermissionError("facility_recall_scope_required")
    source = CaseResultService.read(db, result_id)
    content, versions = source["content"], source["content"]["versions"]
    if not versions["map_snapshot_id"]:
        raise ValueError("facility_recall_map_missing")
    profile = db.query(CaseAnalysisProfile).populate_existing().filter_by(id=versions["case_profile_id"]).first()
    case = db.query(Case).populate_existing().filter_by(id=content["case_id"]).first()
    snapshot = db.query(MapSnapshot).filter_by(id=versions["map_snapshot_id"]).first()
    if case is None or profile is None or snapshot is None:
        raise PermissionError("facility_recall_source_unavailable")
    revision_id = _require_current_case_profile(db, case, profile, versions)
    # Legacy no-process snapshots keep their old hash; bind the revision only in
    # this newly created pool. Completely unversioned legacy fixtures still work.
    if revision_id is not None:
        versions = {**versions, "source_revision_id": revision_id}
    facts = content["related_conditions"]
    if facts.get("latitude") is None or facts.get("longitude") is None:
        raise ValueError("facility_recall_origin_missing")
    origin = RoadLocation(latitude=facts["latitude"], longitude=facts["longitude"])
    standard = content["facts_summary"]["recorded_fields"]
    state = dict(scan_state or {})
    known_at = (datetime.fromisoformat(state["known_at"]) if state else datetime.now(timezone.utc))
    window = case_window(standard)
    temporal_args = {key: datetime.fromisoformat(window[key]) if window[key] else None
                     for key in ("valid_at", "valid_from", "valid_to")}
    history = (state["history"] if state else
               history_context(db, source, known_at=known_at, knowledge_mode="retrospective"))
    if state and (state["result_id"] != result_id or state["content_sha256"] != source["content_sha256"]
                  or state["versions"] != versions):
        raise ValueError("facility_scan_source_changed")
    min_lat, max_lat, min_lon, max_lon = bounding_box(origin.latitude, origin.longitude, 50)
    query = db.query(MapSnapshotFeature, JurisdictionAsset).populate_existing().join(JurisdictionAsset, JurisdictionAsset.id == MapSnapshotFeature.asset_id).filter(MapSnapshotFeature.snapshot_id == snapshot.id,
        MapSnapshotFeature.status == "active", MapSnapshotFeature.asset_type.in_(SOURCE_TYPES),
        MapSnapshotFeature.latitude.between(min_lat, max_lat), MapSnapshotFeature.longitude.between(min_lon, max_lon))
    heap = [tuple(entry[:3]) + (entry[3],) for entry in state.get("heap", [])]
    heapq.heapify(heap)
    scanned, within_radius = state.get("scanned", 0), state.get("within_radius", 0)
    cursor, complete = state.get("cursor", 0), bool(state.get("scan_complete"))
    deadline = time.monotonic() + scan_budget_seconds
    def save_scan():
        nonlocal state
        state = {**state, "result_id": result_id, "content_sha256": source["content_sha256"],
                 "versions": versions, "known_at": known_at.isoformat(), "history": history,
                 "cursor": cursor, "scanned": scanned, "within_radius": within_radius,
                 "scan_complete": complete, "heap": heap}
        if on_scan_checkpoint is not None:
            on_scan_checkpoint(json.loads(json.dumps(state)))
    if not state:
        save_scan()  # Freeze retrieval/known-time before the first potentially slow row.
    remaining = query.filter(MapSnapshotFeature.asset_id > cursor).order_by(MapSnapshotFeature.asset_id)
    scan_rows = [] if complete else (remaining.limit(scan_limit + 1).all() if scan_limit else remaining.yield_per(100))
    complete = True
    processed = 0
    for asset, current_asset in scan_rows:
        if scan_limit is not None and processed >= scan_limit:
            complete = False
            break
        if time.monotonic() >= deadline:
            complete = False
            break
        scanned += 1
        processed += 1
        cursor = asset.asset_id
        distance = haversine_km(origin.latitude, origin.longitude, asset.latitude, asset.longitude) * 1000
        if distance > 50_000 or asset.source in SOURCE_EXCLUDED:
            continue
        within_radius += 1
        guard = _current_source_guard(db, asset, current_asset, analysis_at)
        verified = bool(asset.verified) and guard["state"] == "ready"
        temporal = _production_context(db, asset.asset_id, **temporal_args, known_at=known_at)
        historical_snapshot = temporal.get("snapshot") or {}
        attributes = historical_snapshot.get("attributes") or {}
        details = temporal.get("groups", {}).get("details", {})
        production_verified = (verified and details.get("coverage") == "full" and all(
            row["values"].get("verified") is True and row["values"].get("status") == "active" for row in details.get("segments", [])))
        oil = (group_match(temporal, "details", lambda value: None if not standard.get("oil_type") or not value.get("oil_type")
                           else standard["oil_type"] == value["oil_type"]) if production_verified else "unknown")
        detail_values = [row["values"] for row in details.get("segments", []) if row["state"] == "ready"]
        facility_type = detail_values[0].get("asset_type") if detail_values and all(
            row.get("asset_type") == detail_values[0].get("asset_type") for row in detail_values) else None
        if detail_values and all(row.get("oil_type") == detail_values[0].get("oil_type") for row in detail_values):
            attributes = {**attributes, "oil_type": detail_values[0].get("oil_type")}
        expected_types = FACILITY_TERMS.get(facility_type, set())
        facility = ("unknown" if not production_verified or not standard.get("facility_type") or not expected_types else
                    "matched" if standard["facility_type"] in expected_types else "different")
        production = production_comparison(attributes=attributes, verified=verified,
                                           case_fields=standard, case_facts=facts, temporal_context=temporal)
        historical = facility_history_match(history, asset_type=facility_type,
                                             oil_type=attributes.get("oil_type"), verified=production_verified)
        item = {"asset_id": asset.asset_id, "name": asset.name, "area_id": asset.operational_area_id,
                "snapshot_feature_id": asset.id, "asset_version_id": asset.asset_version_id,
                "evidence_ref": f"map_asset:{asset.asset_id}@snapshot:{snapshot.id}",
                "straight_distance_m": distance, "oil_match": oil, "facility_match": facility,
                "source_verified": verified, "current_source_state": guard["state"],
                "source_guard_sha256": guard["sha256"],
                "source_gap": guard["reason"] if guard["state"] != "ready" else None,
                "production_context": temporal,
                "production_context_sha256": _production_signature(temporal),
                "oil_values": {"case": standard.get("oil_type"), "facility": attributes.get("oil_type")},
                "facility_values": {"case": standard.get("facility_type"), "facility": facility_type},
                "production_comparison": production,
                "history_comparison": historical}
        # Attribute evidence participates in recall, rather than taking nearest N first.
        key = (int(oil == "matched") * 2 + int(facility == "matched") + int(production["state"] == "matched")
               + int(historical["state"] == "matched"), -distance, -asset.asset_id)
        entry = (*key, item)
        if len(heap) < 100:
            heapq.heappush(heap, entry)
        elif key > heap[0][:3]:
            heapq.heapreplace(heap, entry)
    # Conservatively yield if the last source lookup itself used up the slice.
    # The persisted cursor means a later claim can confirm the exhausted range
    # without recalculating that row.
    complete = complete and time.monotonic() < deadline
    save_scan()
    if on_scan_checkpoint is not None and not complete:
        return {"pending": True, "scan_state": state}
    assets = {item[3]["asset_id"]: item[3] for item in sorted(heap, reverse=True)}
    entrances = {int(key): value for key, value in state.get("entrances", {}).items()}
    entrance_cursor = state.get("entrance_cursor", 0)
    asset_ids = list(assets)
    while entrance_cursor < len(asset_ids):
        if on_scan_checkpoint is not None and time.monotonic() >= deadline:
            return {"pending": True, "scan_state": state}
        batch_size = 25 if on_scan_checkpoint is not None else len(asset_ids)
        chosen = asset_ids[entrance_cursor:entrance_cursor + batch_size]
        entrances.update(verified_entrances(db, assets={key: assets[key] for key in chosen},
            network_id=network_id, analysis_at=analysis_at, vehicle=vehicle))
        entrance_cursor += len(chosen)
        state = {**state, "entrances": entrances, "entrance_cursor": entrance_cursor,
                 "entrance_total": len(asset_ids)}
        save_scan()
    rows, points = [], {}
    for asset_id, asset in assets.items():
        all_entries = entrances.get(asset_id, [])
        entries = [entry for entry in all_entries if entry["eligible"]]
        state = entrance_state(all_entries, source_verified=asset["source_verified"])
        ready, restricted = state == "not_calculated", state == "restricted"
        evidence = FacilityEvidence(asset_id=asset_id, evidence_ref=asset["evidence_ref"],
            straight_distance_m=asset["straight_distance_m"], road_state=state,
            entrance_verified=ready, passage_allowed=True if ready else False if restricted else None,
            oil_match=asset["oil_match"], facility_match=asset["facility_match"],
            production_match=asset["production_comparison"]["state"],
            historical_match=asset["history_comparison"]["state"],
            attribute_refs=(f"case_profile:{profile.id}", asset["evidence_ref"],
                            *_production_refs(asset["production_context"]),
                            *(f"case:{identifier}" for identifier in asset["history_comparison"]["case_ids"])))
        asset["entrances"] = all_entries
        asset["entrance_state"] = "verified" if ready else "unknown"
        rows.append(asdict(evidence))
        if ready:
            points[asset_id] = [entry["point"] for entry in entries]
    payload = {"schema_version": RECALL_VERSION, "result_id": result_id, "content_sha256": source["content_sha256"],
        "versions": {**versions, "recall_version": RECALL_VERSION, "production_version": PRODUCTION_VERSION}, "origin": origin.model_dump(),
        "assets": list(assets.values()), "evidence": rows, "entrances": points,
        "source_checked_at": analysis_at.isoformat(), "production_known_at": known_at.isoformat(),
        "history": history,
        "coverage": {"scanned": scanned, "within_radius": within_radius, "selected": len(rows),
                     "radius_m": 50_000, "complete": complete and within_radius <= 100,
                     "scan_complete": complete, "scan_budget_seconds": scan_budget_seconds, "candidate_limit": 100,
                     "entrance_facilities_checked": entrance_cursor, "entrance_facilities_total": len(assets),
                     "entrance_check_complete": entrance_cursor == len(assets),
                     "unselected_in_radius": max(0, within_radius - len(rows))},
        "boundary": "授权快照内50公里生产设施；属性条件参与召回。未选尽或未扫完时不宣称全域最优；入口未知不猜测。"}
    payload = json.loads(json.dumps(payload, ensure_ascii=False))
    return {**payload, "input_sha256": digest(payload)}


def require_current_pool_source(db, pool):
    """Reject stale automatic computation; historical reads remain available."""
    if pool.get("dependency_context"):
        from app.services.facility_dependency_guard import require_dependencies
        require_dependencies(db, pool["dependency_context"])
    versions = pool["versions"]
    profile = db.query(CaseAnalysisProfile).populate_existing().filter_by(id=versions["case_profile_id"]).first()
    case = db.query(Case).populate_existing().filter_by(id=profile.case_id).first() if profile else None
    _require_current_case_profile(db, case, profile, versions)
    if "history" in pool:
        validate_history_access(db, pool["history"], require_fresh=True)
    if not pool.get("source_checked_at"):
        raise ValueError("facility_pool_source_guard_missing")
    at = datetime.fromisoformat(pool["source_checked_at"])
    if at.tzinfo is None:
        raise ValueError("facility_pool_source_guard_missing")
    for item in pool["assets"]:
        row = db.query(MapSnapshotFeature, JurisdictionAsset).populate_existing().join(
            JurisdictionAsset, JurisdictionAsset.id == MapSnapshotFeature.asset_id).filter(
                MapSnapshotFeature.snapshot_id == versions["map_snapshot_id"],
                MapSnapshotFeature.asset_id == item["asset_id"]).first()
        if row is None:
            raise PermissionError("facility_pool_access_changed")
        if _current_source_guard(db, row[0], row[1], at)["sha256"] != item.get("source_guard_sha256"):
            raise ValueError("facility_pool_source_changed")
        temporal = item.get("production_context")
        if temporal is not None:
            valid_at = datetime.fromisoformat(temporal["valid_at"]) if temporal.get("valid_at") else None
            current = _production_context(db, item["asset_id"], valid_at=valid_at,
                valid_from=datetime.fromisoformat(temporal["query_interval"]["from"]) if temporal.get("query_interval") else None,
                valid_to=datetime.fromisoformat(temporal["query_interval"]["to"]) if temporal.get("query_interval") else None,
                known_at=datetime.now(timezone.utc))
            if _production_signature(current) != item["production_context_sha256"]:
                raise ValueError("facility_pool_production_changed")


def validate_pool_access(db, pool):
    """Readonly current access check for every frozen facility, including unselected ones."""
    if digest({key: value for key, value in pool.items() if key != "input_sha256"}) != pool["input_sha256"]:
        raise ValueError("facility_pool_integrity_invalid")
    source = CaseResultService.read(db, pool["result_id"])
    if source["content_sha256"] != pool["content_sha256"]:
        raise ValueError("facility_pool_case_version_changed")
    snapshot_id = pool["versions"]["map_snapshot_id"]
    if source["content"]["versions"]["map_snapshot_id"] != snapshot_id:
        raise ValueError("facility_pool_map_version_changed")
    ids = [item["asset_id"] for item in pool["assets"]]
    visible = db.query(MapSnapshotFeature.asset_id).join(JurisdictionAsset, JurisdictionAsset.id == MapSnapshotFeature.asset_id).filter(MapSnapshotFeature.snapshot_id == snapshot_id,
                                                          MapSnapshotFeature.asset_id.in_(ids)).all()
    if len(ids) != len(set(ids)) or {row[0] for row in visible} != set(ids):
        raise PermissionError("facility_pool_access_changed")
    if "history" in pool:
        validate_history_access(db, pool["history"])
    for asset in pool["assets"]:
        temporal = asset.get("production_context")
        if temporal and temporal.get("schema_version") == "facility-temporal-7.3-1":
            try:
                validate_temporal_access(db, temporal)
            except (LookupError, PermissionError) as error:
                raise PermissionError("facility_pool_production_unavailable") from error
            continue
        if not temporal or temporal.get("version_id") is None:
            continue
        for identifier in set([temporal["version_id"], *temporal.get("supporting_version_ids", [])]):
            version = db.query(JurisdictionAssetVersion).populate_existing().filter_by(id=identifier).first()
            if (version is None or (identifier == temporal["version_id"] and version.snapshot != temporal["snapshot"])
                    or db.query(JurisdictionAsset.id).filter_by(id=version.asset_id).first() is None):
                raise PermissionError("facility_pool_production_unavailable")
            source_id = (version.snapshot.get("attributes") or {}).get("source_id")
            if source_id is not None and db.query(MapSource.id).filter_by(id=source_id, status="active").first() is None:
                raise PermissionError("facility_pool_production_unavailable")
