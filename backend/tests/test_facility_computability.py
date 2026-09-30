"""Isolated facility-input readiness, permission and no-side-effect regressions."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app.models.internal_roads import InternalRoadFeatureVersion, InternalRoadImport, InternalRoadReview
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import (
    JurisdictionAssetVersion, MapSnapshot, MapSnapshotFeature, MapSource,
    OperationalArea, PublicMapBundle, UserAreaScope,
)
from app.models.road_network import RoadAccessGrant, RoadAccessGroup, RoadAccessMembership, RoadNetworkVersion
from app.models.user import User
from app.services.facility_computability import facility_readiness, list_readiness
from app.services.facility_execution_context import freeze_facility_context
from app.services.vehicle_router import ENGINE_VERSION


AT = datetime(2026, 9, 1, tzinfo=timezone.utc)
BEFORE = AT - timedelta(days=1)


@pytest.fixture
def readiness_db(db_session):
    db = db_session
    db.add_all([OperationalArea(id=i, code=f"ready-{i}", name=f"区域{i}") for i in (1, 2)])
    db.add(User(id=1, username="ready-reader", display_name="合成用户", password_hash="test-only", role="analyst", is_active=True))
    db.flush()
    db.add(UserAreaScope(user_id=1, operational_area_id=1, access_level="read"))
    for identifier in (1, 2):
        db.add(MapSource(id=identifier, source_key=f"ready-source-{identifier}", name=f"来源{identifier}",
                         operational_area_id=identifier, source_type="internal_gis", status="active", created_at=BEFORE))
        db.add(JurisdictionAsset(id=identifier, operational_area_id=identifier, name="本井" if identifier == 1 else "受限井名",
            external_id=f"W-{identifier}", asset_type="well", verified=True, status="active",
            latitude=46, longitude=125, attributes={"source_id": identifier}, created_at=BEFORE))
    db.flush()
    db.add(JurisdictionAssetVersion(asset_id=1, version=1, change_type="manual_update", temporal_status="declared",
        valid_from=BEFORE, known_at=BEFORE, snapshot={"operational_area_id": 1, "asset_type": "well",
            "name": "本井", "latitude": 46, "longitude": 125, "attributes": {"source_id": 1}}))
    db.commit()
    db.info.update(principal_user_id=1, authorized_area_ids=(1,))
    return db


def checks(value):
    return {row["key"]: row for row in value["checks"]}


def add_entrance(db, *, verified=False, connected=True, conditions=None):
    conditions = {"direction": "both", "gate": "open", "access": "permitted", **(conditions or {})}
    road = {"id": "road-1", "geometry": {"type": "LineString", "coordinates": [[125, 46], [125.1, 46.1]]},
            "properties": {"kind": "road", "name": "生产道路", "conditions": conditions}}
    gate = {"id": "gate-1", "geometry": {"type": "Point", "coordinates": [125, 46]},
            "properties": {"kind": "entrance", "name": "井入口", "road_id": "road-1", "facility_asset_id": 1,
                           "conditions": conditions}}
    batch = InternalRoadImport(source_id=1, operational_area_id=1, input_sha256="a" * 64,
        schema_version="test", features=[road, gate], warnings=[], created_by=1, created_at=BEFORE)
    db.add(batch)
    db.flush()
    for feature in (road, gate):
        db.add(InternalRoadFeatureVersion(import_id=batch.id, source_id=1, operational_area_id=1,
            feature_id=feature["id"], name=feature["properties"]["name"], kind=feature["properties"]["kind"]))
    if verified:
        for feature in (road, gate):
            connection = {"status": "connected" if connected else "disconnected", "facility_asset_id": 1,
                "road_import_id": batch.id, "road_source_sha256": batch.input_sha256} if feature is gate else None
            db.add(InternalRoadReview(import_id=batch.id, operational_area_id=1, feature_id=feature["id"],
                sequence=1, request_key=feature["id"], decision="verified", note="合成核验", evidence_reference="合成来源",
                connection_evidence=connection, created_by=1, created_at=BEFORE))
    db.commit()
    return batch


def add_permission(db):
    db.add(RoadAccessGroup(id=1, name="合成通行组", policy_revision=1))
    db.flush()
    db.add(RoadAccessMembership(group_id=1, user_id=1, valid_from=BEFORE))
    db.add(RoadAccessGrant(group_id=1, policy_revision=1, source_id=1, feature_id="road-1",
                           decision="allow", evidence_reference="合成许可", created_by=1, created_at=BEFORE))
    db.commit()


def add_graph_and_snapshot(db):
    db.add(PublicMapBundle(id=1, bundle_id="ready-public", provider="synthetic", source_version="test",
        license_record="synthetic", bounds=[], manifest={}, package_hash="public-test"))
    db.flush()
    db.add(RoadNetworkVersion(id="ready-graph", group_id=1, policy_revision=1, public_bundle_id=1,
        input_sha256="a" * 64, conditions_sha256="b" * 64,
        source_manifest={"internal_area_ids": [1], "vehicle": {"kind": "auto", "source": "explicit_reference_assumption"}},
        engine_version=ENGINE_VERSION, builder_version="synthetic", status="ready", graph_sha256="c" * 64,
        artifact_key="c" * 64, valid_from=BEFORE, created_at=BEFORE))
    db.add(MapSnapshot(id="ready-map", version="ready-map-1", operational_area_id=1, public_bundle_id=1,
        status="current", manifest={}, feature_watermark="1", built_at=BEFORE, published_at=BEFORE))
    db.flush()
    db.add(MapSnapshotFeature(snapshot_id="ready-map", asset_id=1, operational_area_id=1, name="本井",
        asset_type="well", geometry_type="point", status="active", verified=True))
    db.commit()


def test_scope_required_and_other_area_names_and_counts_never_leak(readiness_db):
    db = readiness_db
    assert list_readiness(db, at=AT)["total"] == 1
    assert "受限井名" not in str(list_readiness(db, at=AT))
    with pytest.raises(PermissionError):
        facility_readiness(db, 2, at=AT)
    with pytest.raises(PermissionError):
        list_readiness(db, area_id=2, at=AT)
    db.info.pop("principal_user_id")
    with pytest.raises(PermissionError):
        list_readiness(db, at=AT)


def test_no_entrance_is_missing_not_inferred_from_map_point(readiness_db):
    value = facility_readiness(readiness_db, 1, at=AT)
    result = checks(value)
    assert result["geometry"]["state"] == "ready"
    assert result["entrance"]["state"] == "missing"
    assert result["network"]["state"] == "restricted"
    assert value["route_state"] == "not_checked"
    assert value["versions"]["vehicle"]["source"] == "explicit_reference_assumption"
    assert value["versions"]["vehicle"]["weight_t"] is None


@pytest.mark.parametrize("verified,connected,expected", [(False, True, "not_checked"), (True, False, "disconnected"), (True, True, "ready")])
def test_unverified_and_disconnected_entries_are_retained(readiness_db, verified, connected, expected):
    add_entrance(readiness_db, verified=verified, connected=connected)
    value = checks(facility_readiness(readiness_db, 1, at=AT))
    assert value["connection"]["state"] == expected
    assert len(value["entrance"]["details"]) == 1
    assert value["entrance"]["details"][0]["feature_id"] == "gate-1"


@pytest.mark.parametrize("conditions,expected", [({"valid_until": AT.isoformat()}, "expired"),
    ({"gate": "closed"}, "restricted"), ({"gate": "unknown"}, "missing"), ({"max_weight_t": 5.0}, "missing")])
def test_conditions_and_vehicle_unknowns_do_not_become_ready(readiness_db, conditions, expected):
    add_entrance(readiness_db, verified=True, conditions=conditions)
    add_permission(readiness_db)
    assert checks(facility_readiness(readiness_db, 1, at=AT))["passage"]["state"] == expected


def test_allowed_input_does_not_claim_path_or_router_health(readiness_db):
    add_entrance(readiness_db, verified=True)
    add_permission(readiness_db)
    add_graph_and_snapshot(readiness_db)
    value = facility_readiness(readiness_db, 1, at=AT)
    assert checks(value)["passage"]["state"] == "ready"
    assert checks(value)["network"]["state"] == "ready"
    assert checks(value)["graph_connection"]["state"] == "not_checked"
    assert value["state"] == "partial"
    assert value["route_state"] == "not_checked"
    assert "不等于" in value["boundary"] and "未检查引擎" in checks(value)["network"]["detail"]


def test_current_permission_revocation_invalidates_readiness(readiness_db):
    db = readiness_db
    add_entrance(db, verified=True)
    add_permission(db)
    assert checks(facility_readiness(db, 1, at=AT))["passage"]["state"] == "ready"
    db.query(RoadAccessMembership).delete()
    db.commit()
    assert checks(facility_readiness(db, 1, at=AT))["passage"]["state"] == "restricted"
    db.query(UserAreaScope).delete()
    db.commit()
    with pytest.raises(PermissionError):
        facility_readiness(db, 1, at=AT)
    assert list_readiness(db, at=AT)["total"] == 0


def test_historical_unknown_does_not_borrow_future_entries(readiness_db):
    add_entrance(readiness_db, verified=True)
    value = facility_readiness(readiness_db, 1, at=BEFORE - timedelta(days=1))
    assert checks(value)["entrance"]["state"] == "missing"
    assert checks(value)["history"]["state"] == "not_checked"
    assert checks(value)["geometry"]["state"] == "not_checked"
    assert value["state"] != "ready"


def test_known_at_excludes_later_source_and_snapshot_records(readiness_db):
    add_entrance(readiness_db, verified=True)
    add_permission(readiness_db)
    add_graph_and_snapshot(readiness_db)
    value = facility_readiness(readiness_db, 1, at=AT, known_at=BEFORE - timedelta(days=1))
    assert checks(value)["entrance"]["state"] == "missing"
    assert checks(value)["network"]["state"] == "missing"
    assert checks(value)["snapshot"]["state"] == "missing"
    assert checks(value)["history"]["state"] == "not_checked"


def test_latest_unverified_update_does_not_revive_old_connection(readiness_db):
    old = add_entrance(readiness_db, verified=True)
    add_permission(readiness_db)
    new = InternalRoadImport(source_id=1, operational_area_id=1, input_sha256="b" * 64,
        schema_version="test", features=old.features, warnings=[], created_by=1,
        created_at=AT - timedelta(hours=1))
    readiness_db.add(new)
    readiness_db.flush()
    readiness_db.add(InternalRoadFeatureVersion(import_id=new.id, source_id=1, operational_area_id=1,
        feature_id="gate-1", name="入口修改后待核", kind="entrance"))
    readiness_db.commit()
    result = checks(facility_readiness(readiness_db, 1, at=AT))
    assert result["entrance"]["state"] == "unverified"
    assert result["passage"]["state"] == "not_checked"
    assert result["entrance"]["details"][0]["import_id"] == new.id


@pytest.mark.parametrize("change", ["disabled", "moved_source", "area_inactive"])
def test_live_access_is_not_replaced_by_cached_objects(readiness_db, change):
    db = readiness_db
    facility_readiness(db, 1, at=AT)
    if change == "disabled":
        db.query(User).filter_by(id=1).update({"is_active": False})
    elif change == "moved_source":
        db.query(MapSource).filter_by(id=1).update({"operational_area_id": 2})
    else:
        db.query(OperationalArea).filter_by(id=1).update({"status": "inactive"})
    db.commit()
    with pytest.raises(PermissionError):
        facility_readiness(db, 1, at=AT)


def test_stale_context_and_other_user_context_are_rejected(readiness_db):
    db = readiness_db
    context = freeze_facility_context(db, area_id=1, valid_at=AT)
    assert facility_readiness(db, 1, context=context)["context"]["policy_version"] == context.policy_version
    db.query(UserAreaScope).delete()
    db.commit()
    with pytest.raises(PermissionError):
        facility_readiness(db, 1, context=context)


def test_readiness_does_not_flush_pending_writes(readiness_db):
    db = readiness_db
    writes = []

    def capture(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        db.autoflush = True
        db.add(JurisdictionAsset(name="不应保存", asset_type="well", operational_area_id=1))
        list_readiness(db, at=AT)
        facility_readiness(db, 1, at=AT)
        assert writes == []
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)


@pytest.mark.parametrize("kwargs", [{"page": 0}, {"page_size": 101}, {"page_size": True}])
def test_invalid_pagination_is_not_silently_adjusted(readiness_db, kwargs):
    with pytest.raises(ValueError):
        list_readiness(readiness_db, **kwargs)
