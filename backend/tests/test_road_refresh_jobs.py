from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models.case import Case
from app.models.case_pipeline import OutboxEvent
from app.models.map_foundation import MapSnapshot
from app.models.road_network import RoadAccessMembership, RoadNetworkVersion
from app.services import road_refresh_jobs as refresh
from app.services.case_pipeline_service import (
    CASE_DICTIONARY_VERSION, CASE_PROFILE_SCHEMA_VERSION, CasePipelineService,
)
from app.services.case_result_service import CaseResultService
from app.services.case_road_jobs import EVENT_TYPE as COMPARE_TYPE
from app.services.case_road_triggers import REQUEST_TYPE
from test_case_results import db_session, result_data  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from test_case_road_triggers import source_event


@pytest.fixture
def delegated(ready, result_data):
    db = ready
    profile, run, _ = result_data
    profile.source_hash = CasePipelineService.source_hash(db, db.get(Case, 1))
    profile.schema_version = CASE_PROFILE_SCHEMA_VERSION
    profile.dictionary_version = CASE_DICTIONARY_VERSION
    profile.payload = {**profile.payload, 'source_hash': profile.source_hash}
    db.get(MapSnapshot, 'map-1').status = 'current'
    graph = db.get(RoadNetworkVersion, 'graph-1')
    graph.engine_version = '3.8.3'
    graph.valid_from = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.commit()
    source_event(db, profile)
    result_id, _ = CaseResultService.freeze_completed_inputs(db, profile, run)
    db.commit()
    request = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == REQUEST_TYPE))
    request.status = 'completed'
    db.commit()
    return db, result_id


def test_publication_metadata_transaction_rollback_and_idempotency(db_session):
    first = refresh.enqueue_publication(db_session, 'new-graph')
    assert first and refresh.enqueue_publication(db_session, 'new-graph') is None
    db_session.rollback()
    assert db_session.get(OutboxEvent, first) is None


def test_new_connection_requeues_without_any_old_path_or_artifact(delegated):
    db, result_id = delegated
    before = dict(db.info)
    event_id = refresh.enqueue_publication(db, 'graph-1')
    db.commit()
    outcome = refresh.process(db, event_id)
    assert outcome['status'] == 'completed' and outcome['created'] == 1
    assert db.info == before
    job = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == COMPARE_TYPE))
    assert job.payload['result_id'] == result_id
    assert job.payload['user_id'] == 1 and job.payload['scope'] == [1]
    assert job.payload['network_id'] == 'graph-1'
    assert refresh.process(db, event_id)['claimed'] is False
    assert db.query(OutboxEvent).filter_by(event_type=COMPARE_TYPE).count() == 1
    assert db.get(Case, 1).description == '合成记录'


@pytest.mark.parametrize('change', ['revoked', 'changed_case', 'other_graph', 'cancelled'])
def test_refresh_does_not_borrow_publisher_scope_or_reprocess_stale_inputs(delegated, change):
    db, _ = delegated
    if change == 'revoked':
        db.query(RoadAccessMembership).delete()
    elif change == 'changed_case':
        db.get(Case, 1).description = '后来修改，等待新画像'
    elif change == 'cancelled':
        db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == REQUEST_TYPE)).status = 'cancelled'
    db.commit()
    event_id = refresh.enqueue_publication(db, 'different-graph' if change == 'other_graph' else 'graph-1')
    db.commit()
    assert refresh.process(db, event_id)['created'] == 0
    assert db.query(OutboxEvent).filter_by(event_type=COMPARE_TYPE).count() == 0


def test_page_resume_deduplicates_child_jobs_and_registered_worker_dispatches(delegated, monkeypatch):
    from app.tasks import case_road_tasks
    db, _ = delegated
    request = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == REQUEST_TYPE))
    db.add(OutboxEvent(id='second-delegation', event_type=REQUEST_TYPE, aggregate_type='case_result',
        aggregate_id=request.aggregate_id, payload=request.payload,
        idempotency_key='second-delegation', status='completed'))
    db.commit()
    identifier = refresh.enqueue_publication(db, 'graph-1')
    db.commit()
    monkeypatch.setattr(refresh, 'PAGE_SIZE', 1)
    first = refresh.process(db, identifier)
    assert first['status'] == 'pending' and first['scanned'] == 1
    # Keep the calculation behind the refresh page in this dispatch fixture.
    job = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == COMPARE_TYPE))
    job.available_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db.commit()
    monkeypatch.setattr(case_road_tasks, 'SessionLocal', sessionmaker(bind=db.bind, autoflush=False))
    second = case_road_tasks.process_next_comparison.run()
    assert second['event_id'] == identifier and second['status'] == 'completed'
    assert second['scanned'] == 2 and second['created'] == 1
    assert db.query(OutboxEvent).filter_by(event_type=COMPARE_TYPE).count() == 1


def test_failed_page_rolls_back_children_and_retries_original_cursor(delegated, monkeypatch):
    db, _ = delegated
    identifier = refresh.enqueue_publication(db, 'graph-1')
    db.commit()
    original = refresh.enqueue_comparison
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('simulated interruption after child insert')
    monkeypatch.setattr(refresh, 'enqueue_comparison', interrupted)
    assert refresh.process(db, identifier)['status'] == 'retry'
    assert db.query(OutboxEvent).filter_by(event_type=COMPARE_TYPE).count() == 0
    event = db.get(OutboxEvent, identifier, populate_existing=True)
    assert event.payload['cursor'] == ''
    assert refresh.process(db, identifier)['claimed'] is False
    event.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    monkeypatch.setattr(refresh, 'enqueue_comparison', original)
    assert refresh.process(db, identifier)['created'] == 1


def test_future_conditions_wait_until_graph_validity_begins(delegated):
    db, _ = delegated
    identifier = refresh.enqueue_publication(db, 'graph-1',
        valid_from=datetime.now(timezone.utc) + timedelta(hours=1))
    db.commit()
    assert refresh.process(db, identifier)['claimed'] is False
    assert db.query(OutboxEvent).filter_by(event_type=COMPARE_TYPE).count() == 0


@pytest.mark.parametrize('fail_handoff', [False, True])
def test_ready_transition_and_refresh_event_are_one_commit(delegated, monkeypatch, tmp_path, fail_handoff):
    """DB transition proof; byte copying/source validation have separate tests."""
    from uuid import uuid4
    from app.services import road_publication_service as publication
    db, _ = delegated
    graph = db.get(RoadNetworkVersion, 'graph-1')
    graph.id = str(uuid4())
    graph.status = 'building'
    db.commit()
    identifier = graph.id
    monkeypatch.setattr(publication, '_check', lambda *args: None)
    monkeypatch.setattr(publication, 'install_graph_artifact', lambda *args, **kwargs: 'c' * 64)
    monkeypatch.setattr(publication, 'verify_graph_artifact', lambda *args: None)
    original = publication.enqueue_publication
    def interrupt(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('simulated failure before publication commit')
    if fail_handoff:
        monkeypatch.setattr(publication, 'enqueue_publication', interrupt)
        with pytest.raises(RuntimeError):
            publication.publish_road_candidate(db, identifier, work_root=tmp_path, artifact_root=tmp_path)
        assert db.get(RoadNetworkVersion, identifier, populate_existing=True).status == 'building'
        assert db.query(OutboxEvent).filter_by(event_type=refresh.EVENT_TYPE).count() == 0
    else:
        for expected in (True, False):
            assert publication.publish_road_candidate(db, identifier,
                work_root=tmp_path, artifact_root=tmp_path)['created'] is expected
        assert db.query(OutboxEvent).filter_by(event_type=refresh.EVENT_TYPE).count() == 1
