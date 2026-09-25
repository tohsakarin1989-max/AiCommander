from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.api.facility_analysis import router
from app.models.facility_summary import FacilityDerivedSummary
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import UserAreaScope
from app.models.user import User
from app.services.facility_summary_service import reconcile_catalog, summary_metadata
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401


def asset(db, area=1, name='同名井', external_id='A'):
    row = JurisdictionAsset(name=name, asset_type='well', operational_area_id=area,
        external_id=external_id, latitude=46.6, longitude=125.0, verified=True,
        attributes={'oil_type': '原油', 'production_output': 10})
    db.add(row)
    db.commit()
    return row


def client(db, uid=1):
    app = FastAPI()
    @app.middleware('http')
    async def auth(request, call_next):
        if uid is not None:
            request.state.principal = SimpleNamespace(user_id=uid, role='analyst')
        return await call_next(request)
    def session():
        yield db
    app.dependency_overrides[get_db] = session
    app.include_router(router, prefix='/api/facility-analysis')
    return TestClient(app)


def test_catalog_bounded_fair_sweep_revisions_and_read_only_metadata(search_db):
    first, second = asset(search_db), asset(search_db, external_id='B')
    assert reconcile_catalog(search_db, limit=1)['updated'] == 1
    assert search_db.query(FacilityDerivedSummary).count() == 1
    assert reconcile_catalog(search_db, limit=1)['updated'] == 1
    assert search_db.query(FacilityDerivedSummary).count() == 2
    assert reconcile_catalog(search_db)['unchanged'] == 2
    initial = summary_metadata(search_db, first)
    assert initial['revision'] == 1
    first.attributes = {**first.attributes, 'production_output': 20}
    search_db.commit()
    assert summary_metadata(search_db, first)['state'] == 'stale'
    assert not search_db.new and not search_db.dirty
    assert reconcile_catalog(search_db)['updated'] == 1
    updated = summary_metadata(search_db, first)
    assert updated['revision'] == 2
    assert updated['changes'] == ['生产及有效期资料']
    assert summary_metadata(search_db, second)['revision'] == 1


def test_catalog_never_reveals_payload_after_facility_scope_move(search_db):
    row = asset(search_db)
    reconcile_catalog(search_db)
    row.operational_area_id = 2
    search_db.commit()
    metadata = summary_metadata(search_db, row)
    assert metadata['revision'] is None and metadata['updated_at'] is None
    assert 'payload' not in metadata


def test_authenticated_sessions_cannot_run_catalog_worker(query_db):
    with pytest.raises(PermissionError):
        reconcile_catalog(query_db)


def test_facility_api_reads_are_scope_bound_no_writes_and_viewer_allowed(query_db):
    visible = asset(query_db)
    hidden = asset(query_db, area=2, name='不得暴露')
    query_db.get(User, 1).role = 'viewer'
    query_db.commit()
    with client(query_db) as http:
        response = http.get(f'/api/facility-analysis/assets/{visible.id}')
        assert response.status_code == 200, response.text
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['facility']['id'] == visible.id
        assert response.json()['summary']['state'] == 'pending'
        assert http.get(f'/api/facility-analysis/assets/{hidden.id}').status_code == 404
        assert http.get('/api/facility-analysis/region?operational_area_id=2').status_code == 403
        assert http.get('/api/facility-analysis/region?sql=select+1').status_code == 422
        assert http.get('/api/facility-analysis/region?start_date=2026-09-25&end_date=2026-09-24').status_code == 422
        assert http.get('/api/facility-analysis/region?page_size=101').status_code == 422
        assert query_db.query(FacilityDerivedSummary).count() == 0
        assert not query_db.new and not query_db.dirty
        query_db.query(UserAreaScope).filter_by(user_id=1).delete()
        query_db.commit()
        assert http.get(f'/api/facility-analysis/assets/{visible.id}').status_code == 404
    with client(query_db, uid=None) as anonymous:
        assert anonymous.get('/api/facility-analysis/region').status_code == 401


def test_facility_catalog_task_independent_of_agent_lab():
    from app.tasks.facility_summary_tasks import reconcile_facilities
    from app.tasks.celery_app import celery_app
    entry = celery_app.conf.beat_schedule['reconcile-facility-catalog']
    assert entry['task'] == reconcile_facilities.name
    options = {**reconcile_facilities._get_exec_options(), **entry['options']}
    route = celery_app.amqp.router.route(options, reconcile_facilities.name, (), {})
    assert route['queue'].name == celery_app.conf.task_default_queue
    assert reconcile_facilities.time_limit == 60
