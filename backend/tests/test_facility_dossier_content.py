from datetime import datetime

import pytest
from sqlalchemy import event

from app.models.case import Case
from app.models.case_insight import CaseAnalysisRun, CaseHypothesis, HypothesisFeedback
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.case_result import CaseResultSnapshot
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import JurisdictionAssetVersion, MapSnapshot, MapSnapshotFeature, MapSource, PublicMapBundle
from app.services.facility_dossier_content import build_dossier_content
from test_facility_condition_comparison import facility_db  # noqa: F401


def add_candidate(db, *, asset_id=1, extra_refs=()):
    db.add(PublicMapBundle(id=20, bundle_id="dossier-map", provider="synthetic", source_version="1", license_record="test", bounds=[], manifest={}, package_hash="dossier"))
    db.flush()
    db.add(MapSnapshot(id="dossier-map", version="dossier-map-1", operational_area_id=1,
        public_bundle_id=20, manifest={}, feature_watermark="1", status="current"))
    db.flush()
    db.add(MapSnapshotFeature(snapshot_id="dossier-map", asset_id=asset_id, operational_area_id=1,
        name="同名井", asset_type="well", geometry_type="point", status="active", verified=True))
    db.add(CaseAnalysisRun(id="dossier-run", case_id=2, case_profile_id="facility-profile-2",
        map_snapshot_id="dossier-map", algorithm_version="test", status="completed", information_gaps=[]))
    db.flush()
    db.add(CaseHypothesis(id="dossier-candidate", analysis_run_id="dossier-run", case_id=2,
        hypothesis_type="possible_source", rank=1, title="同名井候选", claim="仅为候选", score=1, confidence=.1,
        evidence_refs=[f"map_asset:{asset_id}@snapshot:dossier-map", "case_profile:facility-profile-2", *extra_refs],
        supporting_evidence=["已保存条件"], counter_evidence=["不证明实际来源"], information_gaps=[], score_components={}, status="candidate", boundary="仅供研判"))
    db.flush()
    db.add(HypothesisFeedback(hypothesis_id="dossier-candidate", decision="useful"))
    db.commit()


def test_explicit_nearby_candidate_and_event_classes_remain_separate(facility_db):
    add_candidate(facility_db)
    value = build_dossier_content(facility_db, 1)
    sections = value["sections"]
    assert [row["case_id"] for row in sections["record_links"]["items"]] == [1]
    assert sections["record_links"]["items"][0]["review_status"] == "confirmed"
    assert sections["record_links"]["items"][0]["relation_kind"] == "recorded_event_link"
    assert {row["case_id"] for row in sections["nearby_cases"]["items"]} == {1, 2}
    assert [row["case_id"] for row in sections["candidate_links"]["items"]] == [2]
    assert sections["candidate_links"]["items"][0]["status"] == "candidate"
    assert [row["event_id"] for row in sections["events"]["items"]] == [1]
    assert "risk_score" not in str(value)


def test_identical_names_with_distinct_ids_do_not_share_candidates(facility_db):
    add_candidate(facility_db, asset_id=2)
    assert build_dossier_content(facility_db, 1)["sections"]["candidate_links"]["total"] == 0
    assert build_dossier_content(facility_db, 2)["sections"]["candidate_links"]["total"] == 1


def test_candidate_secondary_source_revocation_hides_items_and_counts(facility_db):
    db = facility_db
    add_candidate(db, extra_refs=("case:3",))
    db.info["authorized_area_ids"] = (1, 2)
    assert build_dossier_content(db, 1)["sections"]["candidate_links"]["total"] == 1
    db.info["authorized_area_ids"] = (1,)
    value = build_dossier_content(db, 1)["sections"]["candidate_links"]
    assert value["state"] == "restricted" and "items" not in value and "total" not in value
    assert "同名井候选" not in str(value)


def test_moved_event_case_hides_recorded_relation_content(facility_db):
    db = facility_db
    db.execute(Case.__table__.update().where(Case.id == 1).values(operational_area_id=2))
    db.commit()
    sections = build_dossier_content(db, 1)["sections"]
    for key in ("record_links", "events"):
        assert sections[key]["state"] == "restricted"
        assert "items" not in sections[key] and "total" not in sections[key]


def test_missing_technical_data_and_expired_production_remain_unknown(facility_db):
    db = facility_db
    asset = db.get(JurisdictionAsset, 1)
    asset.attributes = {"water_cut_min": 20, "water_cut_max": 40, "water_cut_unit": "percent",
        "production_valid_from": "2019-01-01T00:00:00Z", "production_valid_to": "2019-12-31T00:00:00Z"}
    db.commit()
    sections = build_dossier_content(db, 1)["sections"]
    assert sections["production"]["state"] == "stale"
    assert sections["tech_defense"]["state"] == "missing"
    assert "不等于没有技防" in str(sections["tech_defense"]["gaps"])
    assert sections["roads"]["state"] == "missing"
    assert all("含水率" not in str(row["support"]) for row in sections["history_conditions"]["items"])


def test_production_source_hidden_is_not_exposed_by_history_or_versions(facility_db):
    db = facility_db
    db.add(MapSource(id=30, source_key="secret-source", operational_area_id=2, name="隐藏来源", source_type="internal_gis"))
    db.get(JurisdictionAsset, 1).attributes = {"source_id": 30, "oil_type": "隐藏油品", "source_revision": "隐藏版本"}
    db.commit()
    value = build_dossier_content(db, 1)
    assert value["sections"]["production"]["state"] == "restricted"
    assert value["sections"]["history_conditions"]["state"] == "restricted"
    assert "隐藏版本" not in str(value) and "隐藏油品" not in str(value)


def test_linked_case_outside_event_window_is_explicitly_marked(facility_db):
    value = build_dossier_content(facility_db, 1, start_date="2026-09-12", end_date="2026-09-13")
    link = value["sections"]["record_links"]["items"][0]
    assert not link["case_in_window"] and "不纳入" in str(link["gaps"])
    assert {row["case_id"] for row in value["sections"]["nearby_cases"]["items"]} == {2}


def test_dossier_does_not_write_or_flush_and_rechecks_cached_identity(facility_db):
    db = facility_db
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)
    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        db.autoflush = True
        db.add(JurisdictionAsset(name="未保存资产", asset_type="well", operational_area_id=1))
        build_dossier_content(db, 1)
        assert not writes
        db.info["authorized_area_ids"] = (2,)
        with pytest.raises(PermissionError):
            build_dossier_content(db, 1)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)


def test_history_names_are_bound_to_stable_id_and_old_scope_is_rechecked(facility_db):
    db = facility_db
    db.add_all([
        JurisdictionAssetVersion(asset_id=1, version=1, change_type="manual_update",
            snapshot={"name": "本井旧名", "operational_area_id": 1, "attributes": {}}),
        JurisdictionAssetVersion(asset_id=2, version=1, change_type="manual_update",
            snapshot={"name": "另一井旧名", "operational_area_id": 1, "attributes": {}}),
    ])
    db.commit()
    content = build_dossier_content(db, 1)
    assert "本井旧名" in str(content["sections"]["production"])
    assert "另一井旧名" not in str(content)
    old = db.query(JurisdictionAssetVersion).filter_by(asset_id=1).one()
    old.snapshot = {**old.snapshot, "operational_area_id": 2}
    db.commit()
    production = build_dossier_content(db, 1)["sections"]["production"]
    assert production["state"] == "restricted"
    assert "items" not in production and "total" not in production


@pytest.mark.parametrize("malformed", [None, 17, "invalid", {"unexpected": "shape"}])
def test_malformed_saved_candidate_lists_do_not_break_dossier(facility_db, malformed):
    db = facility_db
    db.add(CaseResultSnapshot(id="malformed-result", case_id=1, case_profile_id="facility-profile-1",
        content_sha256="broken", content={"candidates": malformed}))
    db.commit()
    section = build_dossier_content(db, 1)["sections"]["results"]
    assert section["state"] == "unavailable" and section["items"] == []


def test_result_reader_value_error_is_isolated(facility_db, monkeypatch):
    db = facility_db
    db.add(CaseResultSnapshot(id="damaged-result", case_id=1, case_profile_id="facility-profile-1",
        content_sha256="broken", content={"candidates": []}))
    db.commit()
    def fail(*args, **kwargs):
        raise ValueError("damaged_reference")
    monkeypatch.setattr("app.services.facility_dossier_content.CaseResultService.read", fail)
    sections = build_dossier_content(db, 1)["sections"]
    assert sections["results"]["state"] == "unavailable"
    assert sections["record_links"]["total"] == 1
