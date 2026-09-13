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
from app.models.map_foundation import MapSnapshot, MapSnapshotFeature
from app.models.road_network import RoadNetworkVersion
from app.services.case_result_service import CaseResultService
from app.services.case_pipeline_service import CasePipelineService
from app.services.facility_production_conditions import production_comparison, VERSION as PRODUCTION_VERSION
from app.services.facility_history_conditions import history_context, facility_history_match, validate_history_access
from app.services.road_access_policy import InternalRoadConditions, internal_road_eligibility
from app.services.road_network_service import resolve_network
from app.services.scorers.facility_roads_v52 import FacilityEvidence
from app.services.scorers.dual_domain_v34 import SOURCE_TYPES
from app.services.vehicle_router import RoadLocation
from app.utils.geo import bounding_box, haversine_km


RECALL_VERSION = "facility-recall-5.2-1"
SOURCE_EXCLUDED = frozenset({"public_map", "osm", "openstreetmap", "public_reference"})
FACILITY_TERMS = {"well": {"油井", "采油井", "井口"}, "valve": {"阀门"},
                  "station": {"站库", "集油站"}, "pipeline_node": {"管线", "输油管线"}}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _utc(value):
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


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


def freeze_facility_pool(db, *, result_id: str, network_id: str, analysis_at: datetime, vehicle) -> dict:
    if "authorized_area_ids" not in db.info or type(db.info.get("principal_user_id")) is not int:
        raise PermissionError("facility_recall_scope_required")
    source = CaseResultService.read(db, result_id)
    content, versions = source["content"], source["content"]["versions"]
    if not versions["map_snapshot_id"]:
        raise ValueError("facility_recall_map_missing")
    profile = db.query(CaseAnalysisProfile).filter_by(id=versions["case_profile_id"]).first()
    case = db.query(Case).populate_existing().filter_by(id=content["case_id"]).first()
    snapshot = db.query(MapSnapshot).filter_by(id=versions["map_snapshot_id"]).first()
    if case is None or profile is None or snapshot is None:
        raise PermissionError("facility_recall_source_unavailable")
    if not profile.is_current or CasePipelineService.source_hash(db, case) != profile.source_hash:
        raise ValueError("facility_recall_source_outdated")
    facts = content["related_conditions"]
    if facts.get("latitude") is None or facts.get("longitude") is None:
        raise ValueError("facility_recall_origin_missing")
    origin = RoadLocation(latitude=facts["latitude"], longitude=facts["longitude"])
    standard = content["facts_summary"]["recorded_fields"]
    history = history_context(db, source)
    min_lat, max_lat, min_lon, max_lon = bounding_box(origin.latitude, origin.longitude, 50)
    query = db.query(MapSnapshotFeature).join(JurisdictionAsset, JurisdictionAsset.id == MapSnapshotFeature.asset_id).filter(MapSnapshotFeature.snapshot_id == snapshot.id,
        MapSnapshotFeature.status == "active", MapSnapshotFeature.asset_type.in_(SOURCE_TYPES),
        MapSnapshotFeature.latitude.between(min_lat, max_lat), MapSnapshotFeature.longitude.between(min_lon, max_lon))
    heap, scanned, within_radius, complete = [], 0, 0, True
    deadline = time.monotonic() + 5
    for asset in query.order_by(MapSnapshotFeature.asset_id).yield_per(100):
        if time.monotonic() >= deadline:
            complete = False
            break
        scanned += 1
        distance = haversine_km(origin.latitude, origin.longitude, asset.latitude, asset.longitude) * 1000
        if distance > 50_000 or asset.source in SOURCE_EXCLUDED:
            continue
        within_radius += 1
        attributes = asset.attributes if isinstance(asset.attributes, dict) else {}
        oil = ("unknown" if not asset.verified or not standard.get("oil_type") or not attributes.get("oil_type") else
               "matched" if standard["oil_type"] == attributes["oil_type"] else "different")
        facility = "matched" if asset.verified and standard.get("facility_type") in FACILITY_TERMS.get(asset.asset_type, set()) else "unknown"
        production = production_comparison(attributes=attributes, verified=asset.verified,
                                           case_fields=standard, case_facts=facts)
        historical = facility_history_match(history, asset_type=asset.asset_type,
                                             oil_type=attributes.get("oil_type"), verified=asset.verified)
        item = {"asset_id": asset.asset_id, "name": asset.name, "area_id": asset.operational_area_id,
                "snapshot_feature_id": asset.id, "asset_version_id": asset.asset_version_id,
                "evidence_ref": f"map_asset:{asset.asset_id}@snapshot:{snapshot.id}",
                "straight_distance_m": distance, "oil_match": oil, "facility_match": facility,
                "source_verified": asset.verified, "production_comparison": production,
                "history_comparison": historical}
        # Attribute evidence participates in recall, rather than taking nearest N first.
        key = (int(oil == "matched") * 2 + int(facility == "matched") + int(production["state"] == "matched")
               + int(historical["state"] == "matched"), -distance, -asset.asset_id)
        entry = (*key, item)
        if len(heap) < 100:
            heapq.heappush(heap, entry)
        elif key > heap[0][:3]:
            heapq.heapreplace(heap, entry)
    assets = {item[3]["asset_id"]: item[3] for item in sorted(heap, reverse=True)}
    entrances = verified_entrances(db, assets=assets, network_id=network_id, analysis_at=analysis_at, vehicle=vehicle)
    rows, points = [], {}
    for asset_id, asset in assets.items():
        all_entries = entrances.get(asset_id, [])
        entries = [entry for entry in all_entries if entry["eligible"]]
        ready = asset["source_verified"] and bool(entries)
        restricted = bool(all_entries) and not entries and all(entry["reason"] in {
            "explicitly_closed", "traversal_permission_denied"} for entry in all_entries)
        evidence = FacilityEvidence(asset_id=asset_id, evidence_ref=asset["evidence_ref"],
            straight_distance_m=asset["straight_distance_m"], road_state="not_calculated" if ready else "restricted" if restricted else "entrance_unknown",
            entrance_verified=ready, passage_allowed=True if ready else False if restricted else None,
            oil_match=asset["oil_match"], facility_match=asset["facility_match"],
            production_match=asset["production_comparison"]["state"],
            historical_match=asset["history_comparison"]["state"],
            attribute_refs=(f"case_profile:{profile.id}", asset["evidence_ref"],
                            *(f"case:{identifier}" for identifier in asset["history_comparison"]["case_ids"])))
        asset["entrances"] = all_entries
        asset["entrance_state"] = "verified" if ready else "unknown"
        rows.append(asdict(evidence))
        if ready:
            points[asset_id] = [entry["point"] for entry in entries]
    payload = {"schema_version": RECALL_VERSION, "result_id": result_id, "content_sha256": source["content_sha256"],
        "versions": {**versions, "recall_version": RECALL_VERSION, "production_version": PRODUCTION_VERSION}, "origin": origin.model_dump(),
        "assets": list(assets.values()), "evidence": rows, "entrances": points,
        "history": history,
        "coverage": {"scanned": scanned, "within_radius": within_radius, "selected": len(rows),
                     "radius_m": 50_000, "complete": complete and within_radius <= 100,
                     "scan_complete": complete},
        "boundary": "授权快照内50公里生产设施；属性条件参与召回。未选尽或未扫完时不宣称全域最优；入口未知不猜测。"}
    payload = json.loads(json.dumps(payload, ensure_ascii=False))
    return {**payload, "input_sha256": digest(payload)}


def require_current_pool_source(db, pool):
    """Reject stale automatic computation; historical reads remain available."""
    versions = pool["versions"]
    profile = db.query(CaseAnalysisProfile).populate_existing().filter_by(id=versions["case_profile_id"]).first()
    case = db.query(Case).populate_existing().filter_by(id=profile.case_id).first() if profile else None
    if case is None or not profile.is_current or CasePipelineService.source_hash(db, case) != versions["case_source_hash"]:
        raise ValueError("facility_recall_source_outdated")
    if "history" in pool:
        validate_history_access(db, pool["history"], require_fresh=True)


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
