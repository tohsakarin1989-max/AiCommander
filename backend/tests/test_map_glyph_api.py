"""Registered glyph transport with snapshot authorization and integrity checks."""
import hashlib
import json
from pathlib import Path

import pytest

from app.config import settings
from app.models.map_foundation import MapPackageArtifact, MapSnapshot, PublicMapBundle
from tests.test_map_place_api import prepare
from tests.test_offline_maps import client, db_session


URL = '/api/maps/current/glyphs/Noto Sans CJK SC Regular/0-255.pbf'
COMPOSITE = 'Noto Sans CJK SC Regular,Noto Sans Mongolian Regular,Noto Emoji Regular'


def register_composite(client, db_session, tmp_path, *, embedded_font=COMPOSITE):
    from tests.test_map_bundle_inventory import inventory
    from tests.test_map_glyph_validation import stack, glyph

    snapshot, _ = prepare(client, db_session, tmp_path, index=False)
    incoming = tmp_path / 'composite'
    incoming.mkdir()
    bundle, root, artifacts = inventory(db_session, incoming,
        root=Path(settings.MAP_PACKAGE_ROOT), glyph_span='127744-127999',
        font_profile='cjk-mongolian-emoji-v1')
    artifact = next(a for a in artifacts if a.artifact_kind == 'glyphs')
    content = stack([glyph(code=127973)], name=embedded_font.encode(), span=b'127744-127999')
    manifest = json.loads(json.dumps(bundle.manifest))
    asset = next(a for a in manifest['assets'] if a['role'] == 'glyphs')
    digest = hashlib.sha256(content).hexdigest()
    asset.update(size_bytes=len(content), sha256=digest,
                 chunks=[{'file': 'composite.part', 'size_bytes': len(content), 'sha256': digest}])
    old_hash = bundle.package_hash
    bundle.manifest = manifest
    bundle.package_hash = hashlib.sha256(json.dumps(manifest, ensure_ascii=False,
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    for item in artifacts:
        old_path = root / item.storage_key
        item.storage_key = item.storage_key.replace(old_hash, bundle.package_hash)
        new_path = root / item.storage_key
        new_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.rename(new_path)
    (root / artifact.storage_key).write_bytes(content)
    artifact.sha256, artifact.size_bytes = digest, len(content)
    db_session.get(MapSnapshot, snapshot['id']).public_bundle_id = bundle.id
    db_session.commit()
    return bundle, content


def test_composite_transport_checks_font_identity_and_current_scope(client, db_session, tmp_path):
    _, content = register_composite(client, db_session, tmp_path)
    url = URL.replace('Noto Sans CJK SC Regular', COMPOSITE).replace('0-255', '127744-127999')
    response = client.get(url)
    assert response.status_code == 200
    assert response.content == content
    assert client.get(url.replace(COMPOSITE, 'Noto Sans CJK SC Regular')).status_code == 404
    db_session.info['authorized_area_ids'] = []
    assert client.get(url).status_code == 404


def test_composite_transport_rejects_hash_correct_wrong_embedded_font(client, db_session, tmp_path):
    register_composite(client, db_session, tmp_path, embedded_font='Noto Sans CJK SC Regular')
    url = URL.replace('Noto Sans CJK SC Regular', COMPOSITE).replace('0-255', '127744-127999')
    assert client.get(url).status_code == 503


def test_changed_profile_invalidates_registered_identity(client, db_session, tmp_path):
    bundle, _ = register_composite(client, db_session, tmp_path)
    bundle.manifest = {**bundle.manifest, 'font_profile': 'cjk-v1'}
    db_session.commit()
    assert client.get(URL).status_code == 503


def test_composite_artifact_cannot_override_manifest_checksum(client, db_session, tmp_path):
    from tests.test_map_glyph_validation import stack, glyph
    bundle, _ = register_composite(client, db_session, tmp_path)
    artifact = db_session.query(MapPackageArtifact).filter_by(
        public_bundle_id=bundle.id, artifact_kind='glyphs').one()
    replacement = stack([glyph(code=127969)], name=COMPOSITE.encode(), span=b'127744-127999')
    (Path(settings.MAP_PACKAGE_ROOT) / artifact.storage_key).write_bytes(replacement)
    artifact.sha256 = hashlib.sha256(replacement).hexdigest()
    artifact.size_bytes = len(replacement)
    db_session.commit()
    url = URL.replace('Noto Sans CJK SC Regular', COMPOSITE).replace('0-255', '127744-127999')
    assert client.get(url).status_code == 503


def test_composite_artifact_outside_manifest_cannot_be_served(client, db_session, tmp_path):
    from tests.test_map_glyph_validation import stack, glyph
    bundle, _ = register_composite(client, db_session, tmp_path)
    content = stack([glyph(code=65536)], name=COMPOSITE.encode(), span=b'65536-65791')
    key = f'bundles/{bundle.package_hash}/glyphs/cjk-mongolian-emoji-v1/65536-65791.pbf'
    (Path(settings.MAP_PACKAGE_ROOT) / key).write_bytes(content)
    db_session.add(MapPackageArtifact(public_bundle_id=bundle.id, artifact_kind='glyphs',
        storage_key=key, sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content)))
    db_session.commit()
    url = URL.replace('Noto Sans CJK SC Regular', COMPOSITE).replace('0-255', '65536-65791')
    assert client.get(url).status_code == 404


def register(client, db_session, tmp_path, span='0-255'):
    snapshot, _ = prepare(client, db_session, tmp_path, index=False)
    row = db_session.get(MapSnapshot, snapshot['id'])
    bundle = db_session.get(PublicMapBundle, row.public_bundle_id)
    key = f'bundles/{bundle.package_hash}/glyphs/noto-sans-cjk-sc-regular/{span}.pbf'
    path = Path(settings.MAP_PACKAGE_ROOT) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    content = b'\x0a\x00'  # Transport fixture only, not glyph semantic validation.
    path.write_bytes(content)
    artifact = MapPackageArtifact(public_bundle_id=bundle.id, artifact_kind='glyphs',
        storage_key=key, size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    db_session.add(artifact)
    db_session.commit()
    return snapshot, artifact, path, content


def test_registered_bytes_and_revoked_scope(client, db_session, tmp_path):
    snapshot, _, _, content = register(client, db_session, tmp_path)
    response = client.get(URL)
    assert response.status_code == 200
    assert response.content == content
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['content-type'] == 'application/x-protobuf'
    db_session.info['authorized_area_ids'] = []
    assert client.get(URL).status_code == 404
    assert client.get(URL.replace('current', snapshot['id'])).status_code == 404


@pytest.mark.parametrize('value', ['1-256', '0-256', '00-255', '1114112-1114367', '-1-254'])
def test_invalid_range(client, db_session, tmp_path, value):
    register(client, db_session, tmp_path)
    assert client.get(URL.replace('0-255', value)).status_code == 422


def test_registered_supplementary_range_retains_scope(client, db_session, tmp_path):
    _, _, _, content = register(client, db_session, tmp_path, '127744-127999')
    url = URL.replace('0-255', '127744-127999')
    assert client.get(url).content == content
    assert client.get(url).status_code == 200
    assert client.get(URL.replace('0-255', '65536-65791')).status_code == 404
    db_session.info['authorized_area_ids'] = []
    assert client.get(url).status_code == 404


@pytest.mark.parametrize('damage', ['missing', 'hash', 'size', 'symlink', 'directory'])
def test_corrupt_asset_fails_closed(client, db_session, tmp_path, damage):
    _, artifact, path, _ = register(client, db_session, tmp_path)
    if damage == 'hash':
        artifact.sha256 = '0' * 64
    elif damage == 'size':
        artifact.size_bytes = 3 * 1024 * 1024
    else:
        path.unlink()
        if damage == 'symlink':
            path.symlink_to(tmp_path / 'unavailable-secret')
        elif damage == 'directory':
            path.mkdir()
    db_session.commit()
    response = client.get(URL)
    assert response.status_code == 503
    assert str(tmp_path) not in response.text


def test_unregistered_font_or_range(client, db_session, tmp_path):
    register(client, db_session, tmp_path)
    assert client.get(URL.replace('Regular', 'Bold')).status_code == 404
    assert client.get(URL.replace('0-255', '256-511')).status_code == 404


def test_unauthenticated_request_is_denied(db_session, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.offline_maps import router
    from app.database import get_db

    monkeypatch.setattr(settings, 'AUTH_REQUIRED', True)
    app = FastAPI()
    app.include_router(router, prefix='/api')
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as anonymous:
        assert anonymous.get(URL).status_code == 401


def test_historical_glyph_remains_bound_to_original_bundle(client, db_session, tmp_path):
    from tests.test_offline_maps import _import_bundle

    old, _, _, content = register(client, db_session, tmp_path)
    row = db_session.get(MapSnapshot, old['id'])
    row.status = 'superseded'
    db_session.commit()
    bundle = _import_bundle(client, tmp_path, bundle_id='second-glyph-map')
    response = client.post('/api/map-snapshots/build', json={
        'operational_area_id': row.operational_area_id, 'public_bundle_id': bundle['id']})
    assert response.status_code == 201
    assert client.post(f"/api/map-snapshots/{response.json()['id']}/publish").status_code == 200
    assert client.get(URL).status_code == 404
    assert client.get(URL.replace('current', old['id'])).content == content
