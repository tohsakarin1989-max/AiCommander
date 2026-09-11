from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import governance
from app.database import get_db
from app.models.case import Case
from app.models.map_foundation import MapSnapshot
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_result_service import CaseResultService
from app.services import frozen_evaluation_service as evaluations
from test_case_results import db_session, result_data  # noqa: F401


def prepare(db, result_data):
    profile = result_data[0]
    case = db.get(Case, 1)
    profile.source_hash = CasePipelineService.source_hash(db, case)
    profile.payload = {**profile.payload, 'source_hash': profile.source_hash}
    profile.is_current = True
    db.get(MapSnapshot, 'map-1').status = 'current'
    db.info['authorized_area_ids'] = (1,)
    db.commit()
    result, _ = CaseResultService.create_current(db, 1)
    db.commit()
    return result


def test_archive_is_unlabeled_idempotent_and_rejects_stale_case(db_session, result_data):
    result = prepare(db_session, result_data)
    request = dict(result_id=result['id'], expected_checksum=result['content_sha256'], name='成果归档', version='1')
    first = evaluations.create_from_result(db_session, **request)
    assert evaluations.create_from_result(db_session, **request).id == first.id
    assert first.ground_truth == {} and first.manifest['negative_case_ids'] == []
    assert first.manifest['origin']['retrieval_context'] == 'archive_time'
    assert evaluations.run_evaluation(db_session, first.id).metrics['unlabeled_case_count'] == 1
    db_session.get(Case, 1).description = '归档后修改'
    db_session.commit()
    with pytest.raises(ValueError, match='not_current'):
        evaluations.create_from_result(db_session, **{**request, 'version': '2'})
    # The already-frozen input remains replayable; the changed source isn't recaptured.
    assert evaluations.run_evaluation(db_session, first.id).metrics['unlabeled_case_count'] == 1


def test_archive_api_permission_checksum_and_no_input_export(db_session, result_data):
    result = prepare(db_session, result_data)
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
    body = {'result_id': result['id'], 'expected_checksum': result['content_sha256'], 'name': '接口归档', 'version': '1'}
    with TestClient(app) as client:
        url = '/api/admin/evaluations/result-archives'
        response = client.post(url, json=body)
        assert response.status_code == 201, response.text
        assert response.json()['frozen_input_exported'] is False
        assert 'manifest' not in response.json()
        assert client.post(url, json={**body, 'expected_checksum': 'f' * 64}).status_code == 409
        db_session.info['authorized_area_ids'] = ()
        assert client.post(url, json=body).status_code == 404
        role['value'] = 'analyst'
        assert client.post(url, json=body).status_code == 403
