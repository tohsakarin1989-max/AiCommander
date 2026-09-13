from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.case_history_index import CaseHistoryIndex
from app.models.case_pipeline import OutboxEvent
from app.services.case_history_index_service import CaseHistoryIndexService
from app.services.case_history_vector_service import store_embedding
from app.services.case_service import CaseService
from app.services.vector_db_service import VectorDBService
from tests.test_case_history_index import db, make_case  # noqa: F401
from tests.test_case_history_retrieval import db_session  # noqa: F401


def test_legacy_vectors_use_current_sources_negation_and_explicit_partial(db, monkeypatch):
    first = make_case(db)
    second = make_case(db, 'NEGATED')
    second.description, second.location = '未转运。', '未知'
    first.description, first.location = '转运。', '未知'
    db.commit()
    CaseHistoryIndexService.reconcile_batch(db)
    db.commit()
    for row in db.scalars(select(CaseHistoryIndex)):
        store_embedding(db, row, [1., 0.], 'fixture-current')
    db.commit()
    model = SimpleNamespace(state='ready', model_version='fixture-current', encode=lambda _: [1., 0.])
    monkeypatch.setattr('app.services.vector_db_service.get_local_embedder', lambda: model)
    db.info['authorized_area_ids'] = (1,)
    service = VectorDBService()
    result = service.search_similar_cases('转运', db=db)
    assert [item['case_id'] for item in result] == [first.id]
    assert result[0]['score_kind'] == 'cosine_similarity_not_probability'
    assert service.status['complete'] is True
    assert service.find_semantic_serial_cases(first.id, db=db) == []
    first.description = '原文已经修改'
    db.commit()
    assert service.search_similar_cases('转运', db=db) == []
    assert service.status['state'] == 'partial'
    assert service.status['missing_vectors'] == 1
    assert service.status['complete'] is False
    model.state = 'unavailable'
    assert service.search_similar_cases('转运', db=db) == []
    assert service.status['state'] == 'unavailable'


def test_case_save_update_delete_never_constructs_or_calls_embedding(db, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('case save must not invoke vector/model runtime')
    monkeypatch.setattr(settings, 'ENABLE_VECTOR_DB', True)
    monkeypatch.setattr(VectorDBService, '__init__', forbidden)
    monkeypatch.setattr('app.services.local_embedding_service.get_local_embedder', forbidden)
    db.info.update(authorized_area_ids=(1,), area_access_levels={1: 'write'})
    case = CaseService.create_case(db, case_number='NO-SYNC-MODEL', occurred_time=datetime(2020, 1, 1),
                                  location='测试', description='原文', operational_area_id=1)
    assert db.query(OutboxEvent).filter(OutboxEvent.aggregate_id == str(case.id)).first().payload['history_index_pending'] is True
    CaseService.update_case(db, case.id, description='修改后原文')
    assert case.description == '修改后原文'
    assert CaseService.delete_case(db, case.id) is True


def test_removed_direct_writes_cannot_create_secondary_index(monkeypatch):
    service = VectorDBService()
    assert service.add_case(1, {'description': 'caller supplied'}, [1., 0.]) is False
    assert service.update_case(1, {}) is False
    assert service.delete_case(1) is False
    assert not hasattr(service, 'collection')


def test_legacy_semantic_api_preserves_results_and_reports_missing_model_or_index(db_session, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import SQLAlchemyError
    from app.api.cases import router
    from app.database import get_db
    db = db_session
    make_case(db)
    db.info['authorized_area_ids'] = (1,)
    app = FastAPI()
    app.include_router(router, prefix='/api/cases')
    app.dependency_overrides[get_db] = lambda: db
    model = SimpleNamespace(state='not_enabled', model_version=None, encode=lambda _: [1., 0.])
    monkeypatch.setattr('app.services.vector_db_service.get_local_embedder', lambda: model)
    with TestClient(app) as client:
        response = client.get('/api/cases/semantic/search?query=软管')
        assert response.status_code == 200 and response.json()['results'] == []
        assert response.json()['semantic_status']['state'] == 'not_enabled'
        model.state, model.model_version = 'ready', 'missing-index-model'
        response = client.get('/api/cases/semantic/search?query=软管')
        assert response.json()['semantic_status']['state'] == 'partial'
        assert response.json()['semantic_status']['missing_vectors'] == 1
        assert client.get('/api/cases/semantic/search?query=软管&top_k=101').status_code == 422
        def failure(*args, **kwargs):
            raise SQLAlchemyError('private connection details')
        monkeypatch.setattr(VectorDBService, 'search_similar_cases', failure)
        response = client.get('/api/cases/semantic/search?query=软管')
        assert response.status_code == 503 and 'private' not in response.text
