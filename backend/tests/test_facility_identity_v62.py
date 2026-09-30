"""Synthetic identity, reversible mapping and bitemporal facility contracts."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.database import Base
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import (FacilityIdentityDecision, FacilitySourceIdentity,
    JurisdictionAssetVersion, MapFeatureClaim, MapSource, OperationalArea)
from app.models.user import User
from app.services.map_foundation_service import MapFoundationService
from app.services.facility_identity_service import FacilityIdentityService as Identity
from app.services.jurisdiction_service import JurisdictionService

UTC = timezone.utc
T1 = datetime(2026, 1, 10, tzinfo=UTC)
T2 = datetime(2026, 2, 10, tzinfo=UTC)
T3 = datetime(2026, 3, 10, tzinfo=UTC)


def clock(monkeypatch, value):
    monkeypatch.setattr("app.services.facility_identity_service._now", lambda: value)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["authorized_area_ids"] = None
        session.add_all([
            OperationalArea(id=1, code="synthetic-a", name="合成厂区甲"),
            OperationalArea(id=2, code="synthetic-b", name="合成厂区乙"),
            User(id=1, username="synthetic-map-admin", display_name="合成用户", password_hash="synthetic", role="admin"),
        ])
        session.commit()
        yield session
    engine.dispose()


def source(db, key="ledger-a", source_type="ledger", rank=100, area=1):
    row = MapSource(source_key=key, name=key, source_type=source_type,
                    trust_rank=rank, operational_area_id=area)
    db.add(row)
    db.flush()
    return row


def ingest(db, origin, *, revision="1", identifier="W1", name="合成井", longitude=125.1,
           valid_from="", valid_to=""):
    template = MapFoundationService.create_template(db, {
        "source_id": origin.id, "name": f"template-{revision}", "coordinate_system": "wgs84",
        "field_mapping": {"external_id": "id", "name": "name", "asset_type": "type",
                          "longitude": "lon", "latitude": "lat", "valid_from": "from", "valid_to": "to"},
    })
    content = ("id,name,type,lon,lat,from,to\n"
               f"{identifier},{name},well,{longitude},46.6,{valid_from},{valid_to}\n").encode()
    return MapFoundationService.ingest(db, source_id=origin.id, template_id=template.id,
        filename="synthetic.csv", content=content, source_revision=revision, created_by=1)[0]


def test_received_time_is_not_invented_as_business_effective_time(db):
    ingest(db, source(db))
    asset = db.query(JurisdictionAsset).one()
    assert asset.valid_from is None
    version = db.query(JurisdictionAssetVersion).one()
    assert version.temporal_status == "observed_only"
    assert version.known_at is not None


def test_same_source_id_survives_rename_without_name_based_merging(db):
    origin = source(db)
    ingest(db, origin)
    first = db.query(JurisdictionAsset).one()
    original_id, original_key = first.id, first.canonical_key
    ingest(db, origin, revision="2", name="新的井名")
    ingest(db, origin, revision="3", identifier="W2", name="新的井名")
    assert db.get(JurisdictionAsset, original_id).name == "新的井名"
    assert db.get(JurisdictionAsset, original_id).canonical_key == original_key
    assert db.query(JurisdictionAsset).count() == 2
    assert db.query(FacilitySourceIdentity).count() == 2


def test_source_correction_respects_both_valid_at_and_known_at(db, monkeypatch):
    origin = source(db)
    clock(monkeypatch, T1)
    ingest(db, origin, valid_from="2026-01-01T00:00:00Z", name="最初资料")
    asset = db.query(JurisdictionAsset).one()
    clock(monkeypatch, T2)
    ingest(db, origin, revision="2", valid_from="2026-01-01T00:00:00Z", name="迟到更正", longitude=125.2)
    before = Identity.get_asset_at(db, asset.id, valid_at=T1, known_at=T1 + timedelta(days=1))
    after = Identity.get_asset_at(db, asset.id, valid_at=T1, known_at=T2 + timedelta(days=1))
    assert before["state"] == after["state"] == "ready"
    assert before["snapshot"]["name"] == "最初资料"
    assert after["snapshot"]["name"] == "迟到更正"
    assert before["version_id"] != after["version_id"]
    assert Identity.get_asset_at(db, asset.id, valid_at=T1, known_at=T1 - timedelta(days=1))["state"] == "unknown"
    assert Identity.get_asset_at(db, asset.id, valid_at=T1 - timedelta(days=30), known_at=T3)["state"] == "unknown"


def test_late_end_date_correction_does_not_revive_superseded_open_interval(db, monkeypatch):
    origin = source(db)
    clock(monkeypatch, T1)
    ingest(db, origin, valid_from="2026-01-01T00:00:00Z")
    asset = db.query(JurisdictionAsset).one()
    clock(monkeypatch, T2)
    ingest(db, origin, revision="2", valid_from="2026-01-01T00:00:00Z", valid_to="2026-02-01T00:00:00Z")
    db.refresh(asset)
    assert not asset.verified and asset.verification_state == "temporal_not_current"
    assert Identity.get_asset_at(db, asset.id, valid_at=T3, known_at=T1)["state"] == "ready"
    assert Identity.get_asset_at(db, asset.id, valid_at=T3, known_at=T2)["state"] == "unknown"


def test_undeclared_old_import_cannot_become_historic_fact_by_manual_edit(db):
    asset = JurisdictionAsset(name="旧资料", asset_type="well", operational_area_id=1,
        valid_from=T1, latitude=46.6, longitude=125.1, source="manual")
    db.add(asset)
    db.commit()
    JurisdictionService.update_asset(db, asset.id, {"name": "只修正名称"})
    assert {row.temporal_status for row in db.query(JurisdictionAssetVersion)} == {"observed_only"}
    assert Identity.get_asset_at(db, asset.id, valid_at=T2)["state"] == "unknown"


def test_manual_declared_history_and_ended_interval_have_no_current_fallback(db):
    asset = JurisdictionService.create_asset(db, {"name": "明确历史资料", "asset_type": "well",
        "operational_area_id": 1, "source": "manual", "valid_from": T1, "valid_to": T2})
    assert Identity.get_asset_at(db, asset.id, valid_at=T1)["state"] == "ready"
    assert Identity.get_asset_at(db, asset.id, valid_at=T2)["state"] == "unknown"


def test_different_source_alias_bind_is_auditable_idempotent_and_revocable(db, monkeypatch):
    clock(monkeypatch, T1)
    primary, alternate = source(db), source(db, key="ledger-b")
    ingest(db, primary, identifier="MAIN", name="正式井名", valid_from="2026-01-01T00:00:00Z")
    ingest(db, alternate, identifier="ALIAS", name="台账别名", valid_from="2026-01-01T00:00:00Z")
    target = db.query(JurisdictionAsset).filter_by(external_id="MAIN").one()
    identity = db.query(FacilitySourceIdentity).filter_by(source_id=alternate.id).one()
    old_claim = db.query(MapFeatureClaim).filter_by(source_identity_id=identity.id).one()
    original_claim_asset = old_claim.asset_id
    clock(monkeypatch, T2)
    decision = Identity.bind(db, identity.id, target.id, actor_id=1, note="人工对照编号确认同井", request_key="bind-001")
    duplicate = Identity.bind(db, identity.id, target.id, actor_id=1, note="人工对照编号确认同井", request_key="bind-001")
    assert decision["id"] == duplicate["id"] and not duplicate["created"]
    assert len(Identity.list_identity(db, asset_id=target.id)["items"]) == 2
    before = Identity.get_asset_at(db, target.id, valid_at=T1, known_at=T1 + timedelta(days=1))
    now = Identity.get_asset_at(db, target.id, valid_at=T1, known_at=T2)
    assert len(before["supporting_version_ids"]) == 1
    assert len(now["supporting_version_ids"]) == 2
    clock(monkeypatch, T3)
    revoked = Identity.revoke(db, identity.id, actor_id=1, note="新资料证明不是同井", request_key="revoke-001", previous_decision_id=decision["id"])
    assert revoked["status"] == "revoked"
    assert old_claim.asset_id == original_claim_asset
    run = ingest(db, alternate, revision="2", identifier="ALIAS", name="后续资料")
    assert run.quarantined_rows == 1 and run.valid_rows == 0
    assert db.query(FacilityIdentityDecision).count() == 2
    current = Identity.get_asset_at(db, target.id, valid_at=T1, known_at=T3)
    assert len(current["supporting_version_ids"]) == 1
    # A new explicit decision, not another ingest, can restore the mapping.
    Identity.bind(db, identity.id, target.id, actor_id=1, note="重新核验", request_key="bind-002", previous_decision_id=revoked["id"])


@pytest.mark.parametrize("other_area,other_type,public", [(2, "well", False), (1, "station", False), (1, "well", True)])
def test_cross_area_type_and_public_reference_bindings_are_rejected(db, other_area, other_type, public):
    origin = source(db, source_type="public_map" if public else "ledger")
    ingest(db, origin)
    identity = db.query(FacilitySourceIdentity).one()
    target = JurisdictionAsset(name="绑定目标", asset_type=other_type, source="ledger", operational_area_id=other_area)
    db.add(target)
    db.flush()
    with pytest.raises(ValueError):
        Identity.bind(db, identity.id, target.id, actor_id=1, note="不能跨界", request_key="forbidden")
    assert db.query(FacilityIdentityDecision).count() == 0


def test_scope_is_checked_for_native_target_source_and_historical_snapshot(db):
    ingest(db, source(db), valid_from="2026-01-01T00:00:00Z")
    identity = db.query(FacilitySourceIdentity).one()
    db.info["authorized_area_ids"] = (2,)
    with pytest.raises((PermissionError, LookupError)):
        Identity.list_identity(db, source_id=identity.source_id)
    with pytest.raises((PermissionError, LookupError)):
        Identity.get_asset_at(db, identity.native_asset_id, valid_at=T1)
    db.info.pop("authorized_area_ids")
    with pytest.raises(PermissionError):
        Identity.list_identity(db, source_id=identity.source_id)


def test_conflicting_equal_priority_sources_are_not_chosen_as_fact(db, monkeypatch):
    clock(monkeypatch, T1)
    ingest(db, source(db), identifier="A", valid_from="2026-01-01T00:00:00Z")
    ingest(db, source(db, key="other"), identifier="B", longitude=125.2, valid_from="2026-01-01T00:00:00Z")
    target = db.query(JurisdictionAsset).filter_by(external_id="A").one()
    identity = db.query(FacilitySourceIdentity).filter_by(source_record_id="B").one()
    Identity.bind(db, identity.id, target.id, actor_id=1, note="身份相同但属性不同需核", request_key="conflict")
    result = Identity.get_asset_at(db, target.id, valid_at=T1)
    assert result["state"] == "conflict" and result["snapshot"] is None


def test_known_at_is_not_accepted_from_import_payload_and_queries_are_read_only(db):
    ingest(db, source(db), valid_from="2026-01-01T00:00:00Z")
    before = (db.query(JurisdictionAssetVersion).count(), db.query(FacilityIdentityDecision).count())
    asset = db.query(JurisdictionAsset).one()
    Identity.list_identity(db, asset_id=asset.id)
    Identity.get_asset_at(db, asset.id, valid_at=T1)
    assert not db.new and not db.dirty
    assert before == (db.query(JurisdictionAssetVersion).count(), db.query(FacilityIdentityDecision).count())


def test_bound_import_preserves_business_id_and_revoke_removes_current_verification(db):
    primary = source(db, rank=80, source_type="internal_gis")
    alternate = source(db, key="ledger-b", rank=100)
    ingest(db, primary, identifier="MAIN")
    ingest(db, alternate, identifier="ALIAS", name="另一来源名称")
    target = db.query(JurisdictionAsset).filter_by(external_id="MAIN").one()
    original_key = target.canonical_key
    identity = db.query(FacilitySourceIdentity).filter_by(source_id=alternate.id).one()
    bound = Identity.bind(db, identity.id, target.id, actor_id=1, note="人工核对同井", request_key="bind-current")
    run = ingest(db, alternate, revision="2", identifier="ALIAS", name="更新名称")
    assert run.valid_rows == 1
    db.refresh(target)
    assert target.external_id == "MAIN" and target.canonical_key == original_key
    assert target.verified and target.attributes["source_identity_id"] == identity.id
    Identity.revoke(db, identity.id, actor_id=1, note="身份关系撤销", request_key="revoke-current", previous_decision_id=bound["id"])
    assert not target.verified and target.verification_state == "identity_revoked"


@pytest.mark.parametrize("start,end", [("2020-01-01T00:00:00Z", "2021-01-01T00:00:00Z"),
                                        ("2099-01-01T00:00:00Z", "")])
def test_first_historic_or_future_row_is_not_current_verified_data(db, start, end):
    origin = source(db)
    ingest(db, origin, valid_from=start, valid_to=end)
    asset = db.query(JurisdictionAsset).one()
    assert not asset.verified and asset.verification_state == "temporal_not_current"
    # A later, explicitly current source observation can establish current use.
    ingest(db, origin, revision="2", valid_from="2026-01-01T00:00:00Z")
    db.refresh(asset)
    assert asset.verified and asset.verification_state == "source_verified"


def test_old_mapping_form_cannot_overwrite_new_decision_and_actor_is_live(db):
    ingest(db, source(db))
    identity = db.query(FacilitySourceIdentity).one()
    bound = Identity.bind(db, identity.id, identity.native_asset_id, actor_id=1, note="核对", request_key="fresh")
    with pytest.raises(ValueError, match="decision_changed"):
        Identity.revoke(db, identity.id, actor_id=1, note="旧表单", request_key="stale", previous_decision_id=None)
    actor = db.get(User, 1)
    actor.role = "viewer"
    db.commit()
    with pytest.raises(PermissionError, match="admin_required"):
        Identity.revoke(db, identity.id, actor_id=1, note="权限已变", request_key="revoked-actor", previous_decision_id=bound["id"])
