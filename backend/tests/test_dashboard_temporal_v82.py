from datetime import datetime, timezone

from app.models.case_source import CaseLocation
from app.services.dashboard_summary_service import DashboardSummaryService
from test_case_search_page import search_db, add_case, client_for  # noqa: F401

NOW = datetime(2026, 10, 8, 4, tzinfo=timezone.utc)


def test_dashboard_discovery_does_not_treat_late_entry_as_new_event(search_db):
    search_db.info['authorized_area_ids'] = (1,)
    current = add_case(search_db, 'DISCOVERY', discovered_at=datetime(2026, 10, 2),
        occurred_time=None, created_at=datetime(2026, 10, 3), latitude=47, longitude=126)
    late = add_case(search_db, 'LATE', discovered_at=datetime(2026, 7, 1),
        occurred_time=datetime(2026, 7, 1), created_at=datetime(2026, 10, 3))
    add_case(search_db, 'UNKNOWN', discovered_at=None, created_at=datetime(2026, 10, 3))
    search_db.add(CaseLocation(case_id=current.id, role='discovery', precision='exact',
        geometry={'type': 'Point', 'coordinates': [125, 46]}))
    search_db.commit()
    result = DashboardSummaryService.build(search_db, operational_area_id=1, days=30,
        as_of=NOW, time_basis='discovery')
    assert result['metrics']['cases'] == 1
    assert result['map']['cases'][0]['id'] == current.id
    assert result['map']['cases'][0]['location_role'] == 'discovery'
    created = next(item for item in result['activities'] if item['case_id'] == current.id)
    assert (created['latitude'], created['longitude']) == (46, 125)
    for item in result['activities']:
        if item['case_id'] != current.id:
            assert item['latitude'] is None and item['longitude'] is None
    assert sum(row['count'] for row in result['trend']) == 1
    origins = result['temporal_comparison']['change_origins']
    assert origins['late_entry']['case_ids'] == [late.id]
    assert result['temporal_comparison']['quality']['unknown_time_count'] == 1
    assert result['period']['end'].isoformat() == '2026-10-08T00:00:00+08:00'


def test_incident_interval_cross_days_counted_without_fake_day_or_discovery_point(search_db):
    search_db.info['authorized_area_ids'] = (1,)
    row = add_case(search_db, 'INTERVAL', time_precision='interval', occurred_time=None,
        occurred_from=datetime(2026, 10, 1), occurred_to=datetime(2026, 10, 3), latitude=46, longitude=125)
    search_db.add(CaseLocation(case_id=row.id, role='discovery', precision='exact',
        geometry={'type': 'Point', 'coordinates': [125, 46]}))
    search_db.commit()
    result = DashboardSummaryService.build(search_db, operational_area_id=1, days=30,
        as_of=NOW, time_basis='incident')
    assert result['metrics']['cases'] == 1
    assert result['map']['cases'] == []
    assert result['trend_unbucketed_cases'] == 1
    assert sum(row['count'] for row in result['trend']) == 0


def test_dashboard_new_basis_requires_explicit_authorized_area(search_db):
    search_db.info['authorized_area_ids'] = (1,)
    client = client_for(search_db)
    assert client.get('/api/cases/dashboard-summary?time_basis=discovery').status_code == 422
    assert client.get('/api/cases/dashboard-summary?time_basis=discovery&operational_area_id=2').status_code == 403
    assert client.get('/api/cases/dashboard-summary?time_basis=invalid&operational_area_id=1').status_code == 422
