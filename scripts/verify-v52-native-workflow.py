"""Offline synthetic end-to-end fixture, using real governed Valhalla routing.

Run inside the existing native image. No production DB, credentials, map downloads,
HTTP model or Redis broker is used. Registered worker tasks are invoked directly.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
from datetime import datetime, timedelta, timezone

os.environ.update(DATABASE_URL="sqlite://", ENVIRONMENT="test", SECRET_KEY=secrets.token_hex(32))
sys.path.insert(0, "/app")

import osmium
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.models  # noqa: F401
from app.database import Base
from app.models.case import Case
from app.models.case_pipeline import OutboxEvent
from app.models.case_road_artifact import CaseRoadArtifact
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSource, OperationalArea, PublicMapBundle, MapSnapshot, MapSnapshotFeature
from app.models.road_network import RoadAccessGroup, RoadAccessGrant, RoadAccessMembership
from app.models.user import User
from app.services.internal_road_service import ingest_roads, review_feature
from app.services.road_public_alias_service import AliasDecision, record_alias_decision
from app.services.road_build_job import run_road_build_job
from app.services.road_publication_service import publish_road_candidate
from app.services.road_access_policy import VehicleAssumption
from app.services.case_service import CaseService
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_insight_service import CaseInsightService
from app.services.case_road_artifact_service import read_road_artifact, freeze_road_artifact
from app.services.facility_reference_route import route_facility_candidate
from app.services.case_result_service import CaseResultService
from app.services.case_result_document import build_case_result_document
from app.services.case_road_document import attach_road_document
from app.services import frozen_evaluation_service as evaluation
from app.tasks import case_road_tasks


def main(root):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    case_road_tasks.SessionLocal = sessions
    case_road_tasks.settings.MAP_PACKAGE_ROOT = str(root)
    source = root / "source.osm.pbf"
    # Two disconnected roads: a trusted entrance on the other component must
    # never become reachable through a facility centroid or invented connector.
    segments = [[[125, 46], [125.01, 46]], [[125.02, 46], [125.03, 46]]]
    with osmium.SimpleWriter(str(source)) as writer:
        for identifier, point in enumerate(sum(segments, []), 1):
            writer.add_node(osmium.osm.mutable.Node(id=identifier, location=point, version=1))
        for identifier, nodes in ((10, [1, 2]), (20, [3, 4])):
            writer.add_way(osmium.osm.mutable.Way(id=identifier, nodes=nodes, version=1,
                tags={"highway": "residential", "motor_vehicle": "yes", "maxspeed": "30"}))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    at = datetime.now(timezone.utc)
    with sessions() as db:
        db.add(User(id=1, username="native-synthetic", display_name="合成验证", password_hash="not-a-login", role="admin"))
        db.add(OperationalArea(id=1, code="native-fixture", name="合成辖区"))
        db.add(RoadAccessGroup(id=1, name="合成通行组"))
        db.flush()
        db.add(MapSource(id=1, source_key="native-fixture", name="合成台账", source_type="internal_gis", operational_area_id=1))
        db.add(RoadAccessMembership(group_id=1, user_id=1, valid_from=at - timedelta(days=1)))
        db.add(PublicMapBundle(id=1, bundle_id="native-fixture", provider="synthetic", source_version="1",
            license_record="Synthetic fixture only", bounds=[124.9, 45.9, 125.1, 46.1], status="accepted",
            manifest={"assets": [{"role": "road_source", "sha256": digest}]}, package_hash=digest))
        db.flush()
        db.add(MapSnapshot(id="native-map", version="native-fixture-1", operational_area_id=1,
            public_bundle_id=1, manifest={}, feature_watermark="12", status="current"))
        db.flush()
        roads = [{"type": "Feature", "id": "road-1", "geometry": {"type": "MultiLineString", "coordinates": segments},
            "properties": {"kind": "road", "name": "合成生产路", "conditions": {
                "direction": "forward", "access": "permitted", "gate": "open"}}}]
        for i in range(1, 13):
            point = [125.001 + i * .0005, 46] if i != 12 else [125.025, 46]
            db.add(JurisdictionAsset(id=i, operational_area_id=1, name=f"合成设施{i}", asset_type="well"))
            db.add(MapSnapshotFeature(snapshot_id="native-map", asset_id=i, operational_area_id=1,
                name=f"合成设施{i}", asset_type="well", geometry_type="point", source="manual", status="active",
                verified=True, latitude=point[1], longitude=point[0], attributes={"oil_type": "原油"}))
            roads.append({"type": "Feature", "id": f"gate-{i}", "geometry": {"type": "Point", "coordinates": point},
                "properties": {"kind": "entrance", "name": f"合成入口{i}", "road_id": "road-1", "facility_asset_id": i,
                    "conditions": {"direction": "both", "access": "permitted", "gate": "open"}}})
        db.commit()
        db.info.update(principal_user_id=1, authorized_area_ids=(1,), area_access_levels={1: "manage"})
        batch, _ = ingest_roads(db, 1, {"type": "FeatureCollection", "coordinate_system": "EPSG:4326", "features": roads}, 1)
        for feature in roads:
            connection = None if feature["id"] == "road-1" else {"road_import_id": batch["id"],
                "road_source_sha256": batch["input_sha256"], "status": "connected",
                "facility_asset_id": feature["properties"]["facility_asset_id"]}
            review_feature(db, 1, batch["id"], feature["id"], {"input_sha256": batch["input_sha256"],
                "request_key": feature["id"], "decision": "verified", "note": "合成核验", "evidence_reference": "synthetic-only",
                "previous_review_id": None, "connection_evidence": connection}, 1)
        db.add(RoadAccessGrant(group_id=1, policy_revision=1, source_id=1, feature_id="road-1",
            decision="allow", evidence_reference="synthetic-only", created_by=1))
        db.commit()
        for way in (10, 20):
            record_alias_decision(db, AliasDecision(import_id=batch["id"], feature_id="road-1",
                public_source_sha256=digest, osm_way_id=way, decision="verified", request_key=f"alias-{way}",
                evidence_reference="synthetic-only"))
        db.commit()
        vehicle = VehicleAssumption(kind="auto", source="explicit_reference_assumption")
        built = run_road_build_job(db, source_pbf=source, work_root=root / "jobs", source_ids=[1], group_id=1,
            at=datetime.now(timezone.utc), vehicle=vehicle, public_bundle_id=1)
        publish_road_candidate(db, built["id"], work_root=root / "jobs", artifact_root=root / "road-graphs")
        db.commit()
        case = CaseService.create_case(db, case_number="SYNTHETIC-NATIVE-1", occurred_time=at,
            description="合成验证记录，井场发现原油盗取线索，具体来源待核。", location="合成地点", latitude=46.,
            longitude=125.0002, oil_type="原油", facility_type="井口", operational_area_id=1)
        original = CasePipelineService.source_hash(db, case)
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "case.analysis.requested"))
        assert CasePipelineService.process_event(db, event.id)["status"] == "completed"
        insight = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "case.insights.requested"))
        assert insight is not None
        CaseInsightService.process_event(db, insight.id)
        outcomes = []
        for _ in range(12):
            outcome = case_road_tasks.process_next_comparison.run()
            outcomes.append(outcome)
            if outcome.get("outcome") == "calculated":
                break
        else:
            raise AssertionError(outcomes)
        artifact = read_road_artifact(db, outcome["artifact"]["id"])
        content = artifact["content"]
        ranked = content["result"]
        assert [len(item["asset_ids"]) for item in ranked["batches"]] == [10, 2], ranked
        assert len(ranked["scoring_evidence"]) == 12 and len(ranked["candidates"]) == 3
        assert all(item["asset_id"] != 12 for item in ranked["candidates"])
        unreachable = next(item for item in ranked["scoring_evidence"] if item["asset_id"] == 12)
        assert unreachable["road_state"] != "calculated" and unreachable["road_distance_m"] is None, unreachable
        best = ranked["candidates"][0]
        assert best["road_distance_m"] > 0
        calculation = content["calculation"]
        route = route_facility_candidate(db, comparison_id=artifact["id"], comparison_sha256=artifact["content_sha256"],
            asset_id=best["asset_id"], analysis_at=datetime.fromisoformat(calculation["analysis_at"]),
            vehicle=vehicle, artifact_root=root / "road-graphs")
        assert route["route"]["distance_m"] > 0 and route["route"]["shape_polyline6"]
        saved_route = freeze_road_artifact(db, route)
        db.commit()
        document = attach_road_document(build_case_result_document(CaseResultService.read(db, content["result_id"])), artifact)
        assert any("道路前置来源候选" in block.text for block in document.blocks)
        dataset = evaluation.create_dataset(db, name="真实引擎合成固定对照", version="1", inputs=[],
            facility_artifact_ids=[artifact["id"]], created_by=1)
        previous = evaluation.run_evaluation(db, dataset.id, scorer_policy="captured")
        replay = evaluation.run_evaluation(db, dataset.id, scorer_policy="facility_captured")
        assert replay.metrics["positive_top3_hit_rate"] is None  # No business labels invented.
        assert CasePipelineService.source_hash(db, db.get(Case, case.id)) == original
        db.query(RoadAccessMembership).delete()
        db.commit()
        for identifier in (artifact["id"], saved_route["id"]):
            try:
                read_road_artifact(db, identifier)
            except PermissionError:
                pass
            else:
                raise AssertionError("revoked membership still reads road artifact")
        print(json.dumps({"passed": True, "synthetic_data": True, "real_native_engine": calculation["engine_version"],
            "graph_sha256": calculation["graph_sha256"], "governed_source_import": batch["id"],
            "batch_sizes": [10, 2], "candidate_ids": [item["asset_id"] for item in ranked["candidates"]],
            "unconnected_state": unreachable["road_state"], "reference_distance_m": route["route"]["distance_m"],
            "automatic_save_to_artifact": True, "report_bound": True, "revocation_checked": True,
            "evaluation_states": [previous.status, replay.status], "redis_broker_verified": False,
            "target_server_verified": False}, ensure_ascii=False))
    engine.dispose()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="v52-native-", dir="/tmp") as folder:
        main(Path(folder))
