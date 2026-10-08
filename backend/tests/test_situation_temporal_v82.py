from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.models.case import Case
from app.models.case_source import DomainChange
from app.models.user import AuditLog
from app.services.case_source_service import CaseSourceService
from app.services.situation_temporal_changes import (
    case_changes, closed_window, snapshot_difference, record_withdrawal, WITHDRAWAL_ACTION,
)
from tests.test_case_search_page import search_db, add_case  # noqa: F401

AS_OF = datetime(2026, 10, 8, 4, tzinfo=timezone.utc)


def setup_scope(db):
    db.info['authorized_area_ids'] = (1,)
    return closed_window(AS_OF, 'daily')


def test_daily_is_thirty_days_weekly_is_full_business_week():
    window = closed_window(AS_OF, 'daily')
    assert window.current_end == datetime(2026, 10, 7, 16, tzinfo=timezone.utc)
    assert window.current_end - window.current_start == window.current_start - window.previous_start == timedelta(days=30)
    weekly = closed_window(AS_OF, 'weekly')
    assert weekly.current_end == datetime(2026, 10, 4, 16, tzinfo=timezone.utc)
    assert weekly.current_end - weekly.current_start == timedelta(days=7)
    with pytest.raises(ValueError, match='timezone_required'):
        closed_window(AS_OF.replace(tzinfo=None), 'daily')


def test_bases_do_not_replace_missing_or_old_observation_with_entry(search_db):
    w = setup_scope(search_db)
    new = add_case(search_db, 'NEW', discovered_at=w.current_start, created_at=w.current_start,
                   occurred_time=w.previous_start, time_precision='exact')
    old = add_case(search_db, 'LATE', discovered_at=w.previous_start, created_at=w.current_start,
                   occurred_time=w.previous_start, time_precision='exact')
    unknown = add_case(search_db, 'UNKNOWN', discovered_at=None, created_at=w.current_start,
                       occurred_time=w.current_start, time_precision=None)
    add_case(search_db, 'PRIVATE', operational_area_id=2, discovered_at=w.current_start)
    search_db.commit()
    result = case_changes(search_db, 1, w)
    assert result['current']['case_ids'] == [new.id]
    assert result['previous']['case_ids'] == [old.id]
    assert result['change_origins']['late_entry']['case_ids'] == [old.id]
    assert result['quality']['unknown_time_case_ids'] == [unknown.id]
    assert result['quality']['denominator'] == 3
    assert result['quality']['unknown_time_ratio'] == pytest.approx(1 / 3)
    incident = case_changes(search_db, 1, w, 'incident')
    assert incident['current']['case_count'] == 0
    assert incident['previous']['case_count'] == 2
    entry = case_changes(search_db, 1, w, 'entry')
    assert entry['current']['case_count'] == 3
    assert entry['change_origins']['recent_registered']['case_ids'] == [new.id]
    assert entry['change_origins']['entry_time_uncertain']['case_ids'] == [unknown.id]
    with pytest.raises(PermissionError):
        case_changes(search_db, 2, w)


def test_interval_crossing_period_is_uncertain_in_both_not_assigned_to_day(search_db):
    w = setup_scope(search_db)
    case = add_case(search_db, 'INTERVAL', occurred_time=None, time_precision='interval',
        occurred_from=w.current_start - timedelta(hours=1), occurred_to=w.current_start + timedelta(hours=1))
    end = add_case(search_db, 'END', occurred_time=w.current_end, time_precision='exact')
    search_db.commit()
    result = case_changes(search_db, 1, w, 'incident')
    assert result['current']['case_count'] == result['previous']['case_count'] == 0
    assert result['current']['uncertain_case_ids'] == result['previous']['uncertain_case_ids'] == [case.id]
    assert end.id not in result['current']['case_ids']


def test_full_set_counts_and_missing_zero_denominator(search_db):
    w = setup_scope(search_db)
    empty = case_changes(search_db, 1, w)
    assert empty['quality']['unknown_time_ratio'] is None
    for i in range(135):
        add_case(search_db, f'FULL-{i}', discovered_at=w.current_start, created_at=w.current_start)
    search_db.commit()
    result = case_changes(search_db, 1, w)
    assert result['current']['case_count'] == len(result['source_manifest']) == 135
    assert len(result['current']['case_ids']) == 135


def test_revisions_are_explained_and_permissions_hide_old_counts(search_db):
    w = setup_scope(search_db)
    case = add_case(search_db, 'CORRECTED', discovered_at=w.current_start, created_at=w.current_start)
    CaseSourceService.capture_change(search_db, case)
    search_db.commit()
    before = case_changes(search_db, 1, w)
    case.discovered_at = w.previous_start
    revision, change = CaseSourceService.capture_change(search_db, case)
    # Set a synthetic event clock without mutating an immutable source object.
    search_db.query(DomainChange).filter_by(id=change.id).update({'created_at': w.current_start}, synchronize_session=False)
    search_db.commit()
    after = case_changes(search_db, 1, w)
    assert after['current']['case_count'] == 0 and after['previous']['case_count'] == 1
    assert after['change_origins']['corrections']['items'][0]['revision_id'] == revision.id
    diff = snapshot_difference(search_db, before, after)
    assert diff['state'] == 'comparable' and diff['material_changed']
    assert diff['items'][1]['case_ids'] == [case.id]
    copied = deepcopy(after)
    copied['time_basis'] = 'entry'
    assert snapshot_difference(search_db, before, copied)['state'] == 'incomparable'
    case.operational_area_id = 2
    search_db.commit()
    current = case_changes(search_db, 1, w)
    hidden = snapshot_difference(search_db, before, current)
    assert hidden['state'] == 'incomparable' and hidden['items'] == []
    assert 'count' not in str(hidden)


def test_withdrawal_keeps_only_scope_metadata_and_rolls_back_with_delete(search_db):
    w = setup_scope(search_db)
    case = add_case(search_db, 'DELETE', description='不得留存在撤回统计中的原文')
    search_db.commit()
    record_withdrawal(search_db, case)
    search_db.flush()
    audit = search_db.query(AuditLog).filter_by(action=WITHDRAWAL_ACTION).one()
    assert '不得留存' not in str(audit.detail) and 'case_id' not in audit.detail
    search_db.rollback()
    assert search_db.query(AuditLog).filter_by(action=WITHDRAWAL_ACTION).count() == 0
    record_withdrawal(search_db, case)
    search_db.flush()
    search_db.query(AuditLog).filter_by(action=WITHDRAWAL_ACTION).update({'created_at': w.current_start.replace(tzinfo=None)})
    search_db.commit()
    assert case_changes(search_db, 1, w)['change_origins']['withdrawals']['count'] == 1
    search_db.info['authorized_area_ids'] = (2,)
    assert case_changes(search_db, 2, w)['change_origins']['withdrawals']['count'] == 0


def test_reading_changes_does_not_create_profiles_or_mutate_source(search_db):
    w = setup_scope(search_db)
    case = add_case(search_db, 'READONLY', discovered_at=w.current_start, created_at=w.current_start)
    search_db.commit()
    first = case_changes(search_db, 1, w)
    assert not search_db.new and not search_db.dirty and not search_db.deleted
    assert case_changes(search_db, 1, w) == first
    assert search_db.query(Case).filter_by(id=case.id).one().description is None
