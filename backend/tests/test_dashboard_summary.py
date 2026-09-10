"""大屏统计使用完整授权集，地图点位限额不得改变统计。"""
from datetime import datetime, timedelta, timezone

from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.models.case_insight import CaseAnalysisRun
from app.models.case_pipeline import CaseAnalysisProfile
from app.models.map_foundation import MapSnapshot, PublicMapBundle
from app.services.dashboard_summary_service import DashboardSummaryService
from test_case_search_page import search_db, add_case, client_for  # noqa: F401


NOW = datetime(2026, 9, 10, 4, tzinfo=timezone.utc)


def current_insight_fixture(db):
    from tests.test_intelligent_query_tools import insight_fixture
    values = insight_fixture(db)
    values[3].status = 'current'
    db.commit()
    return values


def test_full_scope_counts_include_missing_coordinates_and_zero_days(search_db):
    for index in range(125):
        add_case(search_db, f"CURRENT-{index}", latitude=46 if index < 10 else None,
                 longitude=125 if index < 10 else None)
    add_case(search_db, "PREVIOUS", occurred_time=datetime(2026, 9, 1))
    add_case(search_db, "FUTURE", occurred_time=NOW + timedelta(days=1))
    add_case(search_db, "PRIVATE", operational_area_id=2)
    search_db.add_all([
        JurisdictionAsset(name="井一", asset_type="well", operational_area_id=1),
        JurisdictionAsset(name="井二", asset_type="well", operational_area_id=2),
        JurisdictionAsset(name="停用井", asset_type="well", operational_area_id=1, status="inactive"),
    ])
    search_db.commit()
    search_db.info["authorized_area_ids"] = (1,)
    result = DashboardSummaryService.build(search_db, operational_area_id=1, days=7, as_of=NOW, map_limit=5)
    assert result["metrics"] == {"cases": 125, "previous_cases": 1, "change": 124,
                                  "registered_wells": 1, "analysis_results": 0}
    assert result["map"]["missing_coordinate_cases"] == 115
    assert result["map"]["coordinate_cases"] == 10
    assert len(result["map"]["cases"]) == 5
    assert result["map"]["cases_truncated"] is True
    assert sum(row["count"] for row in result["trend"]) == 125
    assert any(row["count"] == 0 for row in result["trend"])
    assert len(result["attention"]) == 1
    assert result["attention"][0]["current_count"] == 125
    assert result["attention"][0]["kind"] == "observed_change"
    assert search_db.query(Case).count() == 127  # 全程只读（另一区不可见）


def test_denied_scope_is_empty_and_no_change_does_not_invent_attention(search_db):
    add_case(search_db, "SECRET", operational_area_id=2)
    search_db.commit()
    search_db.info["authorized_area_ids"] = (1,)
    result = DashboardSummaryService.build(search_db, operational_area_id=2, days=7, as_of=NOW)
    assert result["metrics"]["cases"] == 0
    assert result["state"] == "empty"
    assert result["attention"] == []
    assert result["map"]["cases"] == []
    assert client_for(search_db).get("/api/cases/dashboard-summary?operational_area_id=2").status_code == 403


def test_attention_includes_existing_insight_with_current_evidence_scope(search_db):
    run, candidate, hidden, _ = current_insight_fixture(search_db)
    search_db.info['authorized_area_ids'] = (1,)
    result = DashboardSummaryService.build(search_db, operational_area_id=1, days=7, as_of=NOW)
    item = next(item for item in result['attention'] if item['kind'] == 'existing_insight')
    assert item['claim'] == candidate.claim
    assert item['counter_evidence'] == candidate.counter_evidence
    assert item['run_id'] == run.id
    assert len(result['attention']) <= 3
    candidate.evidence_refs = [f'case:{hidden.id}']
    search_db.commit()
    result = DashboardSummaryService.build(search_db, operational_area_id=1, days=7, as_of=NOW)
    assert all(item['kind'] != 'existing_insight' for item in result['attention'])


def test_attention_does_not_recommend_superseded_candidates(search_db):
    _, candidate, _, _ = current_insight_fixture(search_db)
    candidate.status = 'superseded'
    search_db.commit()
    search_db.info['authorized_area_ids'] = (1,)
    result = DashboardSummaryService.build(search_db, operational_area_id=1, days=7, as_of=NOW)
    assert all(item['kind'] != 'existing_insight' for item in result['attention'])


def test_attention_stays_within_three_and_preserves_change_facts(search_db):
    run, _, _, _ = current_insight_fixture(search_db)
    for index in range(4):
        add_case(search_db, f'TYPE-{index}', case_type=f'类型{index}')
    search_db.commit()
    search_db.info['authorized_area_ids'] = (1,)
    result = DashboardSummaryService.build(search_db, operational_area_id=1, days=7, as_of=NOW)
    assert len(result['attention']) == 3
    assert [item['kind'] for item in result['attention']] == [
        'existing_insight', 'observed_change', 'observed_change']
    run.completed_at = NOW - timedelta(days=8)
    search_db.commit()
    result = DashboardSummaryService.build(search_db, operational_area_id=1, days=7, as_of=NOW)
    assert len(result['attention']) == 3
    assert all(item['kind'] == 'observed_change' for item in result['attention'])


def test_attention_excludes_old_inputs_while_reanalysis_is_pending(search_db):
    run, _, _, snapshot = current_insight_fixture(search_db)
    search_db.info['authorized_area_ids'] = (1,)
    profile = search_db.query(CaseAnalysisProfile).filter_by(id=run.case_profile_id).one()
    for old_input in ('profile', 'map'):
        profile.is_current = old_input != 'profile'
        snapshot.status = 'superseded' if old_input == 'map' else 'current'
        search_db.commit()
        result = DashboardSummaryService.build(search_db, operational_area_id=1, days=7, as_of=NOW)
        assert all(item['kind'] != 'existing_insight' for item in result['attention'])


def test_attention_scan_budget_is_explicit_without_truncating_counts(search_db):
    from app.models.case_insight import CaseHypothesis
    original, candidate, _, _ = current_insight_fixture(search_db)
    values = {column.name: getattr(candidate, column.name)
              for column in CaseHypothesis.__table__.columns
              if column.name not in {'id', 'analysis_run_id', 'evidence_refs'}}
    for index in range(51):
        run = CaseAnalysisRun(id=f'budget-{index}', case_id=original.case_id,
            case_profile_id=original.case_profile_id, map_snapshot_id=original.map_snapshot_id,
            algorithm_version=f'budget-{index}', status='completed', information_gaps=[],
            completed_at=NOW - timedelta(seconds=index + 1))
        search_db.add(run)
        search_db.flush()
        search_db.add(CaseHypothesis(**values, id=f'budget-h-{index}', analysis_run_id=run.id,
                                    evidence_refs=['unknown:unverifiable']))
    search_db.commit()
    search_db.info['authorized_area_ids'] = (1,)
    result = DashboardSummaryService.build(search_db, operational_area_id=1, days=7, as_of=NOW)
    assert result['metrics']['analysis_results'] == 52
    assert result['attention_scan']['truncated'] is True
    assert result['attention_scan']['limit'] == 50
    assert all(item['kind'] != 'existing_insight' for item in result['attention'])


def test_business_dates_and_equal_length_windows(search_db):
    add_case(search_db, "BEGIN", occurred_time=NOW - timedelta(days=7))
    add_case(search_db, "END", occurred_time=NOW)
    add_case(search_db, "CHINA-NEXT-DAY", occurred_time=datetime(2026, 9, 9, 17))
    search_db.commit()
    result = DashboardSummaryService.build(search_db, operational_area_id=1, days=7, as_of=NOW)
    assert result["metrics"]["cases"] == 2
    assert next(row["count"] for row in result["trend"] if row["date"] == "2026-09-10") == 1
    assert result["period"]["timezone"] == "Asia/Shanghai"
    assert result["period"]["start"] - result["period"]["previous_start"] == timedelta(days=7)


def test_api_validates_days_and_updates_after_edit_delete(search_db):
    item = add_case(search_db, "TODAY", occurred_time=datetime.now(timezone.utc) - timedelta(hours=1))
    search_db.commit()
    client = client_for(search_db)
    assert client.get("/api/cases/dashboard-summary?days=0").status_code == 422
    first = client.get("/api/cases/dashboard-summary?days=7&operational_area_id=1")
    assert first.status_code == 200
    assert first.json()["metrics"]["cases"] == 1
    item.occurred_time = datetime.now(timezone.utc) - timedelta(days=60)
    search_db.commit()
    assert client.get("/api/cases/dashboard-summary?days=7").json()["metrics"]["cases"] == 0
    search_db.delete(item)
    search_db.commit()
    assert client.get("/api/cases/dashboard-summary?days=7").json()["metrics"]["cases"] == 0


def test_historical_case_results_use_completion_time_and_scope(search_db):
    bundle = PublicMapBundle(bundle_id="fixture", provider="test", source_version="1",
                             license_record="fixture", bounds=[], manifest={}, package_hash="a" * 64)
    search_db.add(bundle)
    search_db.flush()
    for area in (1, 2):
        item = add_case(search_db, f"OLD-{area}", operational_area_id=area, occurred_time=datetime(2025, 1, 1))
        snapshot = MapSnapshot(id=f"map-{area}", version=f"map-{area}", operational_area_id=area,
                               public_bundle_id=bundle.id, manifest={}, feature_watermark="1")
        profile = CaseAnalysisProfile(id=f"profile-{area}", case_id=item.id, profile_version=1,
                                      source_hash="a" * 64, schema_version="1", dictionary_version="1",
                                      payload={}, quality_score=50, analysis_readiness="ready")
        search_db.add_all([snapshot, profile])
        search_db.flush()
        for index, status in enumerate(("completed", "degraded", "failed", "completed")):
            search_db.add(CaseAnalysisRun(id=f"run-{area}-{index}", case_id=item.id,
                case_profile_id=profile.id, map_snapshot_id=snapshot.id, algorithm_version=str(index),
                status=status, information_gaps=[],
                completed_at=NOW - timedelta(days=30 if index == 3 else 1)))
    search_db.commit()
    search_db.info["authorized_area_ids"] = (1,)
    result = DashboardSummaryService.build(search_db, operational_area_id=None, days=7, as_of=NOW)
    assert result["metrics"]["cases"] == 0
    assert result["metrics"]["analysis_results"] == 2
    assert result["state"] == "ready"
    assert result["attention"] == []
