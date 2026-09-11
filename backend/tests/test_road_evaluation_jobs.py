from threading import Event

import pytest

from app.models.case_pipeline import OutboxEvent
from app.models.governance import EvaluationRun
from app.models.road_network import RoadAccessMembership
from app.services import road_evaluation_jobs as jobs
from app.services import frozen_road_dataset
from app.services.vehicle_router import RoadCalculationError
from tests.test_frozen_road_inputs import freeze
from tests.test_case_road_artifacts import artifact_input  # noqa: F401
from test_road_network_service import ready  # noqa: F401
from test_case_results import db_session, result_data  # noqa: F401


def prepare(artifact_input, monkeypatch, tmp_path):
    db, content = artifact_input
    envelope = freeze(db, content, monkeypatch, tmp_path)
    dataset = frozen_road_dataset.create_dataset(db, name='后台道路评测', version='1',
        artifact_ids=[envelope['payload']['artifact_id']], artifact_root=tmp_path)
    db.commit()
    return db, dataset.id


@pytest.mark.parametrize('outcome', ['success', 'failure', 'cancel', 'revoke', 'lease_lost'])
def test_background_result_fence_and_failure_accounting(artifact_input, monkeypatch, tmp_path, outcome):
    db, dataset_id = prepare(artifact_input, monkeypatch, tmp_path)
    submitted = jobs.enqueue(db, dataset_id, request_id='fixed-run-1')
    assert jobs.enqueue(db, dataset_id, request_id='fixed-run-1')['created'] is False
    db.commit()
    event_id = submitted['event_id']
    cancelled = Event()
    def replay(db, envelope, **kwargs):
        if outcome == 'failure':
            raise RoadCalculationError('private engine failure')
        if outcome == 'cancel':
            cancelled.set()
        if outcome == 'revoke':
            db.query(RoadAccessMembership).delete()
            db.commit()
        if outcome == 'lease_lost':
            db.query(OutboxEvent).filter_by(id=event_id).update({'worker_id': 'replacement'}, synchronize_session=False)
            db.commit()
        return {'result_checksum': 'f' * 64}
    monkeypatch.setattr(jobs, 'replay_road_inputs', replay)
    result = jobs.process(db, event_id, artifact_root=tmp_path, cancel_event=cancelled)
    runs = db.query(EvaluationRun).filter_by(id=event_id).all()
    if outcome in ('success', 'failure'):
        assert result['status'] == 'completed'
        assert len(runs) == 1
        assert runs[0].metrics['failed_sample_count'] == int(outcome == 'failure')
        assert runs[0].metrics['accuracy'] is None
        assert 'private engine failure' not in str(runs[0].trace_manifest)
        assert jobs.process(db, event_id, artifact_root=tmp_path)['claimed'] is False
        assert db.query(EvaluationRun).count() == 1
        assert jobs.read_run(db, event_id)['metrics']['sample_count'] == 1
        db.query(RoadAccessMembership).delete()
        db.commit()
        with pytest.raises(PermissionError):
            jobs.read_run(db, event_id)
    else:
        assert runs == []
        assert result['status'] in ('cancelled', 'failed', 'processing')


def test_job_api_permissions_cancel_and_input_validation(artifact_input, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import governance
    from app.database import get_db
    db, dataset_id = prepare(artifact_input, monkeypatch, tmp_path)
    app = FastAPI()
    app.include_router(governance.router, prefix='/api')
    role = {'value': 'admin'}
    @app.middleware('http')
    async def principal(request, call_next):
        request.state.principal = SimpleNamespace(role=role['value'], user_id=1)
        return await call_next(request)
    def database():
        yield db
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        original = frozen_road_dataset.read_dataset(db, dataset_id)
        artifact_id = original.manifest['entries'][0]['payload']['artifact_id']
        from app.services import frozen_road_inputs
        def no_http_graph_hash(*args):
            raise AssertionError('graph verification must run in worker')
        monkeypatch.setattr(frozen_road_inputs, 'verify_graph_artifact', no_http_graph_hash)
        captured = client.post('/api/admin/evaluations/road-datasets', json={
            'name': '接口固定输入', 'version': '1', 'artifact_ids': [artifact_id]})
        assert captured.status_code == 201, captured.text
        assert captured.json()['graph_verification'] == 'deferred_to_worker'
        assert captured.json()['frozen_input_exported'] is False
        assert 'manifest' not in captured.json()
        payload = {'dataset_id': dataset_id, 'request_id': 'admin-test-1'}
        response = client.post('/api/admin/evaluations/road-jobs', json=payload)
        assert response.status_code == 202, response.text
        event_id = response.json()['event_id']
        url = '/api/admin/evaluations/road-jobs/' + event_id
        assert client.get(url).json()['status'] == 'pending'
        catalog = client.get('/api/admin/evaluations/road-jobs').json()
        assert catalog['total'] == 1 and catalog['items'][0]['event_id'] == event_id
        assert client.post('/api/admin/evaluations/road-jobs', json={**payload, 'artifact_root': '/tmp'}).status_code == 422
        assert client.post(url + '/cancel').json()['status'] == 'cancelled'
        assert jobs.process(db, event_id, artifact_root=tmp_path)['claimed'] is False
        role['value'] = 'analyst'
        assert client.get(url).status_code == 403
        assert client.get('/api/admin/evaluations/road-jobs').status_code == 403


def test_registered_worker_consumes_evaluation_once(artifact_input, monkeypatch, tmp_path):
    from sqlalchemy.orm import sessionmaker
    from app.tasks import case_road_tasks
    db, dataset_id = prepare(artifact_input, monkeypatch, tmp_path)
    event_id = jobs.enqueue(db, dataset_id, request_id='worker-integration')['event_id']
    db.commit()
    monkeypatch.setattr(case_road_tasks, 'SessionLocal', sessionmaker(bind=db.bind, autoflush=False))
    monkeypatch.setattr(jobs, 'replay_road_inputs', lambda *args, **kwargs: {'result_checksum': 'a' * 64})
    assert case_road_tasks.process_next_comparison.run()['event_id'] == event_id
    assert case_road_tasks.process_next_comparison.run() == {'selected': 0}
    assert db.query(EvaluationRun).filter_by(id=event_id).count() == 1


def test_owner_directory_paginates_and_allows_cancel_after_revocation(artifact_input, monkeypatch, tmp_path):
    db, dataset_id = prepare(artifact_input, monkeypatch, tmp_path)
    own = [jobs.enqueue(db, dataset_id, request_id=f'owner-{index}')['event_id'] for index in range(2)]
    db.add(OutboxEvent(id='other-owner', event_type=jobs.EVENT_TYPE, aggregate_type='evaluation_dataset',
        aggregate_id=str(dataset_id), payload={'user_id': 999}, idempotency_key='other-owner', status='pending'))
    db.commit()
    original_info = dict(db.info)
    first = jobs.list_jobs(db, page=1, page_size=1)
    second = jobs.list_jobs(db, page=2, page_size=1)
    assert first['total'] == second['total'] == 2
    assert {first['items'][0]['event_id'], second['items'][0]['event_id']} == set(own)
    assert first['items'][0]['source_available'] is True
    assert db.info == original_info
    db.query(RoadAccessMembership).delete()
    db.commit()
    revoked = jobs.list_jobs(db)
    assert revoked['total'] == 2
    assert all(row['dataset_id'] is None and not row['source_available'] for row in revoked['items'])
    assert jobs.cancel(db, own[0])['status'] == 'cancelled'
    with pytest.raises(PermissionError):
        jobs.cancel(db, 'other-owner')
