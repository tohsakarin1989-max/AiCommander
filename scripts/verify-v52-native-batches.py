"""Offline native batching check; synthetic pool, not facility-governance acceptance.

Run in the existing road image with /fixtures/catalog.sqlite and content-addressed
tiles mounted read-only at /graphs. All writable state is in-memory SQLite.
"""
import json
import os
from pathlib import Path
import secrets
import sys
from datetime import datetime, timedelta, timezone

os.environ.update(DATABASE_URL="sqlite://", ENVIRONMENT="test", SECRET_KEY=secrets.token_hex(32))
sys.path.insert(0, "/app")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.database import Base
from app.models.map_foundation import PublicMapBundle
from app.models.road_network import RoadNetworkVersion, RoadAccessGroup, RoadAccessMembership
from app.models.user import User
from app.services.facility_road_batches import compare_facility_pool
from app.services.road_access_policy import VehicleAssumption
from app.services.scorers.facility_roads_v52 import FacilityEvidence
from app.services.vehicle_router import RoadLocation


def main():
    source = create_engine("sqlite:///file:/fixtures/catalog.sqlite?mode=ro&uri=true")
    with Session(source) as db:
        graph = db.scalar(select(RoadNetworkVersion).where(RoadNetworkVersion.status == "ready"))
        public = db.get(PublicMapBundle, graph.public_bundle_id)
        graph_values = {column.name: getattr(graph, column.name) for column in graph.__table__.columns}
        public_values = {column.name: getattr(public, column.name) for column in public.__table__.columns}
    source.dispose()
    assert graph_values["graph_sha256"] == "dfb23e67f0de3de1628adf97f2e84d71ae026494dc78282979b069cc0a01e07b"
    assert graph_values["source_manifest"]["internal_area_ids"] == []
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    at = datetime.now(timezone.utc)
    with Session(engine) as db:
        db.add(PublicMapBundle(**public_values))
        db.add(User(id=1, username="native-fixture", display_name="合成验证账号", password_hash="not-a-login", role="admin"))
        db.add(RoadAccessGroup(id=graph_values["group_id"], name="合成公共路网组", policy_revision=graph_values["policy_revision"]))
        db.flush()
        db.add(RoadAccessMembership(group_id=graph_values["group_id"], user_id=1, valid_from=at - timedelta(hours=1)))
        db.add(RoadNetworkVersion(**graph_values))
        db.commit()
        db.info.update(principal_user_id=1, authorized_area_ids=())
        origin = RoadLocation(longitude=125.1852727, latitude=46.54446175)
        # Repeated public control points exercise batching only, not recall quality.
        targets = {i: RoadLocation(longitude=125.18509545, latitude=46.5444392) for i in range(1, 13)}
        result = compare_facility_pool(db, origin=origin,
            evidence=[FacilityEvidence(asset_id=i, evidence_ref=f"map_asset:{i}@snapshot:synthetic-map",
                straight_distance_m=15, road_state="not_calculated", entrance_verified=True, passage_allowed=True)
                for i in targets], entrances=targets, network_id=graph_values["id"], analysis_at=at,
            vehicle=VehicleAssumption(kind="auto", source="explicit_reference_assumption"), artifact_root=Path("/graphs"),
            source_versions={"case_profile_id": "synthetic-profile", "case_source_hash": "synthetic-source",
                             "map_snapshot_id": "synthetic-map", "recall_version": "native-batch-fixture"},
            recall_complete=True)
        assert [len(batch["asset_ids"]) for batch in result["batches"]] == [10, 2]
        assert result["coverage"]["compared"] == 12 and len(result["candidates"]) == 3
        assert all(item["road_distance_m"] > 100 for item in result["candidates"])
        print(json.dumps({"passed": True, "native_engine": result["versions"]["engine_version"],
            "graph_sha256": graph_values["graph_sha256"], "batch_sizes": [10, 2], "coverage": result["coverage"],
            "distance_m": result["candidates"][0]["road_distance_m"],
            "synthetic_pool": True, "facility_governance_acceptance": False}, ensure_ascii=False))
    engine.dispose()


if __name__ == "__main__":
    main()
