from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.map_foundation import router
from app.database import get_db
from app.models.road_public_alias import RoadPublicAlias
from test_map_foundation import db_session, _client  # noqa: F401
from test_internal_road_import import source  # noqa: F401
from test_road_build_inputs import prepared  # noqa: F401
from test_road_public_alias import decision


def test_create_repeat_revoke_and_paginated_history(prepared):
    db, _, batch_id = prepared
    client = _client(db)
    url = '/api/map-sources/1/roads/public-aliases'
    payload = decision(batch_id).model_dump()
    first = client.post(url, json=payload)
    assert first.status_code == 201, first.text
    assert first.headers['cache-control'] == 'no-store'
    assert first.json()['routing_available'] is False
    repeat = client.post(url, json=payload)
    assert repeat.status_code == 200 and repeat.json()['id'] == first.json()['id']
    revoke = {**payload, 'request_key': 'alias-revoke', 'decision': 'revoked', 'previous_id': first.json()['id']}
    assert client.post(url, json=revoke).status_code == 201
    stale = {**payload, 'request_key': 'alias-stale', 'previous_id': first.json()['id']}
    assert client.post(url, json=stale).status_code == 409
    history = f'/api/map-sources/1/roads/imports/{batch_id}/features/road-1/public-aliases'
    page = client.get(history, params={'public_source_sha256': 'a' * 64, 'limit': 1})
    assert page.status_code == 200
    assert page.json()['items'][0]['decision'] == 'revoked'
    second = client.get(history, params={'public_source_sha256': 'a' * 64, 'limit': 1,
                                       'before_id': page.json()['next_before_id']})
    assert second.json()['items'][0]['id'] == first.json()['id']
    assert second.json()['next_before_id'] is None
    assert client.get(history, params={'public_source_sha256': 'b' * 64}).json()['items'] == []


def test_alias_endpoints_reject_role_scope_wrong_source_and_extra_fields(prepared):
    db, _, batch_id = prepared
    payload = decision(batch_id).model_dump()
    url = '/api/map-sources/1/roads/public-aliases'
    assert _client(db, 'analyst').post(url, json=payload).status_code == 403
    client = _client(db)
    assert client.post('/api/map-sources/999/roads/public-aliases', json=payload).status_code == 404
    assert client.post(url, json={**payload, 'ignore_restrictions': True}).status_code == 422
    assert client.post(url, json={**payload, 'osm_way_id': 9007199254740992}).status_code == 422
    db.info['area_access_levels'] = {1: 'read'}
    assert client.post(url, json=payload).status_code == 403
    db.info['authorized_area_ids'] = ()
    assert client.post(url, json=payload).status_code == 404
    assert db.query(RoadPublicAlias).count() == 0


def test_alias_requires_login_even_without_auth_middleware(prepared):
    db, _, batch_id = prepared
    app = FastAPI()
    app.include_router(router, prefix='/api')
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    assert client.post('/api/map-sources/1/roads/public-aliases', json=decision(batch_id).model_dump()).status_code == 401
    assert client.get(f'/api/map-sources/1/roads/imports/{batch_id}/features/road-1/public-aliases',
                      params={'public_source_sha256': 'a' * 64}).status_code == 401
