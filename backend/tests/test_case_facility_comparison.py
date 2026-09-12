"""Real isolated persistence/permissions; routing responses remain synthetic."""
from datetime import datetime, timedelta
from copy import deepcopy

import pytest

from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.internal_roads import InternalRoadImport, InternalRoadFeatureVersion, InternalRoadReview
from app.models.map_foundation import MapSource, MapSnapshot, MapSnapshotFeature
from app.models.road_network import RoadNetworkVersion, RoadAccessMembership
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_result_service import CaseResultService
from app.services.case_road_jobs import enqueue_comparison, process_comparison
from app.services.case_road_status import automatic_comparison_status
from app.services.case_road_artifact_service import read_road_artifact
from app.services.facility_candidate_pool import freeze_facility_pool, validate_pool_access
from app.services.road_access_policy import VehicleAssumption
from app.services.road_source_revision import source_revision
from app.services.public_road_access import NODE_POLICY_VERSION
from test_road_network_service import ready  # noqa: F401
from test_case_results import db_session, result_data  # noqa: F401
from test_road_access_policy import AT


VEHICLE = VehicleAssumption(kind="auto", source="explicit_reference_assumption")


@pytest.fixture
def prepared(ready, monkeypatch):
    db = ready
    case = db.get(Case, 1)
    profile = db.get(CaseAnalysisProfile, "profile-1")
    db.get(MapSnapshot, "map-1").status = "current"
    profile.is_current = True
    profile.source_hash = CasePipelineService.source_hash(db, case)
    profile.payload = {**profile.payload, "source_hash": profile.source_hash,
        "standard": {"oil_type": "原油", "facility_type": "井口", "location": "合成地点"},
        "analysis_facts": {"latitude": 46., "longitude": 125.}}
    db.add(MapSource(id=10, operational_area_id=1, source_key="facility-roads", name="合成道路来源", source_type="internal_gis"))
    db.flush()
    features = [{"id": "road", "type": "Feature", "properties": {"kind": "road", "name": "生产路"},
                 "geometry": {"type": "LineString", "coordinates": [[125, 46], [125.02, 46]]}}]
    for i in range(2, 14):
        db.add(JurisdictionAsset(id=i, operational_area_id=1, name=f"合成设施{i}", asset_type="well"))
        db.add(MapSnapshotFeature(snapshot_id="map-1", asset_id=i, operational_area_id=1,
            name=f"合成设施{i}", asset_type="well", geometry_type="point", source="manual", status="active",
            verified=True, latitude=46., longitude=125 + i / 1000,
            attributes={"oil_type": "原油" if i == 13 else "柴油"}))
        features.append({"id": f"gate-{i}", "type": "Feature", "geometry": {"type": "Point", "coordinates": [125 + i / 1000, 46]},
            "properties": {"kind": "entrance", "name": f"入口{i}", "road_id": "road", "facility_asset_id": i,
                           "conditions": {"gate": "open", "access": "permitted", "direction": "both"}}})
    db.add(InternalRoadImport(id=100, source_id=10, operational_area_id=1, input_sha256="e" * 64,
        schema_version="test", features=features, warnings=[], created_by=1, created_at=AT - timedelta(minutes=10)))
    db.flush()
    for item in features:
        db.add(InternalRoadFeatureVersion(import_id=100, source_id=10, operational_area_id=1,
            feature_id=item["id"], name=item["properties"]["name"], kind=item["properties"]["kind"]))
        if item["id"] != "road":
            db.add(InternalRoadReview(import_id=100, operational_area_id=1, feature_id=item["id"], sequence=1,
                request_key=item["id"], decision="verified", note="合成核验", evidence_reference="合成依据", created_by=1,
                created_at=AT - timedelta(minutes=5), connection_evidence={"road_import_id": 100,
                    "road_source_sha256": "e" * 64, "status": "connected", "facility_asset_id": item["properties"]["facility_asset_id"]}))
    db.commit()
    graph = db.get(RoadNetworkVersion, "graph-1")
    revision = source_revision(db, source_ids=[10], group_id=1, public_bundle_id=1, public_source_sha256="f" * 64)
    graph.source_manifest = {**graph.source_manifest, "source_revision": revision,
        "filter_result": {"public_node_access_policy_version": NODE_POLICY_VERSION},
        "governance_plan": {"public_source_sha256": "f" * 64, "inputs": {"source_ids": [10], "included": [
            {"source_id": 10, "feature_id": "road", "import_id": 100, "input_sha256": "e" * 64}]}}}
    db.commit()
    source, _ = CaseResultService.create_current(db, 1)
    db.commit()
    calls = []
    def matrix(_db, **kwargs):
        calls.append(kwargs)
        return {"network_id": "graph-1", "graph_sha256": "c" * 64, "policy_revision": 1,
            "cells": [{"source_index": 0, "target_index": j, "status": "calculated",
                "distance_m": (20 - round((point.longitude - 125) * 1000)) * 1000} for j, point in enumerate(kwargs["targets"])]}
    monkeypatch.setattr("app.services.facility_road_batches.calculate_distance_matrix", matrix)
    return db, source, calls


def freeze(db, source):
    return freeze_facility_pool(db, result_id=source["id"], network_id="graph-1", analysis_at=AT, vehicle=VEHICLE)


def test_recall_uses_full_authorized_snapshot_not_old_top_three(prepared):
    db, source, _ = prepared
    original = deepcopy(source)
    pool = freeze(db, source)
    assert len(pool["assets"]) == 12 and pool["coverage"]["complete"]
    assert pool["assets"][0]["asset_id"] == 13  # Oil attributes before nearest-only recall.
    assert len(pool["entrances"]) == 12
    validate_pool_access(db, pool)  # Integer JSON key normalization is stable.
    assert source == original
    db.info["authorized_area_ids"] = ()
    with pytest.raises(PermissionError):
        validate_pool_access(db, pool)


def test_frozen_pool_cannot_retain_asset_moved_out_of_scope(prepared):
    db, source, _ = prepared
    pool = freeze(db, source)
    db.query(JurisdictionAsset).filter_by(id=12).update({"operational_area_id": 2})
    db.commit()
    with pytest.raises(PermissionError, match="access_changed"):
        validate_pool_access(db, pool)
    assert all(item["asset_id"] != 12 for item in freeze(db, source)["assets"])


def test_production_and_authorized_old_history_are_grounded_before_routing(prepared, tmp_path):
    from app.services.case_facility_comparison import compare_case_facilities
    db, _, _ = prepared
    case = db.get(Case, 1)
    case.description = "井场发生打孔盗油"
    case.occurred_time = datetime(2026, 9, 12)
    case.modus_operandi = "打孔盗油"
    case.oil_type = "原油"
    case.facility_type = "井口"
    case.water_cut = 30.0
    profile = db.get(CaseAnalysisProfile, "profile-1")
    db.flush()
    profile.source_hash = CasePipelineService.source_hash(db, case)
    profile.payload = {**profile.payload, "source_hash": profile.source_hash,
        "standard": {**profile.payload["standard"], "occurred_time": case.occurred_time.isoformat(),
                     "modus_operandi": case.modus_operandi},
        "analysis_facts": {**profile.payload["analysis_facts"], "water_cut": 30}}
    for identifier, area, when in ((3, 1, datetime(2020, 1, 1)), (4, 2, datetime(2020, 1, 1)), (5, 1, datetime(2027, 1, 1))):
        db.add(Case(id=identifier, operational_area_id=area, case_number=f"HIST-{identifier}",
            occurred_time=when, description="井场发生打孔盗油", modus_operandi="打孔盗油", oil_type="原油", facility_type="井口"))
    asset = db.query(MapSnapshotFeature).filter_by(asset_id=13).one()
    asset.attributes = {**asset.attributes, "water_cut_min": 20, "water_cut_max": 40, "water_cut_unit": "percent",
        "production_valid_from": "2026-09-01T00:00:00Z", "production_valid_to": "2026-10-01T00:00:00Z"}
    db.commit()
    source, _ = CaseResultService.create_current(db, 1)
    db.commit()
    result = compare_case_facilities(db, result_id=source["id"], network_id="graph-1", analysis_at=AT,
        vehicle=VEHICLE, artifact_root=tmp_path)
    best = result["result"]["candidates"][0]
    assert best["asset_id"] == 13
    assert best["components"]["production_match"] == 10
    assert best["components"]["historical_match"] == 10
    assert "case:3" in best["evidence_refs"] and "case:4" not in best["evidence_refs"]
    assert [record["case_id"] for record in result["pool"]["history"]["records"]] == [3]
    assert any("含水率 30%" in text for text in best["supporting_evidence"])
    assert any("不证明其与本设施" in text for text in best["counter_evidence"])
    from app.services.facility_candidate_pool import require_current_pool_source
    db.query(Case).filter_by(id=3).update({"description": "历史原文已补充"})
    db.commit()
    # Frozen history remains readable, but cannot become a new current result.
    validate_pool_access(db, result["pool"])
    with pytest.raises(ValueError, match="history_source_changed"):
        require_current_pool_source(db, result["pool"])
    db.query(Case).filter_by(id=3).update({"operational_area_id": 2})
    db.commit()
    with pytest.raises(PermissionError, match="history_access_changed"):
        validate_pool_access(db, result["pool"])


def test_automatic_job_persists_ranked_pool_and_read_export_recheck_permissions(prepared, tmp_path):
    from app.services.case_road_document import attach_road_document
    from app.services.case_result_document import build_case_result_document
    db, source, calls = prepared
    original = db.get(Case, 1).description
    job = enqueue_comparison(db, result_id=source["id"], analysis_at=AT, vehicle=VEHICLE,
        engine_version="valhalla-test", include_facility_pool=True)
    db.commit()
    result = process_comparison(db, job["event_id"], artifact_root=tmp_path)
    assert result["status"] == "completed", result
    assert [len(call["targets"]) for call in calls] == [10, 2]
    status = automatic_comparison_status(db, source["id"])
    artifact = status["artifact"]
    assert status["status"] == "completed" and artifact["content"]["schema_version"] == "case-facility-comparison-5.2-1"
    ranked = artifact["content"]["result"]
    assert ranked["coverage"]["compared"] == 12 and ranked["candidates"][0]["asset_id"] == 13
    assert len(ranked["candidates"]) == 3
    document = attach_road_document(build_case_result_document(source), artifact)
    text = "\n".join(block.text for block in document.blocks)
    assert "合成设施13" in text and "道路前置来源候选" in text
    assert db.get(Case, 1).description == original
    db.query(RoadAccessMembership).delete()
    db.commit()
    with pytest.raises(PermissionError):
        read_road_artifact(db, artifact["id"])


def test_missing_facility_confirmation_never_becomes_verified_entry(prepared):
    db, source, _ = prepared
    review = db.query(InternalRoadReview).filter_by(feature_id="gate-13").one()
    review.connection_evidence = {key: value for key, value in review.connection_evidence.items() if key != "facility_asset_id"}
    db.commit()
    # A review change first invalidates the graph, not just the UI note.
    with pytest.raises(PermissionError):
        freeze(db, source)
    graph = db.get(RoadNetworkVersion, "graph-1")
    graph.source_manifest = {**graph.source_manifest, "source_revision": source_revision(
        db, source_ids=[10], group_id=1, public_bundle_id=1, public_source_sha256="f" * 64)}
    db.commit()
    pool = freeze(db, source)
    assert "13" not in pool["entrances"]
    assert next(row for row in pool["evidence"] if row["asset_id"] == 13)["road_state"] == "entrance_unknown"


def test_case_change_during_routing_does_not_publish_stale_automatic_result(prepared, monkeypatch, tmp_path):
    from app.models.case_road_artifact import CaseRoadArtifact
    from app.services import facility_road_batches as batches
    db, source, _ = prepared
    original = batches.calculate_distance_matrix
    def change_case(*args, **kwargs):
        value = original(*args, **kwargs)
        db.query(Case).filter_by(id=1).update({"description": "案件原文已更新"})
        db.commit()
        return value
    monkeypatch.setattr(batches, "calculate_distance_matrix", change_case)
    job = enqueue_comparison(db, result_id=source["id"], analysis_at=AT, vehicle=VEHICLE,
        engine_version="valhalla-test", include_facility_pool=True)
    db.commit()
    result = process_comparison(db, job["event_id"], artifact_root=tmp_path)
    assert result["status"] != "completed"
    assert db.query(CaseRoadArtifact).count() == 0
    assert CaseResultService.read(db, source["id"])["content_sha256"] == source["content_sha256"]


def test_facility_route_uses_saved_entry_and_retains_parent_authorization(prepared, monkeypatch, tmp_path):
    from app.services import facility_reference_route as routes
    from app.services.case_facility_comparison import compare_case_facilities
    from app.services.case_road_artifact_service import freeze_road_artifact
    db, source, _ = prepared
    content = compare_case_facilities(db, result_id=source["id"], network_id="graph-1", analysis_at=AT,
        vehicle=VEHICLE, artifact_root=tmp_path)
    parent = freeze_road_artifact(db, content)
    db.commit()
    calls = []
    def calculate(_db, **kwargs):
        calls.append(kwargs)
        return {**content["calculation"], "distance_m": 7000, "shape_polyline6": "synthetic"}
    monkeypatch.setattr(routes, "calculate_reference_route", calculate)
    params = dict(comparison_id=parent["id"], comparison_sha256=parent["content_sha256"], asset_id=13,
        analysis_at=AT, vehicle=VEHICLE, artifact_root=tmp_path)
    route = routes.route_facility_candidate(db, **params)
    assert calls[0]["end"].longitude == 125.013
    assert calls[0]["start"].longitude == 125
    assert route["target"]["entrance"]["feature_id"] == "gate-13"
    saved = freeze_road_artifact(db, route)
    db.commit()
    stored = read_road_artifact(db, saved["id"])
    assert stored["content"]["facility_comparison"] == {
        "id": parent["id"], "content_sha256": parent["content_sha256"]}
    from app.services.case_road_document import attach_road_document
    from app.services.case_result_document import build_case_result_document
    document = attach_road_document(build_case_result_document(source), stored)
    assert any(("入口来源编号", "gate-13") in block.rows for block in document.blocks)
    mismatched = deepcopy(route)
    mismatched["target"]["entrance"]["feature_id"] = "different-gate"
    with pytest.raises(ValueError, match="parent_changed"):
        freeze_road_artifact(db, mismatched)
    with pytest.raises(ValueError, match="not_selected"):
        routes.route_facility_candidate(db, **{**params, "asset_id": 2})
    with pytest.raises(ValueError, match="version_changed"):
        routes.route_facility_candidate(db, **{**params, "comparison_sha256": "0" * 64})
    assert len(calls) == 1
    db.query(RoadAccessMembership).delete()
    db.commit()
    with pytest.raises(PermissionError):
        read_road_artifact(db, saved["id"])


def test_facility_route_api_rejects_client_endpoints_and_persists_success(prepared, monkeypatch):
    from test_road_analysis_api import client
    from app.services import facility_reference_route as routes
    from app.services.case_facility_comparison import compare_case_facilities
    from app.services.case_road_artifact_service import freeze_road_artifact
    db, source, _ = prepared
    content = compare_case_facilities(db, result_id=source["id"], network_id="graph-1", analysis_at=AT,
        vehicle=VEHICLE, artifact_root=None)
    parent = freeze_road_artifact(db, content)
    db.commit()
    monkeypatch.setattr(routes, "calculate_reference_route", lambda *args, **kwargs: {
        **content["calculation"], "distance_m": 7000, "shape_polyline6": "synthetic"})
    url = f"/api/road-analysis/artifacts/{parent['id']}/facilities/13/routes"
    body = {"content_sha256": parent["content_sha256"]}
    response = client(db).post(url, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["artifact"]["id"]
    for field in ("end", "network_id", "vehicle", "ignore_restrictions"):
        assert client(db).post(url, json={**body, field: "untrusted"}).status_code == 422
    assert client(db, "viewer").post(url, json=body).status_code == 403
    assert client(db, None).post(url, json=body).status_code == 401
