"""v5.4 full-history, window, source freshness and read-only contracts."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from app.models.case import Case, CaseEvidence, CasePerson, CaseVehicle, OilRecoveryRecord
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.event import Event
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSource, OperationalArea
from app.services.case_pipeline_service import CasePipelineService
from app.services.facility_condition_comparison import build_region_content, current_source_hashes


def add_profile(db, case, *, assertions=None):
    payload = CasePipelineService.build_profile_payload(db, case)
    digest = payload["source_hash"]
    if assertions is not None:
        payload["semantics"]["assertions"] = assertions
    profile = CaseAnalysisProfile(id=f"facility-profile-{case.id}", case_id=case.id,
        profile_version=1, source_hash=digest, schema_version="4.1.0", dictionary_version="test",
        quality_score=1, analysis_readiness="ready", is_current=True,
        payload=payload)
    db.add(profile)
    return profile


@pytest.fixture
def facility_db(db_session):
    db = db_session
    db.add_all([OperationalArea(id=i, code=f"facility-{i}", name=f"区域{i}", status="active") for i in (1, 2)])
    db.flush()
    db.add_all([JurisdictionAsset(id=i, operational_area_id=1 if i < 3 else 2,
        name="同名井", external_id=f"W-{i}", asset_type="well", status="active",
        latitude=46, longitude=125 + (i - 1) * .1, verified=True, attributes={"oil_type": "原油"}) for i in (1, 2, 3)])
    cases = [Case(id=i, case_number=f"FAC-{i}", operational_area_id=2 if i == 3 else 1,
        occurred_time=datetime(2020 if i == 1 else 2026, 9, 12, 10), description="已记录条件",
        latitude=None if i == 4 else 46, longitude=None if i == 4 else 125,
        facility_type="井口", oil_type="原油", water_cut=30, modus_operandi="打孔盗油") for i in (1, 2, 3, 4)]
    db.add_all(cases)
    db.commit()
    for case in cases:
        add_profile(db, case)
    db.add_all([
        Event(id=1, event_number="EV-1", operational_area_id=1, event_type="oil_trace",
              occurred_time=datetime(2026, 9, 12, 11), related_asset_id=1, related_case_id=1,
              review_status="confirmed", title="明确记录关联"),
        Event(id=2, event_number="EV-2", operational_area_id=1, event_type="oil_trace",
              occurred_time=datetime(2026, 9, 12, 11), latitude=46, longitude=125, title="仅邻近的独立事件"),
    ])
    db.commit()
    db.info.update(authorized_area_ids=(1,), principal_user_id=1)
    return db


def test_region_pages_facilities_but_compares_all_authorized_history(facility_db):
    result = build_region_content(facility_db, page_size=1)
    assert result["facilities"]["total"] == 2
    assert len(result["facilities"]["items"]) == 1
    comparison = result["facilities"]["items"][0]["condition_comparison"]
    assert {row["case_id"] for row in comparison["reference_cases"]} == {1, 2, 4}
    assert result["coverage"]["profiles_scanned"] == 3
    assert result["cases"]["total"] == 3 and result["cases"]["missing_coordinates"] == 1
    assert result["statistics"]["page_facilities_with_reference"] == 1
    assert result["events"]["linked_case_count"] == 1 and result["events"]["independent_count"] == 1
    assert result["statistics"]["case_and_independent_event_count"] == 4
    assert build_region_content(facility_db, page=2, page_size=1)["facilities"]["items"][0]["id"] == 2


def test_half_open_datetime_window_is_shared_by_statistics_and_map(facility_db):
    result = build_region_content(facility_db, start_date="2026-09-12T18:00:00+08:00", end_date="2026-09-12T11:00:00")
    assert result["cases"]["total"] == 2
    assert result["events"]["total"] == 0
    assert result["statistics"]["monthly"] == [{"month": "2026-09", "case_count": 2, "event_count": 0}]
    assert result["window"]["start_date"] == "2026-09-12T10:00:00+00:00"
    with pytest.raises(ValueError):
        build_region_content(facility_db, start_date="2026-09-13", end_date="2026-09-12")


def test_changed_raw_case_excludes_stale_profile_without_reanalysis(facility_db):
    db = facility_db
    db.execute(Case.__table__.update().where(Case.id == 1).values(description="新的原始记录"))
    db.commit()
    result = build_region_content(db)
    assert result["coverage"]["profiles_stale"] == 1
    assert result["coverage"]["profiles_current"] == 2
    assert 1 not in {row["case_id"] for row in result["facilities"]["items"][0]["condition_comparison"]["reference_cases"]}


def test_source_access_revocation_does_not_reveal_condition_summary(facility_db):
    db = facility_db
    db.add(MapSource(id=8, source_key="hidden-facility", operational_area_id=2, name="不可泄露来源", source_type="internal_gis"))
    db.get(JurisdictionAsset, 1).attributes = {"source_id": 8, "oil_type": "不应显示的油品"}
    db.commit()
    comparison = build_region_content(db)["facilities"]["items"][0]["condition_comparison"]
    assert comparison["state"] == "restricted"
    assert "reference_cases" not in comparison and "reference_total" not in comparison
    assert "不应显示" not in str(comparison)


def test_naive_and_aware_hashes_use_pipeline_contract_with_all_detail_tables(facility_db):
    db = facility_db
    db.add_all([
        CaseVehicle(case_id=1, vehicle_type="货车", plate_number="合成车牌", height_m=3.1),
        CasePerson(case_id=1, name="合成人员", role="driver"),
        CaseEvidence(case_id=1, evidence_type="photo", title="合成照片", meta={"test": True}),
        OilRecoveryRecord(case_id=1, oil_nature="原油", volume_tons=1.2, water_cut=22),
    ])
    db.commit()
    cases = db.query(Case).order_by(Case.id).all()
    assert current_source_hashes(db, cases) == {case.id: CasePipelineService.source_hash(db, case) for case in cases}


def test_nonaffirmative_profile_conditions_never_become_similar(facility_db):
    db = facility_db
    profile = db.get(CaseAnalysisProfile, "facility-profile-1")
    case = db.get(Case, 1)
    case.description = "未发现井口；可能存在原油"
    db.flush()
    profile.payload = CasePipelineService.build_profile_payload(db, case)
    profile.source_hash = profile.payload["source_hash"]
    db.commit()
    rows = build_region_content(db)["facilities"]["items"][0]["condition_comparison"]["reference_cases"]
    assert 1 not in {row["case_id"] for row in rows}


def test_real_profile_handling_and_conflicts_are_reference_only(facility_db):
    db = facility_db
    row = build_region_content(db)["facilities"]["items"][0]["condition_comparison"]["reference_cases"][0]
    assert "历史手法条件参考：打孔盗油" in row["historical_conditions"]
    case = db.get(Case, 1)
    case.description = "打孔盗油；未发现打孔盗油"
    db.flush()
    profile = db.get(CaseAnalysisProfile, "facility-profile-1")
    profile.payload = CasePipelineService.build_profile_payload(db, case)
    profile.source_hash = profile.payload["source_hash"]
    db.commit()
    result = build_region_content(db)["facilities"]["items"][0]["condition_comparison"]
    row = next(item for item in result["reference_cases"] if item["case_id"] == 1)
    assert not row["historical_conditions"]
    assert any("肯定与否定并存" in gap for gap in row["gaps"])


def test_damaged_quote_is_rejected_even_with_valid_hash_and_verified_flag(facility_db):
    from copy import deepcopy
    db = facility_db
    profile = db.get(CaseAnalysisProfile, "facility-profile-1")
    payload = deepcopy(profile.payload)
    payload["semantics"]["assertions"][0]["reference"]["quote"] = "损坏的原文引用"
    payload["semantics"]["assertions"][0]["reference_verified"] = True
    profile.payload = payload
    db.commit()
    result = build_region_content(db)
    assert result["coverage"]["profiles_invalid"] == 1
    assert 1 not in {row["case_id"] for row in result["facilities"]["items"][0]["condition_comparison"]["reference_cases"]}


def test_bound_scope_required_and_cached_assets_do_not_bypass_revocation(facility_db):
    db = facility_db
    cached = db.get(JurisdictionAsset, 1)
    db.info["authorized_area_ids"] = (2,)
    assert [row["id"] for row in build_region_content(db)["facilities"]["items"]] == [3]
    assert cached.id == 1
    db.info.pop("authorized_area_ids")
    with pytest.raises(PermissionError):
        build_region_content(db)


def test_map_limit_keeps_full_counts_and_explicit_coverage(facility_db, monkeypatch):
    monkeypatch.setattr("app.services.facility_condition_comparison.MAP_LIMIT", 1)
    result = build_region_content(facility_db)
    assert len(result["cases"]["items"]) == 1 and result["cases"]["total"] == 3
    assert len(result["events"]["items"]) == 1 and result["events"]["total"] == 2
    assert result["coverage"]["cases_truncated"] and result["coverage"]["events_truncated"]
    assert sum(row["case_count"] for row in result["statistics"]["monthly"]) == 3


def test_read_does_not_flush_pending_caller_changes(facility_db):
    db = facility_db
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)
    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        db.autoflush = True
        db.add(JurisdictionAsset(name="尚未保存", asset_type="well", operational_area_id=1))
        build_region_content(db, operational_area_id=1)
        assert not writes
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)


def test_expired_production_is_historical_only_when_incident_was_covered(facility_db):
    from app.services.facility_dossier_content import build_dossier_content
    db = facility_db
    db.get(JurisdictionAsset, 1).attributes = {
        "oil_type": "原油", "water_cut_min": 20, "water_cut_max": 40, "water_cut_unit": "percent",
        "production_valid_from": "2020-01-01T00:00:00Z", "production_valid_to": "2021-01-01T00:00:00Z"}
    db.commit()
    comparison = build_region_content(db)["facilities"]["items"][0]["condition_comparison"]
    assert comparison["state"] == "stale" and "当前已过期" in str(comparison["gaps"])
    rows = {row["case_id"]: row for row in comparison["reference_cases"]}
    assert rows[1]["production_validity"]["incident_state"] == "covered"
    assert any("油品相同" in text and "不表示当前" in text for text in rows[1]["historical_conditions"])
    assert any("历史含水率参照" in text for text in rows[1]["historical_conditions"])
    for row in rows.values():
        assert not any("油品" in text or "含水率" in text for text in row["similar"])
    assert rows[2]["production_validity"]["incident_state"] == "outside"
    assert "不覆盖该案发时段" in str(rows[2]["gaps"])
    assert not any("油品相同" in text for text in rows[2]["historical_conditions"])
    dossier = build_dossier_content(db, 1)
    assert dossier["sections"]["production"]["state"] == "stale"
    assert dossier["sections"]["history_conditions"]["state"] == "stale"


def test_registration_without_validity_remains_comparable_with_explicit_unknown(facility_db):
    comparison = build_region_content(facility_db)["facilities"]["items"][0]["condition_comparison"]
    assert comparison["state"] == "ready"
    assert comparison["production_validity"]["current_state"] == "unknown"
    assert "时效未知" in str(comparison["gaps"])
    for row in comparison["reference_cases"]:
        assert "登记油品相同（时效未知）：原油" in row["similar"]
        assert "油品相符：原油" not in row["similar"]


def test_business_timezone_buckets_cross_utc_month_day_and_weekday(facility_db):
    db = facility_db
    at = datetime(2026, 9, 30, 17)  # SQLite stores UTC-naive by project contract.
    db.add(Case(id=5, case_number="FAC-MONTH-BOUNDARY", operational_area_id=1,
        occurred_time=at, latitude=46, longitude=125, facility_type="井口", oil_type="原油"))
    db.add(Event(id=5, event_number="EV-MONTH-BOUNDARY", operational_area_id=1,
        event_type="oil_trace", occurred_time=at, latitude=46, longitude=125))
    db.commit()
    result = build_region_content(db, start_date="2026-09-30T17:00:00Z", end_date="2026-09-30T18:00:00Z")
    stats = result["statistics"]
    assert stats["timezone"] == "Asia/Shanghai"
    assert stats["hour_day"] == [{"weekday": 3, "hour": 1, "count": 1}]  # Thursday, October 1.
    assert stats["monthly"] == [{"month": "2026-10", "case_count": 1, "event_count": 1}]
    assert len(stats["spatial_monthly"]) == 1
    assert stats["spatial_monthly"][0]["month"] == "2026-10"
    assert stats["spatial_monthly"][0]["case_count"] == 1
    assert result["cases"]["items"][0]["id"] == 5 and result["events"]["items"][0]["id"] == 5
    assert result["cases"]["items"][0]["occurred_time"] == "2026-09-30T17:00:00+00:00"
    assert result["events"]["items"][0]["occurred_time"] == "2026-09-30T17:00:00+00:00"
    assert result["window"]["start_date"] == "2026-09-30T17:00:00+00:00"
