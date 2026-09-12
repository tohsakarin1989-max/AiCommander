from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest
from sqlalchemy import select

from app.models.case import Case
from app.models.case_pipeline import OutboxEvent
from app.models.case_road_artifact import CaseRoadArtifact
from app.models.road_network import RoadAccessMembership
from app.models.user import User
from app.services import case_road_jobs as jobs
from app.services.road_access_policy import VehicleAssumption
from test_case_road_artifacts import artifact_input  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from test_case_results import db_session, result_data  # noqa: F401
from test_road_access_policy import AT


def enqueue(db, content):
    return jobs.enqueue_comparison(db, result_id=content['result_id'], analysis_at=AT,
        vehicle=VehicleAssumption(kind='auto', source='explicit_reference_assumption'),
        engine_version='valhalla-test')


def test_job_enqueue_is_transactional_and_idempotent(artifact_input):
    db, content = artifact_input
    first = enqueue(db, content)
    again = enqueue(db, content)
    assert first['created'] and not again['created'] and first['event_id'] == again['event_id']
    db.rollback()
    assert db.scalar(select(OutboxEvent.id).where(OutboxEvent.event_type == jobs.EVENT_TYPE)) is None


def test_facility_rule_versions_change_job_identity_and_supersede_old_pending_job(artifact_input, monkeypatch, tmp_path):
    db, content = artifact_input
    kwargs = dict(result_id=content['result_id'], analysis_at=AT,
        vehicle=VehicleAssumption(kind='auto', source='explicit_reference_assumption'),
        engine_version='valhalla-test', include_facility_pool=True)
    old = jobs.enqueue_comparison(db, **kwargs)
    db.commit()
    assert not jobs.enqueue_comparison(db, **kwargs)['created']
    changed = {**jobs.current_versions(), 'production': 'fixture-new-production'}
    monkeypatch.setattr(jobs, 'current_versions', lambda: changed)
    new = jobs.enqueue_comparison(db, **kwargs)
    db.commit()
    assert new['created'] and old['event_id'] != new['event_id']
    assert jobs.process_comparison(db, old['event_id'], artifact_root=tmp_path)['status'] == 'superseded'
    assert db.query(CaseRoadArtifact).count() == 0


@pytest.mark.parametrize('outcome', ['success', 'gap', 'failure', 'cancel', 'revoke', 'lease_lost'])
def test_worker_atomic_outcomes_and_live_authority(artifact_input, monkeypatch, tmp_path, outcome):
    db, content = artifact_input
    before_case = db.get(Case, 1).description
    identifier = enqueue(db, content)['event_id']
    db.commit()
    prior_info = dict(db.info)
    cancelled = Event()
    calls = []
    def calculate(session, **kwargs):
        calls.append(kwargs)
        assert kwargs['network_id'] == 'graph-1'
        assert session.info['principal_user_id'] == 1
        if outcome == 'failure':
            raise RuntimeError('sensitive internal path must not appear in job error')
        if outcome == 'cancel':
            cancelled.set()
        if outcome == 'revoke':
            session.query(RoadAccessMembership).delete()
            session.commit()
        if outcome == 'lease_lost':
            session.query(OutboxEvent).filter_by(id=identifier).update({'worker_id': 'new-worker'})
            session.commit()
        return {**deepcopy(content), 'matrix': None} if outcome == 'gap' else deepcopy(content)
    monkeypatch.setattr(jobs, 'compare_result_roads', calculate)
    if outcome == 'lease_lost':
        with pytest.raises(RuntimeError, match='outbox_claim_lost'):
            jobs.process_comparison(db, identifier, artifact_root=tmp_path, cancel_event=cancelled)
    else:
        result = jobs.process_comparison(db, identifier, artifact_root=tmp_path, cancel_event=cancelled)
        expected = {'success': 'completed', 'gap': 'completed', 'failure': 'retry',
                    'cancel': 'cancelled', 'revoke': 'retry'}[outcome]
        assert result['status'] == expected
        if outcome == 'gap':
            assert result['outcome'] == 'information_missing'
    assert db.query(CaseRoadArtifact).count() == int(outcome == 'success')
    assert db.get(Case, 1).description == before_case
    assert db.info == prior_info
    row = db.get(OutboxEvent, identifier, populate_existing=True)
    assert not row.error or 'sensitive' not in row.error
    if outcome != 'lease_lost':
        # Both terminal work and scheduled retry must not immediately run again.
        assert not jobs.process_comparison(db, identifier, artifact_root=tmp_path)['claimed']
        assert len(calls) == 1


@pytest.mark.parametrize('state', ['disabled', 'viewer', 'expired_lease'])
def test_worker_revalidates_identity_and_recovers_expired_claim(artifact_input, monkeypatch, tmp_path, state):
    db, content = artifact_input
    identifier = enqueue(db, content)['event_id']
    db.commit()
    if state == 'expired_lease':
        row = db.get(OutboxEvent, identifier)
        row.status, row.worker_id = 'processing', 'old-worker'
        row.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif state == 'disabled':
        db.get(User, 1).is_active = False
    else:
        db.get(User, 1).role = 'viewer'
    db.commit()
    def calculate(*args, **kwargs):
        assert state == 'expired_lease'
        return deepcopy(content)
    monkeypatch.setattr(jobs, 'compare_result_roads', calculate)
    result = jobs.process_comparison(db, identifier, artifact_root=tmp_path)
    assert result['status'] == ('completed' if state == 'expired_lease' else 'retry')
    assert db.query(CaseRoadArtifact).count() == int(state == 'expired_lease')


def test_registered_consumer_processes_durable_event_once(artifact_input, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.tasks import case_road_tasks
    from app.tasks.celery_app import celery_app
    db, content = artifact_input
    enqueue(db, content)
    db.commit()
    monkeypatch.setattr(case_road_tasks, 'SessionLocal', sessionmaker(bind=db.bind, autoflush=False))
    monkeypatch.setattr(jobs, 'compare_result_roads', lambda *args, **kwargs: deepcopy(content))
    schedule = celery_app.conf.beat_schedule['process-case-road-comparison']
    assert schedule['task'] == case_road_tasks.process_next_comparison.name
    assert schedule['options']['queue'] == 'road_analysis'
    assert 'app.tasks.case_road_tasks' in celery_app.conf.include
    assert case_road_tasks.process_next_comparison.run()['outcome'] == 'calculated'
    assert case_road_tasks.process_next_comparison.run() == {'selected': 0}
    assert db.query(CaseRoadArtifact).count() == 1


def test_retry_limit_retains_sanitized_failure_without_artifact(artifact_input, monkeypatch, tmp_path):
    db, content = artifact_input
    identifier = enqueue(db, content)['event_id']
    db.commit()
    def fail(*args, **kwargs):
        raise RuntimeError('not safe to expose')
    monkeypatch.setattr(jobs, 'compare_result_roads', fail)
    for attempt in range(3):
        result = jobs.process_comparison(db, identifier, artifact_root=tmp_path)
        assert result['status'] == ('retry' if attempt < 2 else 'failed')
        row = db.get(OutboxEvent, identifier, populate_existing=True)
        assert row.attempts == attempt + 1 and row.error == 'road_job_failed'
        row.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert not jobs.process_comparison(db, identifier, artifact_root=tmp_path)['claimed']
    assert db.query(CaseRoadArtifact).count() == 0
