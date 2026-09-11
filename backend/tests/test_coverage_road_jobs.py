from threading import Event

import pytest

from app.models.case_pipeline import OutboxEvent
from app.models.road_network import RoadAccessMembership
from app.services import coverage_road_jobs as jobs
from app.services.spatial_coverage_service import compare_coverage, save_comparison
from tests.test_spatial_coverage import inventory, AS_OF
from tests.test_coverage_road_comparison import VEHICLE
from test_road_network_service import ready  # noqa: F401
from test_case_results import db_session, result_data  # noqa: F401


def prepare(db, monkeypatch):
    rows = inventory(db)
    for row in rows:
        row.attributes = {**row.attributes, 'operational_status_valid_until': '2099-01-01T00:00:00+00:00'}
    db.commit()
    monkeypatch.setattr(jobs, 'ENGINE_VERSION', 'valhalla-test')
    return save_comparison(db, compare_coverage(db, 1, as_of=AS_OF), created_by=None)


def enqueue(db, source):
    return jobs.enqueue(db, source['id'], at=AS_OF, vehicle=VEHICLE, distance_budget_m=3000)


def test_durable_enqueue_idempotency_and_rollback(ready, monkeypatch):
    source = prepare(ready, monkeypatch)
    one, two = enqueue(ready, source), enqueue(ready, source)
    assert one['created'] and not two['created']
    assert one['event_id'] == two['event_id']
    ready.rollback()
    assert ready.query(OutboxEvent).filter_by(event_type=jobs.EVENT_TYPE).count() == 0


@pytest.mark.parametrize('outcome', ['success', 'missing', 'failure', 'cancel', 'revoke', 'lease_lost'])
def test_fenced_artifact_and_authority(ready, monkeypatch, tmp_path, outcome):
    source = prepare(ready, monkeypatch)
    identifier = enqueue(ready, source)['event_id']
    ready.commit()
    previous = dict(ready.info)
    cancellation = Event()
    def calculate(db, comparison_id, **kwargs):
        assert kwargs['network_id'] == 'graph-1'
        if outcome == 'failure':
            raise RuntimeError('do not expose precise coordinates or private paths')
        if outcome == 'cancel':
            cancellation.set()
        if outcome == 'revoke':
            db.query(RoadAccessMembership).delete()
            db.commit()
        if outcome == 'lease_lost':
            db.query(OutboxEvent).filter_by(id=identifier).update({'worker_id': 'replacement'})
            db.commit()
        return {'state': 'information_missing' if outcome == 'missing' else 'calculated_reference',
                'comparison_id': comparison_id}
    monkeypatch.setattr(jobs, 'compare_coverage_roads', calculate)
    if outcome == 'lease_lost':
        with pytest.raises(RuntimeError, match='outbox_claim_lost'):
            jobs.process(ready, identifier, artifact_root=tmp_path, cancel_event=cancellation)
    else:
        result = jobs.process(ready, identifier, artifact_root=tmp_path, cancel_event=cancellation)
        assert result['status'] == {'success': 'completed', 'missing': 'completed', 'failure': 'retry',
                                    'cancel': 'cancelled', 'revoke': 'failed'}[outcome]
    row = ready.get(OutboxEvent, identifier, populate_existing=True)
    assert ('artifact' in row.payload) is (outcome in ('success', 'missing'))
    assert not row.error or 'private' not in row.error
    assert ready.info == previous
    if outcome in ('success', 'missing'):
        assert jobs.read_job(ready, identifier)['artifact']['state'] == calculate(ready, source['id'], network_id='graph-1')['state']
        ready.info['principal_user_id'] = 999
        with pytest.raises(PermissionError):
            jobs.read_job(ready, identifier)


def test_completed_job_rechecks_live_road_authority(ready, monkeypatch, tmp_path):
    source = prepare(ready, monkeypatch)
    identifier = enqueue(ready, source)['event_id']
    ready.commit()
    monkeypatch.setattr(jobs, 'compare_coverage_roads', lambda *args, **kwargs: {'state': 'calculated_reference'})
    assert jobs.process(ready, identifier, artifact_root=tmp_path)['status'] == 'completed'
    ready.query(RoadAccessMembership).delete()
    ready.commit()
    with pytest.raises(PermissionError):
        jobs.read_job(ready, identifier)


def test_api_accepts_durable_work_without_running_native_engine(ready, monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import governance
    from app.database import get_db
    source = prepare(ready, monkeypatch)
    app = FastAPI()
    app.include_router(governance.router, prefix='/api')
    @app.middleware('http')
    async def identity(request, call_next):
        request.state.principal = SimpleNamespace(user_id=1, role='admin')
        return await call_next(request)
    def database():
        yield ready
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        path = f"/api/deployment-sandbox/spatial-comparisons/{source['id']}/road-jobs"
        payload = {'vehicle': {'kind': 'auto'}, 'distance_budget_m': 3000}
        first = client.post(path, json=payload)
        assert first.status_code == 202, first.text
        identifier = first.json()['event_id']
        catalog = client.get(path, params={'page_size': 1})
        assert catalog.status_code == 200
        assert catalog.json()['total'] == 1
        assert catalog.json()['items'][0]['event_id'] == identifier
        assert set(catalog.json()['items'][0]) == {'event_id', 'status', 'created_at'}
        assert client.get(path, params={'page': 2, 'page_size': 1}).json()['items'] == []
        assert client.get(path, params={'page_size': 101}).status_code == 422
        assert client.post(path, json=payload).json()['event_id'] == identifier
        status = client.get(f'/api/deployment-sandbox/road-jobs/{identifier}')
        assert status.status_code == 200
        assert status.json()['status'] == 'pending' and status.json()['artifact'] is None
        assert client.post(path, json={**payload, 'network_id': 'unauthorized'}).status_code == 422
        cancelled = client.post(f'/api/deployment-sandbox/road-jobs/{identifier}/cancel')
        assert cancelled.status_code == 200 and cancelled.json()['status'] == 'cancelled'
        assert client.post(f'/api/deployment-sandbox/road-jobs/{identifier}/cancel').json()['status'] == 'cancelled'
        ready.info['authorized_area_ids'] = ()
        assert client.get(path).status_code == 404
        assert client.get(f'/api/deployment-sandbox/road-jobs/{identifier}').status_code == 404


def test_task_catalog_filters_other_users_before_pagination(ready, monkeypatch):
    source = prepare(ready, monkeypatch)
    identifier = enqueue(ready, source)['event_id']
    ready.commit()
    original = ready.get(OutboxEvent, identifier)
    ready.add(OutboxEvent(id='other-owner', event_type=jobs.EVENT_TYPE, aggregate_type='coverage_comparison',
        aggregate_id=source['id'], payload={**original.payload, 'user_id': 999},
        idempotency_key='x' * 64, status='pending'))
    ready.commit()
    result = jobs.list_jobs(ready, source['id'], page_size=1)
    assert result['total'] == 1
    assert result['items'][0]['event_id'] == identifier
    assert jobs.list_jobs(ready, source['id'], page=2, page_size=1)['items'] == []


def test_cancelled_during_worker_never_publishes(ready, monkeypatch, tmp_path):
    source = prepare(ready, monkeypatch)
    identifier = enqueue(ready, source)['event_id']
    ready.commit()
    def calculate(db, *args, **kwargs):
        signal = kwargs['cancel_event']
        assert not signal.is_set()
        assert jobs.cancel_job(db, identifier)['status'] == 'cancelled'
        signal.checked_at = float('-inf')
        assert signal.is_set()
        return {'state': 'calculated_reference'}
    monkeypatch.setattr(jobs, 'compare_coverage_roads', calculate)
    result = jobs.process(ready, identifier, artifact_root=tmp_path)
    assert result['status'] == 'cancelled'
    row = ready.get(OutboxEvent, identifier, populate_existing=True)
    assert row.status == 'cancelled' and 'artifact' not in row.payload
    assert not jobs.process(ready, identifier, artifact_root=tmp_path)['claimed']


def test_cancel_cannot_target_another_actor(ready, monkeypatch):
    source = prepare(ready, monkeypatch)
    identifier = enqueue(ready, source)['event_id']
    ready.commit()
    ready.info['principal_user_id'] = 999
    with pytest.raises(PermissionError):
        jobs.cancel_job(ready, identifier)
    assert ready.get(OutboxEvent, identifier).status == 'pending'
