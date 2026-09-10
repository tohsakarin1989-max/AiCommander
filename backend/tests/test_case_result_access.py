from datetime import datetime

import pytest

from app.models.case import Case
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import OperationalArea, PublicMapBundle, MapSnapshot, MapSnapshotFeature
from app.services.case_result_access import CaseResultAccessError, require_result_access
from app.services.case_result_snapshot import assemble_case_result
from test_case_result_snapshot import inputs


@pytest.fixture
def result_data(db_session):
    db = db_session
    db.add_all([OperationalArea(id=i, code=f"RESULT-{i}", name=f"合成辖区{i}") for i in (1, 2)])
    db.flush()
    db.add_all([Case(id=i, case_number=f"RESULT-{i}", operational_area_id=i,
                     occurred_time=datetime(2026, 9, 1), description="合成记录") for i in (1, 2)])
    db.add(PublicMapBundle(id=1, bundle_id="synthetic", provider="synthetic", source_version="1",
                           license_record="test", bounds=[], manifest={}, package_hash="test"))
    db.flush()
    db.add(MapSnapshot(id="map-1", version="synthetic-1", operational_area_id=1,
                       public_bundle_id=1, manifest={}, feature_watermark="1", status="superseded"))
    db.add(JurisdictionAsset(id=1, operational_area_id=1, name="合成设施", asset_type="well"))
    profile, run, candidate = inputs()
    profile.quality_score = 1
    profile.analysis_readiness = "ready"
    db.add(profile)
    db.flush()
    db.add(MapSnapshotFeature(snapshot_id="map-1", asset_id=1, operational_area_id=1,
                              name="合成设施", asset_type="well", geometry_type="point",
                              status="active", verified=True))
    db.add(run)
    db.flush()
    candidate.confidence = 0.1
    candidate.evidence_refs = ["case_profile:profile-1", "map_asset:1@snapshot:map-1"]
    db.add(candidate)
    db.commit()
    return profile, run, candidate


def test_explicit_scope_allows_historical_snapshot_but_unbound_session_denied(db_session, result_data):
    result = assemble_case_result(*result_data[:2], [result_data[2]])
    with pytest.raises(CaseResultAccessError):
        require_result_access(db_session, result)
    for scope in [(1,), None]:
        db_session.info["authorized_area_ids"] = scope
        require_result_access(db_session, result)


def test_cached_case_and_profile_do_not_bypass_scope_shrink(db_session, result_data):
    result = assemble_case_result(*result_data[:2], [result_data[2]])
    cached_case = db_session.get(Case, 1)
    cached_profile = db_session.get(CaseAnalysisProfile, "profile-1")
    db_session.info["authorized_area_ids"] = (1, 2)
    require_result_access(db_session, result)
    db_session.info["authorized_area_ids"] = (2,)
    assert cached_case.id == 1 and cached_profile.case_id == 1
    with pytest.raises(CaseResultAccessError):
        require_result_access(db_session, result)


@pytest.mark.parametrize("reference", ["case:2", "case_profile:missing", "case:999", "https://example.org",
                                      "map_asset:1@snapshot:other", "map_asset:999@snapshot:map-1"])
def test_inaccessible_or_unknown_evidence_denies_entire_result(db_session, result_data, reference):
    profile, run, candidate = result_data
    candidate.evidence_refs = [reference]
    result = assemble_case_result(profile, run, [candidate])
    db_session.info["authorized_area_ids"] = (1,)
    with pytest.raises(CaseResultAccessError, match="^case_result_unavailable$"):
        require_result_access(db_session, result)


def test_related_case_is_checked_again_after_scope_revocation(db_session, result_data):
    profile, run, candidate = result_data
    candidate.evidence_refs = ["case:2"]
    result = assemble_case_result(profile, run, [candidate])
    db_session.info["authorized_area_ids"] = (1, 2)
    require_result_access(db_session, result)
    db_session.info["authorized_area_ids"] = (1,)
    with pytest.raises(CaseResultAccessError):
        require_result_access(db_session, result)


@pytest.mark.parametrize("action", ["move", "delete"])
def test_live_asset_revocation_cannot_be_bypassed_by_frozen_map(db_session, result_data, action):
    result = assemble_case_result(*result_data[:2], [result_data[2]])
    db_session.info["authorized_area_ids"] = (1,)
    require_result_access(db_session, result)
    table = JurisdictionAsset.__table__
    statement = table.delete() if action == "delete" else table.update().values(operational_area_id=2)
    db_session.execute(statement.where(table.c.id == 1))
    db_session.commit()
    with pytest.raises(CaseResultAccessError):
        require_result_access(db_session, result)


def test_profile_only_result_is_available_without_map_or_run(db_session, result_data):
    db_session.info["authorized_area_ids"] = (1,)
    result = assemble_case_result(result_data[0], None, [])
    require_result_access(db_session, result)
    result["content"]["case_id"] = 2
    with pytest.raises(CaseResultAccessError):
        require_result_access(db_session, result)


def test_valid_hash_does_not_allow_profile_version_mixing(db_session, result_data):
    profile, run, candidate = result_data
    profile.profile_version = 9
    result = assemble_case_result(profile, run, [candidate])
    db_session.info["authorized_area_ids"] = (1,)
    with pytest.raises(CaseResultAccessError):
        require_result_access(db_session, result)


@pytest.mark.parametrize("model", [Case, MapSnapshot])
def test_current_database_membership_is_used_even_with_cached_objects(db_session, result_data, model):
    result = assemble_case_result(*result_data[:2], [result_data[2]])
    db_session.info["authorized_area_ids"] = (1,)
    require_result_access(db_session, result)
    db_session.execute(model.__table__.update().values(operational_area_id=2))
    db_session.commit()
    with pytest.raises(CaseResultAccessError):
        require_result_access(db_session, result)


def test_related_profile_uses_its_own_current_case_scope(db_session, result_data):
    profile, run, candidate = result_data
    db_session.add(CaseAnalysisProfile(
        id="profile-2", case_id=2, profile_version=1, source_hash="source-2",
        schema_version="4.1.0", dictionary_version="rules-1", payload={},
        quality_score=1, analysis_readiness="ready",
    ))
    db_session.commit()
    candidate.evidence_refs = ["case_profile:profile-2"]
    result = assemble_case_result(profile, run, [candidate])
    db_session.info["authorized_area_ids"] = (1, 2)
    require_result_access(db_session, result)
    db_session.info["authorized_area_ids"] = (1,)
    with pytest.raises(CaseResultAccessError):
        require_result_access(db_session, result)
