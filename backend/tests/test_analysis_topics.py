from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.analysis_topics import router
from app.database import get_db
from app.models.analysis_topic import AnalysisTopic, TopicSnapshot
from app.models.event import Event
from app.models.map_foundation import UserAreaScope
from app.models.user import User
from app.services import analysis_topic_service as topics
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_case_search_page import add_case
from tests.test_query_profiles import profile


def client_for(db, uid=1):
    app = FastAPI()
    @app.middleware('http')
    async def auth(request, call_next):
        if uid is not None:
            request.state.principal = SimpleNamespace(user_id=uid, role='analyst')
        return await call_next(request)
    def session():
        yield db
    app.dependency_overrides[get_db] = session
    app.include_router(router, prefix='/api/analysis-topics')
    return TestClient(app)


def seed(db):
    case = add_case(db, 'TOPIC-CASE', description='井场发现软管。')
    profile(db, case)
    return case


def test_api_create_read_refresh_and_pause_are_separate(query_db):
    seed(query_db)
    with client_for(query_db) as client:
        response = client.post('/api/analysis-topics', json={'title': '井场专题',
            'filters': {'conditions': [{'category': 'place_condition', 'value': '井场'}]}})
        assert response.status_code == 201 and response.headers['cache-control'] == 'no-store'
        url = response.headers['location']
        topic_id = response.json()['id']
        assert client.get(url).json()['snapshot'] is None
        assert query_db.query(TopicSnapshot).count() == 0
        assert topics.process_next_topic(query_db)['status'] == 'updated'
        first = client.get(url).json()
        assert first['snapshot']['aggregate']['total'] == 1
        assert first['snapshot']['revision'] == 1
        assert client.get(url).json() == first
        assert query_db.query(TopicSnapshot).count() == 1
        assert not query_db.dirty and not query_db.new
        assert client.post(url + '/refresh').status_code == 202
        assert topics.process_next_topic(query_db)['status'] == 'unchanged'
        assert query_db.query(TopicSnapshot).count() == 1
        assert client.patch(url, json={'paused': True}).json()['paused'] is True
        assert client.post(url + '/refresh').status_code == 409
        assert topics.refresh_topic(query_db, topic_id)['status'] == 'not_claimed'
        assert topics.process_next_topic(query_db) is None
        assert client.patch(url, json={'paused': False, 'notes': '保留未知'}).json()['refresh_state'] == 'queued'
        assert client.get(url + '/history').json()['total'] == 1
        assert client.get('/api/analysis-topics').json()['total'] == 1


def test_api_owner_grants_roles_and_validation(query_db):
    seed(query_db)
    with client_for(query_db) as client:
        url = client.post('/api/analysis-topics', json={'title': '专题'}).headers['location']
        for body in ({'title': ''}, {'title': '   '}, {'title': '专题', 'sql': 'select 1'},
                     {'title': '专题', 'filters': {'page_size': 999}}):
            assert client.post('/api/analysis-topics', json=body).status_code == 422
        assert client.post('/api/analysis-topics', json={'title': '越权',
            'filters': {'operational_area_id': 2}}).status_code == 403
        assert client.get(url + '?revision=100').status_code == 404
    with client_for(query_db, uid=2) as other:
        assert other.get(url).status_code == 404
        assert other.patch(url, json={'paused': True}).status_code == 404
        assert other.get('/api/analysis-topics').json()['total'] == 0
    with client_for(query_db, uid=None) as anon:
        assert anon.get(url).status_code == 401
    query_db.get(User, 1).role = 'viewer'
    query_db.commit()
    with client_for(query_db) as viewer:
        assert viewer.get(url).status_code == 403


def test_scope_revocation_hides_old_counts_and_pauses_worker(query_db):
    seed(query_db)
    created = topics.create_topic(query_db, '专题', {})
    topics.refresh_topic(query_db, created['id'])
    query_db.query(UserAreaScope).filter_by(user_id=1).delete()
    query_db.commit()
    with pytest.raises(PermissionError):
        topics.read_topic(query_db, created['id'])
    assert topics.list_topics(query_db)['total'] == 0
    query_db.get(AnalysisTopic, created['id']).next_refresh_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    query_db.commit()
    assert topics.process_next_topic(query_db)['status'] == 'access_changed'
    assert query_db.get(AnalysisTopic, created['id']).paused is True


def test_moved_or_deleted_case_does_not_leak_from_history_or_changes(query_db):
    case = seed(query_db)
    created = topics.create_topic(query_db, '专题', {})
    topics.refresh_topic(query_db, created['id'])
    case.operational_area_id = 2
    query_db.commit()
    with pytest.raises(PermissionError):
        topics.read_topic(query_db, created['id'])
    assert topics.refresh_topic(query_db, created['id'])['revision'] == 2
    latest = topics.read_topic(query_db, created['id'])['snapshot']
    assert latest['aggregate']['total'] == 0
    assert latest['changes']['removed_case_ids'] == []
    assert latest['changes']['left_group'] == []
    assert latest['changes']['comparison_state'] == 'restricted'
    with pytest.raises(PermissionError):
        topics.read_topic(query_db, created['id'], revision=1)
    with pytest.raises(PermissionError):
        topics.topic_history(query_db, created['id'])


def test_data_changes_add_revision_and_freeze_old_statistics(query_db):
    seed(query_db)
    created = topics.create_topic(query_db, '专题', {})
    topics.refresh_topic(query_db, created['id'])
    old = topics.read_topic(query_db, created['id'])['snapshot']
    new_case = add_case(query_db, 'NEW', description='未发现软管。')
    profile(query_db, new_case)
    assert topics.refresh_topic(query_db, created['id'])['revision'] == 2
    latest = topics.read_topic(query_db, created['id'])['snapshot']
    assert latest['aggregate']['total'] == 2
    assert latest['changes']['added_case_ids'] == [new_case.id]
    assert latest['content_sha256'] != old['content_sha256']
    assert topics.read_topic(query_db, created['id'], revision=1)['snapshot'] == old


def test_event_source_relation_deduplicates_without_text_deduplication(query_db):
    case = seed(query_db)
    hidden = add_case(query_db, 'HIDDEN', operational_area_id=2)
    for number, related, area in [('one', None, 1), ('same-text', None, 1),
                                 ('linked', case.id, 1), ('restricted', hidden.id, 1),
                                 ('hidden-event', None, 2)]:
        query_db.add(Event(event_number=number, title='同一描述不等于同一来源',
            event_type='other', occurred_time=datetime(2026, 9, 9),
            related_case_id=related, operational_area_id=area))
    query_db.commit()
    created = topics.create_topic(query_db, '专题', {})
    topics.refresh_topic(query_db, created['id'])
    data = topics.read_topic(query_db, created['id'])['snapshot']
    assert data['aggregate']['total'] == 1
    assert data['events']['independent_event_count'] == 2
    assert data['events']['case_linked_event_count'] == 1
    assert 'source_manifest' not in data['events']


def test_worker_recovers_expired_lease_but_does_not_steal_live_work(query_db):
    seed(query_db)
    created = topics.create_topic(query_db, '专题', {})
    row = query_db.get(AnalysisTopic, created['id'])
    row.refresh_state = 'running'
    row.lease_token = 'old-worker'
    row.lease_until = datetime.now(timezone.utc) + timedelta(minutes=1)
    query_db.commit()
    assert topics.process_next_topic(query_db) is None
    assert topics.refresh_topic(query_db, row.id)['status'] == 'not_claimed'
    row.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    query_db.commit()
    assert topics.process_next_topic(query_db)['status'] == 'updated'
    assert row.lease_token is None


def test_resume_obeys_same_active_topic_capacity_as_create(query_db):
    from uuid import uuid4
    created = topics.create_topic(query_db, '暂停的专题', {})
    topics.update_topic(query_db, created['id'], paused=True)
    row = query_db.get(AnalysisTopic, created['id'])
    for index in range(100):
        query_db.add(AnalysisTopic(id=str(uuid4()), created_by=1, title=f'活跃专题{index}',
            filters={}, scope_version=row.scope_version, paused=False, refresh_state='queued'))
    query_db.commit()
    with client_for(query_db) as client:
        response = client.patch(f"/api/analysis-topics/{row.id}", json={'paused': False})
        assert response.status_code == 429
    assert query_db.get(AnalysisTopic, row.id).paused is True


def test_pause_invalidates_late_publication(query_db, monkeypatch):
    seed(query_db)
    created = topics.create_topic(query_db, '专题', {})
    original = topics.build_aggregate
    def paused_during_scan(db, args, **kwargs):
        snapshot = original(db, args, **kwargs)
        topics.update_topic(db, created['id'], paused=True)
        return snapshot
    monkeypatch.setattr(topics, 'build_aggregate', paused_during_scan)
    assert topics.refresh_topic(query_db, created['id'])['status'] == 'superseded'
    assert query_db.query(TopicSnapshot).count() == 0


def test_evidence_resolves_frozen_profile_and_never_arbitrary_case(query_db):
    case = seed(query_db)
    created = topics.create_topic(query_db, '专题', {'keyword': 'TOPIC-CASE'})
    topics.refresh_topic(query_db, created['id'])
    case.description = '后续修改原文，不再描述软管。'
    query_db.commit()
    # The old profile is an immutable version, so its original quote remains citable.
    evidence = topics.read_topic_evidence(query_db, created['id'], case.id, revision=1)
    assert any(row['reference']['quote'] == '井场发现软管' for row in evidence['assertions'])
    assert all('case_profile:' in row['evidence_ref'] for row in evidence['assertions'])
    other = add_case(query_db, 'NOT-IN-TOPIC')
    query_db.commit()
    with client_for(query_db) as client:
        path = f"/api/analysis-topics/{created['id']}/evidence"
        assert client.get(f'{path}/{case.id}?revision=1').status_code == 200
        assert client.get(f'{path}/{other.id}?revision=1').status_code == 404
        assert client.get(f'{path}/{case.id}?revision=99').status_code == 404
        assert client.get(f'{path}/{case.id}').status_code == 422


def test_incomplete_refresh_retains_last_successful_snapshot(query_db, monkeypatch):
    seed(query_db)
    created = topics.create_topic(query_db, '专题', {})
    topics.refresh_topic(query_db, created['id'])
    old = topics.read_topic(query_db, created['id'])['snapshot']
    original = topics.build_aggregate
    def incomplete(db, args, **kwargs):
        result = original(db, args, **kwargs)
        result['coverage']['complete'] = False
        return result
    monkeypatch.setattr(topics, 'build_aggregate', incomplete)
    with pytest.raises(ValueError, match='scan_incomplete'):
        topics.refresh_topic(query_db, created['id'])
    read = topics.read_topic(query_db, created['id'])
    assert read['refresh_state'] == 'failed'
    assert read['snapshot'] == old
