from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import governance
from app.database import get_db
from app.models.jurisdiction import JurisdictionAsset
from app.services import frozen_evaluation_service as service
from tests.test_frozen_evaluation import dataset
from tests.test_case_insights import db_session  # noqa: F401


def test_label_revision_preserves_input_and_old_run_after_live_case_change(db_session, monkeypatch):
    original, case = dataset(db_session)
    old_manifest = deepcopy(original.manifest)
    old_run = service.run_evaluation(db_session, original.id)
    case.description = '后来增加的业务信息，不作为旧评测输入'
    case.latitude, case.longitude = 47, 125
    db_session.commit()
    def forbidden(*args, **kwargs):
        raise AssertionError('label edits must not retrieve live inputs')
    monkeypatch.setattr(service, 'capture_inputs', forbidden)
    params = dict(version='2', ground_truth={}, negative_case_ids=[], reason='撤回未经确认的阴性标签')
    revised = service.revise_labels(db_session, original.id, **params)
    assert revised.id != original.id
    assert service.read_dataset(db_session, original.id).manifest == old_manifest
    assert revised.manifest['entries'] == old_manifest['entries']
    assert revised.manifest['label_revision']['parent_checksum'] == original.checksum
    assert service.revise_labels(db_session, original.id, **params).id == revised.id
    assert service.read_run(db_session, old_run.id).metrics['negative_case_count'] == 1
    new_run = service.run_evaluation(db_session, revised.id)
    assert new_run.metrics['unlabeled_case_count'] == 1
    assert new_run.metrics['negative_correct_empty_rate'] is None
    with pytest.raises(ValueError, match='inputs_or_labels_differ'):
        service.compare_runs(db_session, old_run.id, new_run.id)


def test_conflicting_labels_unknown_targets_and_version_overwrite_rejected(db_session):
    original, case = dataset(db_session)
    common = dict(version='2', reason='人工核验', negative_case_ids=[])
    with pytest.raises(PermissionError):
        service.revise_labels(db_session, original.id, **common,
            ground_truth={str(case.id): [{'hypothesis_type': 'possible_source', 'expected_asset_ids': [99999]}]})
    with pytest.raises(ValueError, match='negative_labels'):
        service.revise_labels(db_session, original.id, **{**common, 'negative_case_ids': [case.id]},
            ground_truth={str(case.id): [{'hypothesis_type': 'possible_source', 'expected_region_grid': '47:125'}]})
    with pytest.raises(ValueError, match='version_conflict'):
        service.revise_labels(db_session, original.id, **{**common, 'version': original.version}, ground_truth={})


def test_label_api_never_exports_frozen_inputs_and_checks_current_scope(db_session):
    original, case = dataset(db_session)
    db_session.add(JurisdictionAsset(id=123, name='合成核验设施', asset_type='well', operational_area_id=case.operational_area_id))
    db_session.commit()
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
    url = f'/api/admin/evaluations/fixed-datasets/{original.id}'
    payload = {'version': '2', 'reason': '撤回标签', 'ground_truth': {}, 'negative_case_ids': []}
    with TestClient(app) as client:
        labels = client.get(url + '/labels')
        assert labels.status_code == 200
        assert labels.json()['negative_case_ids'] == [case.id]
        assert 'entries' not in labels.json() and 'manifest' not in labels.json()
        lookup = client.get(url + '/label-assets', params={'case_id': case.id, 'q': '核验'})
        assert lookup.status_code == 200
        assert lookup.json()['items'] == [{'id': 123, 'name': '合成核验设施', 'asset_type': 'well'}]
        assert client.get(url + '/label-assets', params={'case_id': 99999}).status_code == 404
        assert client.get(url + '/label-assets', params={'case_id': case.id, 'q': '%'}).json()['items'] == []
        created = client.post(url + '/label-versions', json=payload)
        assert created.status_code == 201, created.text
        assert created.json()['frozen_input_exported'] is False
        db_session.info['authorized_area_ids'] = ()
        assert client.get(url + '/labels').status_code == 404
        assert client.get(url + '/label-assets', params={'case_id': case.id}).status_code == 404
        assert client.post(url + '/label-versions', json=payload).status_code == 404
        role['value'] = 'analyst'
        assert client.post(url + '/label-versions', json=payload).status_code == 403
