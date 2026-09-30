"""A frozen map cannot resurrect withdrawn current facility input."""
from datetime import timedelta

import pytest

from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import FacilityIdentityDecision, FacilitySourceIdentity, MapSnapshotFeature
from app.services.facility_candidate_pool import require_current_pool_source, validate_pool_access
from test_case_facility_comparison import prepared, ready, db_session, result_data, freeze  # noqa: F401
from test_road_access_policy import AT


@pytest.mark.parametrize("changes", [
    {"verification_state": "identity_revoked", "verified": False},
    {"verification_state": "temporal_not_current", "verified": False},
    {"valid_from": AT + timedelta(days=1)},
    {"valid_to": AT},
    {"status": "inactive"},
    {"verified": False},
])
def test_old_verified_snapshot_cannot_override_current_withdrawal(prepared, changes):
    db, source, _ = prepared
    db.query(JurisdictionAsset).filter_by(id=13).update(changes)
    db.commit()
    pool = freeze(db, source)
    asset = next(row for row in pool["assets"] if row["asset_id"] == 13)
    assert asset["source_verified"] is False
    assert asset["oil_match"] == "unknown"
    assert asset["production_comparison"]["state"] == "unknown"
    assert asset["current_source_state"] != "ready"
    assert asset["source_gap"]
    assert "13" not in pool["entrances"]


def _identity(db):
    identity = FacilitySourceIdentity(source_id=10, operational_area_id=1, native_asset_id=13,
        identity_key="id:alias13", source_record_id="alias13", asset_type="well", identity_kind="exact_id")
    db.add(identity)
    db.flush()
    asset = db.get(JurisdictionAsset, 13)
    asset.attributes = {"source_id": 10, "source_identity_id": identity.id, "identity_decision_id": None}
    snapshot = db.query(MapSnapshotFeature).filter_by(asset_id=13).one()
    snapshot.attributes = {**snapshot.attributes, **asset.attributes}
    db.commit()
    return identity


@pytest.mark.parametrize("action,target", [("revoke", 13), ("bind", 12)])
def test_changed_mapping_is_checked_even_if_flat_verified_flag_was_not_updated(prepared, action, target):
    db, source, _ = prepared
    identity = _identity(db)
    db.add(FacilityIdentityDecision(identity_id=identity.id, operational_area_id=1,
        target_asset_id=target, sequence=1, action=action, actor_id=1, note="合成身份更正", request_key="change-identity"))
    db.commit()
    pool = freeze(db, source)
    asset = next(row for row in pool["assets"] if row["asset_id"] == 13)
    assert not asset["source_verified"] and "13" not in pool["entrances"]
    assert asset["current_source_state"] != "ready"


def test_revocation_during_calculation_stops_new_publication_but_preserves_history(prepared):
    db, source, _ = prepared
    pool = freeze(db, source)
    db.query(JurisdictionAsset).filter_by(id=13).update({"verification_state": "identity_revoked", "verified": False})
    db.commit()
    validate_pool_access(db, pool)
    with pytest.raises(ValueError, match="facility_pool_source_changed"):
        require_current_pool_source(db, pool)


def test_effective_current_source_still_uses_saved_map_and_history(prepared):
    db, source, _ = prepared
    db.query(JurisdictionAsset).filter_by(id=13).update({"valid_from": AT - timedelta(days=1), "valid_to": AT + timedelta(days=1)})
    db.commit()
    pool = freeze(db, source)
    asset = next(row for row in pool["assets"] if row["asset_id"] == 13)
    assert asset["source_verified"] and asset["current_source_state"] == "ready"
    assert asset["oil_match"] == "matched" and "13" in pool["entrances"]
    require_current_pool_source(db, pool)
