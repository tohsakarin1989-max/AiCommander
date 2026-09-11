from datetime import datetime, timedelta, timezone

import pytest

from app.services.situation_change_service import closed_window, case_changes
from tests.test_case_search_page import search_db, add_case  # noqa: F401


def test_closed_business_day_and_week_are_equal_windows():
    as_of = datetime(2026, 9, 11, 3, tzinfo=timezone.utc)
    day = closed_window(as_of, 'daily')
    assert day.current_end == datetime(2026, 9, 10, 16, tzinfo=timezone.utc)
    assert day.current_end - day.current_start == day.current_start - day.previous_start == timedelta(days=1)
    week = closed_window(as_of, 'weekly')
    assert week.current_end == datetime(2026, 9, 6, 16, tzinfo=timezone.utc)
    assert week.current_end - week.current_start == week.current_start - week.previous_start == timedelta(days=7)
    with pytest.raises(ValueError, match='timezone_required'):
        closed_window(datetime(2026, 9, 11), 'daily')


def test_case_time_is_not_import_or_profile_time_and_end_is_exclusive(search_db):
    window = closed_window(datetime(2026, 9, 11, 3, tzinfo=timezone.utc), 'daily')
    add_case(search_db, 'PREVIOUS', occurred_time=window.previous_start)
    add_case(search_db, 'CURRENT', occurred_time=window.current_start)
    add_case(search_db, 'EXCLUDED-END', occurred_time=window.current_end)
    add_case(search_db, 'OLD-IMPORTED-TODAY', occurred_time=window.previous_start - timedelta(days=30))
    add_case(search_db, 'OTHER-AREA', operational_area_id=2, occurred_time=window.current_start)
    search_db.commit()
    search_db.info['authorized_area_ids'] = (1,)
    result = case_changes(search_db, 1, window)
    assert result['current']['case_count'] == result['previous']['case_count'] == 1
    assert result['case_count_change'] == 0
    assert result['current']['profile_versions_generated'] == 0
    with pytest.raises(PermissionError):
        case_changes(search_db, 2, window)


def test_brief_freezes_comparison_and_new_input_creates_new_revision(search_db):
    from app.services.deployment_advisor_service import DeploymentAdvisorService
    as_of = datetime(2026, 9, 11, 3, tzinfo=timezone.utc)
    window = closed_window(as_of, 'daily')
    case = add_case(search_db, 'CURRENT', occurred_time=window.current_start)
    search_db.commit()
    first, reused = DeploymentAdvisorService.generate_brief(search_db,
        operational_area_id=1, period_type='daily', as_of=as_of)
    assert not reused and first.comparison_snapshot['current']['case_count'] == 1
    same, reused = DeploymentAdvisorService.generate_brief(search_db,
        operational_area_id=1, period_type='daily', as_of=as_of + timedelta(hours=1))
    assert reused and same.id == first.id
    case.occurred_time = window.previous_start
    search_db.commit()
    second, reused = DeploymentAdvisorService.generate_brief(search_db,
        operational_area_id=1, period_type='daily', as_of=as_of)
    assert not reused and second.id != first.id
    assert second.comparison_snapshot['current']['case_count'] == 0
    assert first.comparison_snapshot['current']['case_count'] == 1
    assert '处理进度，非新增案发' in first.summary
    case.operational_area_id = 2
    search_db.commit()
    search_db.info['authorized_area_ids'] = (1,)
    hidden = DeploymentAdvisorService.brief_to_dict(search_db, first)
    assert hidden['comparison_snapshot'] is None and hidden['status'] == 'unavailable'


def test_changes_require_real_increase_and_do_not_invent_probability(search_db):
    from app.services.situation_change_service import change_recommendations
    from app.services.deployment_advisor_service import DeploymentAdvisorService
    as_of = datetime(2026, 9, 11, 3, tzinfo=timezone.utc)
    window = closed_window(as_of, 'daily')
    search_db.info['authorized_area_ids'] = (1,)
    for index in range(3):
        add_case(search_db, f'NEW-{index}', occurred_time=window.current_start)
    search_db.commit()
    changes = case_changes(search_db, 1, window)
    recommendations = change_recommendations(changes, '一区')
    assert len(recommendations) == 1  # Three equivalent total/type/oil signals are not three tasks.
    assert len(recommendations[0]['evidence_refs']) == 3
    brief, _ = DeploymentAdvisorService.generate_brief(search_db, operational_area_id=1,
        period_type='daily', as_of=as_of)
    result = DeploymentAdvisorService.brief_to_dict(search_db, brief)
    assert result['recommendations'][0]['confidence'] is None
    assert result['comparison_snapshot']['change_rule']['calibrated_probability'] is False
    for index in range(3):
        add_case(search_db, f'OLD-{index}', occurred_time=window.previous_start)
    search_db.commit()
    assert change_recommendations(case_changes(search_db, 1, window), '一区') == []
