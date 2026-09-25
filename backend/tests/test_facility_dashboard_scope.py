"""v5.4 regional and dashboard statistics share the exact half-open window."""
from datetime import datetime, timezone

import pytest

from app.services.dashboard_summary_service import DashboardSummaryService
from app.services.facility_condition_comparison import build_region_content
from tests.test_case_search_page import search_db, add_case  # noqa: F401


def test_dashboard_custom_window_matches_regional_full_count(search_db):
    start = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    end = datetime(2026, 1, 3, 12, tzinfo=timezone.utc)
    add_case(search_db, 'START', occurred_time=start)
    add_case(search_db, 'BEFORE', occurred_time=datetime(2026, 1, 1, 11, tzinfo=timezone.utc))
    add_case(search_db, 'END', occurred_time=end)
    add_case(search_db, 'HIDDEN', occurred_time=start, operational_area_id=2)
    search_db.commit()
    search_db.info['authorized_area_ids'] = (1,)
    measured_at = datetime(2026, 9, 25, tzinfo=timezone.utc)
    summary = DashboardSummaryService.build(search_db, operational_area_id=1, days=7,
        start_date=start, end_date=end, as_of=measured_at)
    region = build_region_content(search_db, operational_area_id=1, start_date=start, end_date=end)
    assert summary['metrics']['cases'] == region['statistics']['case_count'] == 1
    assert summary['metrics']['previous_cases'] == 1
    assert summary['period']['days'] == 2
    assert summary['period']['previous_start'] == datetime(2025, 12, 30, 12, tzinfo=timezone.utc)
    assert summary['as_of'] == measured_at
    assert summary['map']['missing_coordinate_cases'] == 1
    assert not search_db.new and not search_db.dirty


def test_dashboard_rejects_invalid_and_unbounded_trend_windows(search_db):
    for start, end in ((datetime(2026, 1, 3), datetime(2026, 1, 1)),
                       (datetime(1900, 1, 1), datetime(2026, 1, 1))):
        with pytest.raises(ValueError, match='dashboard_window_invalid'):
            DashboardSummaryService.build(search_db, operational_area_id=1, days=7,
                                           start_date=start, end_date=end)
