"""Snapshot-bound public place lookup; no formal map is changed."""
import hashlib
import sqlite3
from pathlib import Path

import pytest

from app.config import settings
from app.models.map_foundation import MapPackageArtifact
from app.models.map_foundation import MapSnapshot
from app.services.public_place_index import build_index
from tests.test_offline_maps import client, db_session, _default_area, _import_bundle


def prepare(client, db_session, tmp_path, *, index=True):
    area = _default_area(db_session)
    bundle = _import_bundle(client, tmp_path)
    response = client.post('/api/map-snapshots/build', json={
        'operational_area_id': area.id, 'public_bundle_id': bundle['id']})
    assert response.status_code == 201
    snapshot = response.json()
    assert client.post(f"/api/map-snapshots/{snapshot['id']}/publish").status_code == 200
    if not index:
        return snapshot, None
    path = Path(settings.MAP_PACKAGE_ROOT) / 'places.sqlite'
    build_index(path, [{'id': 'n123', 'name': '大庆市', 'kind': 'city',
                        'longitude': 125, 'latitude': 46.5,
                        'location_role': 'name_reference_point'}], {'source_sha256': 'a' * 64})
    artifact = MapPackageArtifact(public_bundle_id=bundle['id'], artifact_kind='gazetteer',
                                  storage_key='places.sqlite', size_bytes=path.stat().st_size,
                                  sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    db_session.add(artifact)
    db_session.commit()
    return snapshot, artifact


def test_search_and_empty_are_versioned(client, db_session, tmp_path):
    snapshot, artifact = prepare(client, db_session, tmp_path)
    response = client.get('/api/maps/current/places', params={'q': '大庆'})
    assert response.status_code == 200
    result = response.json()
    assert result['snapshot_id'] == snapshot['id']
    assert result['index_sha256'] == artifact.sha256
    assert result['items'][0]['id'] == 'n123'
    assert result['location_role'] == 'name_reference_point'
    assert response.headers['cache-control'] == 'private, no-store'
    assert client.get('/api/maps/current/places', params={'q': "%' OR 1=1 --"}).json()['items'] == []


@pytest.mark.parametrize('params', [{'q': '大'}, {'q': '  '}, {'q': '大庆', 'limit': 51}])
def test_invalid_query(client, db_session, tmp_path, params):
    prepare(client, db_session, tmp_path)
    assert client.get('/api/maps/current/places', params=params).status_code == 422


def test_legacy_map_is_not_empty_search(client, db_session, tmp_path):
    prepare(client, db_session, tmp_path, index=False)
    response = client.get('/api/maps/current/places', params={'q': '大庆'})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'place_index_not_configured'


@pytest.mark.parametrize('damage', ['missing', 'checksum', 'path', 'corrupt'])
def test_bad_artifact_is_sanitized(client, db_session, tmp_path, damage):
    _, artifact = prepare(client, db_session, tmp_path)
    path = Path(settings.MAP_PACKAGE_ROOT) / artifact.storage_key
    if damage == 'missing':
        path.unlink()
    elif damage == 'checksum':
        artifact.sha256 = '0' * 64
    elif damage == 'path':
        artifact.storage_key = '../secret.sqlite'
    else:
        path.write_bytes(b'broken database')
        artifact.size_bytes = path.stat().st_size
        artifact.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    db_session.commit()
    response = client.get('/api/maps/current/places', params={'q': '大庆'})
    assert response.status_code == 503
    assert str(tmp_path) not in response.text
    assert 'secret' not in response.text


def test_scope_is_checked_before_artifact_access(client, db_session, tmp_path, monkeypatch):
    snapshot, _ = prepare(client, db_session, tmp_path)
    db_session.info['authorized_area_ids'] = []
    for ref in ('current', snapshot['id']):
        assert client.get(f'/api/maps/{ref}/places', params={'q': '大庆'}).status_code == 404


def test_auth_required_without_principal(db_session, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.offline_maps import router
    from app.database import get_db

    monkeypatch.setattr(settings, 'AUTH_REQUIRED', True)
    app = FastAPI()
    app.include_router(router, prefix='/api')
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as unauthenticated:
        assert unauthenticated.get('/api/maps/current/places', params={'q': '大庆'}).status_code == 401


def test_historical_index_does_not_follow_current_bundle(client, db_session, tmp_path):
    old, _ = prepare(client, db_session, tmp_path)
    old_row = db_session.get(MapSnapshot, old['id'])
    old_row.status = 'superseded'
    db_session.commit()
    bundle = _import_bundle(client, tmp_path, bundle_id='different-public-map')
    response = client.post('/api/map-snapshots/build', json={
        'operational_area_id': old_row.operational_area_id, 'public_bundle_id': bundle['id']})
    assert response.status_code == 201
    assert client.post(f"/api/map-snapshots/{response.json()['id']}/publish").status_code == 200
    assert client.get('/api/maps/current/places', params={'q': '大庆'}).status_code == 409
    assert client.get(f"/api/maps/{old['id']}/places", params={'q': '大庆'}).json()['items'][0]['id'] == 'n123'
    db_session.info['authorized_area_ids'] = []
    assert client.get(f"/api/maps/{old['id']}/places", params={'q': '大庆'}).status_code == 404


def test_ambiguous_index_is_not_selected_arbitrarily(client, db_session, tmp_path):
    _, artifact = prepare(client, db_session, tmp_path)
    db_session.add(MapPackageArtifact(public_bundle_id=artifact.public_bundle_id,
        artifact_kind='gazetteer', storage_key='another.sqlite', sha256=artifact.sha256,
        size_bytes=artifact.size_bytes))
    db_session.commit()
    assert client.get('/api/maps/current/places', params={'q': '大庆'}).status_code == 503


def test_extension_columns_are_not_exposed(client, db_session, tmp_path):
    _, artifact = prepare(client, db_session, tmp_path)
    path = Path(settings.MAP_PACKAGE_ROOT) / artifact.storage_key
    connection = sqlite3.connect(path)
    try:
        connection.execute('ALTER TABLE places ADD COLUMN internal_build_path TEXT')
        connection.execute("UPDATE places SET internal_build_path='/private/build' ")
        connection.commit()
    finally:
        connection.close()
    artifact.size_bytes = path.stat().st_size
    artifact.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    db_session.commit()
    response = client.get('/api/maps/current/places', params={'q': '大庆'})
    assert response.status_code == 200
    assert 'internal_build_path' not in response.text
    assert '/private/build' not in response.text
