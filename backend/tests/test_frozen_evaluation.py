from copy import deepcopy

import pytest

from app.models.case_pipeline import CaseAnalysisProfile
from app.services import frozen_evaluation_service as service
from tests.test_case_insights import db_session, _case, _current_map  # noqa: F401


def dataset(db):
    area, snapshot = _current_map(db)
    case = _case(db, 'FIXED-EMPTY', None, None)
    case.operational_area_id = area.id
    db.commit()
    profile = db.query(CaseAnalysisProfile).filter_by(case_id=case.id).one()
    db.info['authorized_area_ids'] = (area.id,)
    created = service.create_dataset(db, name='固定合成集', version='1',
        inputs=[{'case_id': case.id, 'profile_id': profile.id, 'snapshot_id': snapshot.id}],
        negative_case_ids=[case.id])
    return created, case


def test_persisted_negative_replay_survives_business_change_and_checks_scope(db_session):
    frozen, case = dataset(db_session)
    first = service.run_evaluation(db_session, frozen.id)
    assert first.metrics['negative_correct_empty_rate'] == 1
    assert first.metrics['positive_top3_hit_rate'] is None
    case.description = '后来修改的描述'
    case.latitude, case.longitude = 47, 125
    db_session.commit()
    second = service.run_evaluation(db_session, frozen.id)
    assert second.metrics == first.metrics
    assert second.trace_manifest == first.trace_manifest
    db_session.info['authorized_area_ids'] = ()
    with pytest.raises(PermissionError):
        service.run_evaluation(db_session, frozen.id)


def test_failure_counts_against_negative_and_tampering_is_rejected(db_session, monkeypatch):
    frozen, _ = dataset(db_session)
    def failed(_):
        raise ValueError('private details must not escape')
    monkeypatch.setattr(service, 'replay_inputs', failed)
    run = service.run_evaluation(db_session, frozen.id)
    assert run.status == 'partial_failure'
    assert run.metrics['failed_case_count'] == 1
    assert run.metrics['negative_correct_empty_rate'] == 0
    assert 'private details' not in str(run.trace_manifest)
    damaged = deepcopy(frozen.manifest)
    damaged['negative_case_ids'] = []
    frozen.manifest = damaged
    db_session.commit()
    with pytest.raises(ValueError, match='integrity'):
        service.run_evaluation(db_session, frozen.id)


def test_admin_api_does_not_export_inputs_and_rechecks_history(db_session):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import governance
    from app.database import get_db
    frozen, case = dataset(db_session)
    app = FastAPI()
    app.include_router(governance.router, prefix='/api')
    role = {'value': 'admin'}
    @app.middleware('http')
    async def principal(request, call_next):
        request.state.principal = SimpleNamespace(role=role['value'], user_id=None)
        return await call_next(request)
    def database():
        yield db_session
    app.dependency_overrides[get_db] = database
    entry = frozen.manifest['entries'][0]['payload']
    payload = {'name': '接口合成集', 'version': '1', 'inputs': [{'case_id': case.id,
        'profile_id': entry['profile']['id'], 'snapshot_id': entry['map']['id']}], 'negative_case_ids': [case.id]}
    with TestClient(app) as client:
        created = client.post('/api/admin/evaluations/fixed-datasets', json=payload)
        assert created.status_code == 201, created.text
        assert created.json()['frozen_input_exported'] is False
        assert 'manifest' not in created.json() and 'inputs' not in created.json()
        catalog = client.get('/api/admin/evaluations/fixed-datasets')
        assert catalog.status_code == 200
        assert created.json()['id'] in [item['id'] for item in catalog.json()['items']]
        assert all('manifest' not in item and 'inputs' not in item for item in catalog.json()['items'])
        assert catalog.json()['frozen_input_exported'] is False
        result = client.post('/api/admin/evaluations/fixed-run', json={'dataset_id': created.json()['id']})
        assert result.status_code == 201
        assert result.json()['metrics']['negative_correct_empty_rate'] == 1
        diagnostics = client.get(f'/api/admin/evaluations/runs/{result.json()["id"]}/diagnostics')
        assert diagnostics.status_code == 200
        assert diagnostics.json()['calibrated_probability'] is None
        calibration = client.get(f'/api/admin/evaluations/runs/{result.json()["id"]}/calibration')
        assert calibration.status_code == 200
        assert calibration.json()['status'] == 'insufficient_labels'
        assert calibration.json()['production_promotion_allowed'] is False
        assert len(client.get('/api/admin/evaluations/runs').json()) == 1
        repeated = client.post('/api/admin/evaluations/fixed-run', json={'dataset_id': created.json()['id'],
            'scorer_policy': 'current_candidate'})
        assert repeated.status_code == 201
        pair = {'baseline_run_id': result.json()['id'], 'candidate_run_id': repeated.json()['id']}
        comparison = client.post('/api/admin/evaluations/fixed-compare', json=pair)
        assert comparison.status_code == 200 and comparison.json()['mode'] == 'repeatability'
        assert client.post('/api/admin/evaluations/fixed-run', json={'dataset_id': frozen.id,
            'scorer_policy': 'arbitrary_script'}).status_code == 422
        db_session.info['authorized_area_ids'] = ()
        assert client.get(f'/api/admin/evaluations/runs/{result.json()["id"]}/diagnostics').status_code == 404
        assert client.get(f'/api/admin/evaluations/runs/{result.json()["id"]}/calibration').status_code == 404
        assert client.get('/api/admin/evaluations/fixed-datasets').json()['items'] == []
        assert client.get('/api/admin/evaluations/runs').json() == []
        assert client.post('/api/admin/evaluations/fixed-compare', json=pair).status_code == 404
        assert client.post('/api/admin/evaluations/fixed-run', json={'dataset_id': frozen.id}).status_code == 404
        role['value'] = 'viewer'
        assert client.post('/api/admin/evaluations/fixed-datasets', json=payload).status_code == 403


def test_unlabeled_and_positive_empty_have_different_denominators(db_session):
    frozen, case = dataset(db_session)
    value = frozen.manifest['entries'][0]['payload']
    inputs = [{'case_id': case.id, 'profile_id': value['profile']['id'], 'snapshot_id': value['map']['id']}]
    unlabeled = service.create_dataset(db_session, name='未标注', version='1', inputs=inputs)
    metrics = service.run_evaluation(db_session, unlabeled.id).metrics
    assert metrics['unlabeled_case_count'] == 1
    assert metrics['positive_top3_hit_rate'] is None and metrics['negative_correct_empty_rate'] is None
    positive = service.create_dataset(db_session, name='阳性空结果', version='1', inputs=inputs,
        ground_truth={str(case.id): [{'hypothesis_type': 'possible_source', 'expected_region_grid': '47:125'}]})
    result = service.run_evaluation(db_session, positive.id)
    assert result.metrics['positive_top3_hit_rate'] == 0
    assert result.metrics['empty_case_count'] == 1
    assert result.trace_manifest['records'][0]['correct'] is False


def test_repeatability_failure_regression_and_integrity(db_session, monkeypatch):
    frozen, _ = dataset(db_session)
    first = service.run_evaluation(db_session, frozen.id)
    repeated = service.run_evaluation(db_session, frozen.id)
    result = service.compare_runs(db_session, first.id, repeated.id)
    assert result['mode'] == 'repeatability'
    assert result['counts']['unchanged_correct'] == 1
    assert result['counts']['improved'] == 0
    def failed(_):
        raise ValueError('synthetic failure')
    monkeypatch.setattr(service, 'replay_inputs', failed)
    broken = service.run_evaluation(db_session, frozen.id)
    regression = service.compare_runs(db_session, first.id, broken.id)
    assert regression['counts']['regressed'] == 1
    assert regression['candidate_failed_cases'] == 1
    broken.metrics = {**broken.metrics, 'failed_case_count': 0}
    db_session.commit()
    with pytest.raises(ValueError, match='integrity'):
        service.compare_runs(db_session, first.id, broken.id)


def test_different_labels_are_not_comparable(db_session):
    frozen, case = dataset(db_session)
    value = frozen.manifest['entries'][0]['payload']
    other = service.create_dataset(db_session, name='其他标签', version='1', inputs=[{'case_id': case.id,
        'profile_id': value['profile']['id'], 'snapshot_id': value['map']['id']}])
    first = service.run_evaluation(db_session, frozen.id)
    second = service.run_evaluation(db_session, other.id)
    with pytest.raises(ValueError, match='inputs_or_labels_differ'):
        service.compare_runs(db_session, first.id, second.id)
