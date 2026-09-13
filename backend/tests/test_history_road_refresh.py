"""History mutations refresh delegated candidates, not formal case facts."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.case import Case
from app.models.case_pipeline import OutboxEvent
from app.models.road_network import RoadAccessMembership
from app.services import history_road_refresh as history
from app.services import road_refresh_jobs as refresh
from app.services.case_history_index_service import CaseHistoryIndexService
from app.services.case_road_jobs import EVENT_TYPE as COMPARE_TYPE
from app.services.case_service import CaseService
from test_case_history_index import db, make_case  # noqa: F401
from test_road_refresh_jobs import delegated, db_session, result_data, ready  # noqa: F401


def changes(db):
    return list(db.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == history.SOURCE_EVENT_TYPE)))


def index_pass(db):
    output = CaseHistoryIndexService.reconcile_batch(db)
    db.commit()
    return output['history_refresh_event_id']


def test_background_detects_time_only_edit_move_and_unchanged_input(db):
    case = make_case(db)
    first = index_pass(db)
    assert first and len(changes(db)) == 1
    assert index_pass(db) is None and len(changes(db)) == 1
    # A time-only edit matters to the incident-time cutoff despite identical words.
    case.occurred_time = datetime(2002, 1, 1, tzinfo=timezone.utc)
    db.commit()
    assert index_pass(db) is None  # active scan coalesces, never resets its cursor
    assert len(changes(db)) == 2
    case.operational_area_id = 2
    db.commit()
    index_pass(db)
    assert len(changes(db)) == 3
    assert any(set(event.payload['area_ids']) == {1, 2} for event in changes(db))
    db.get(OutboxEvent, first).status = 'completed'
    db.commit()
    second = index_pass(db)
    event = db.get(OutboxEvent, second)
    assert event.payload['area_ids'] == [1, 2]
    assert event.payload['source_change_count'] == 2
    assert not event.payload['unknown_area']


def test_changed_then_restored_history_creates_new_revision(db):
    case = make_case(db)
    original = case.description
    first = index_pass(db)
    db.get(OutboxEvent, first).status = 'completed'
    case.description = '更新后的资料'
    db.commit()
    second = index_pass(db)
    db.get(OutboxEvent, second).status = 'completed'
    case.description = original
    db.commit()
    third = index_pass(db)
    assert len({first, second, third}) == 3
    assert index_pass(db) is None


def test_delete_notification_survives_cascade_and_contains_no_raw_case(db):
    case = make_case(db)
    identifier = case.id
    first = index_pass(db)
    db.get(OutboxEvent, first).status = 'completed'
    db.commit()
    assert CaseService.delete_case(db, identifier)
    assert db.get(Case, identifier) is None
    second = index_pass(db)
    assert second and db.get(OutboxEvent, second).payload['source_change_count'] == 1
    assert all('夜间' not in str(event.payload) for event in changes(db))


def test_delete_failure_rolls_back_case_and_notification(db, monkeypatch):
    from app.repositories.case_repository import CaseRepository
    case = make_case(db)
    identifier = case.id
    def fail(repo, row):
        repo.db.delete(row)
        repo.db.flush()
        raise RuntimeError('before commit')
    monkeypatch.setattr(CaseRepository, 'delete', fail)
    with pytest.raises(RuntimeError, match='before commit'):
        CaseService.delete_case(db, identifier)
    assert db.get(Case, identifier) is not None
    assert not changes(db)


def test_index_and_refresh_handoff_rollback_together(db):
    case = make_case(db)
    result = CaseHistoryIndexService.reconcile_batch(db)
    event_id = result['history_refresh_event_id']
    assert event_id
    db.rollback()
    assert not changes(db) and db.get(OutboxEvent, event_id) is None
    assert index_pass(db)


def test_corrupt_cache_remains_rebuildable_and_does_not_block_deletion(db):
    from app.models.case_history_index import CaseHistoryIndex
    case = make_case(db)
    first = index_pass(db)
    db.get(OutboxEvent, first).status = 'completed'
    index = db.get(CaseHistoryIndex, (case.id, 'case', str(case.id)))
    index.payload = ['invalid cache']
    db.commit()
    second = index_pass(db)
    assert db.get(OutboxEvent, second).payload['unknown_area']
    index.payload = ['invalid cache']
    db.commit()
    assert CaseService.delete_case(db, case.id)


def create_refresh(db, areas=(1,)):
    history.record_change(db, case_id=99, area_ids=list(areas))
    db.flush()
    identifier = history.coalesce_changes(db)
    db.commit()
    return identifier


def test_history_requeues_existing_result_once_per_batch_with_original_scope(delegated):
    db, result_id = delegated
    before = dict(db.info)
    first = create_refresh(db)
    assert refresh.process(db, first)['created'] == 1
    assert db.info == before
    assert refresh.process(db, first)['claimed'] is False
    second = create_refresh(db)
    assert refresh.process(db, second)['created'] == 1
    jobs = list(db.scalars(select(OutboxEvent).where(OutboxEvent.event_type == COMPARE_TYPE)))
    assert len(jobs) == 2
    assert {job.payload['history_refresh_event_id'] for job in jobs} == {first, second}
    assert all(job.payload['scope'] == [1] and job.payload['user_id'] == 1
               and job.payload['result_id'] == result_id for job in jobs)
    assert db.get(Case, 1).description == '合成记录'


@pytest.mark.parametrize('change', ['other_scope', 'revoked', 'cancelled'])
def test_refresh_never_expands_scope_or_restarts_cancelled_work(delegated, change):
    db, result_id = delegated
    if change == 'revoked':
        db.query(RoadAccessMembership).delete()
    elif change == 'cancelled':
        db.add(OutboxEvent(id='cancelled-history', event_type=COMPARE_TYPE,
            aggregate_type='case_result', aggregate_id=result_id, payload={},
            idempotency_key='cancelled-history', status='cancelled'))
    db.commit()
    identifier = create_refresh(db, areas=(2,) if change == 'other_scope' else (1,))
    assert refresh.process(db, identifier)['created'] == 0
    assert db.query(OutboxEvent).filter_by(event_type=COMPARE_TYPE, status='pending').count() == 0


def test_background_task_dispatches_history_scan(delegated, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.tasks import case_road_tasks
    db, _ = delegated
    identifier = create_refresh(db)
    monkeypatch.setattr(case_road_tasks, 'SessionLocal', sessionmaker(bind=db.bind, autoflush=False))
    result = case_road_tasks.process_next_comparison.run()
    assert result['event_id'] == identifier and result['created'] == 1


def test_notifications_during_scan_are_not_lost_and_batch_is_bounded(db, monkeypatch):
    monkeypatch.setattr(history, 'BATCH_SIZE', 2)
    for identifier in range(3):
        history.record_change(db, case_id=identifier + 1, area_ids=[1])
    db.flush()
    first = history.coalesce_changes(db)
    db.commit()
    assert db.get(OutboxEvent, first).payload['source_change_count'] == 2
    assert history.coalesce_changes(db) is None
    history.record_change(db, case_id=4, area_ids=[2])
    db.get(OutboxEvent, first).status = 'completed'
    db.commit()
    second = history.coalesce_changes(db)
    db.commit()
    assert second != first
    assert db.get(OutboxEvent, second).payload['source_change_count'] == 2
    assert all(event.status == 'completed' for event in changes(db))
