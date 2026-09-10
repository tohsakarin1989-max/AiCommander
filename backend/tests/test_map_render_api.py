"""Runtime transport fixtures, not substitutes for package semantic acceptance."""
import hashlib
import copy
import io
from contextlib import closing
import json
import gzip
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from app.config import settings
from app.models.map_foundation import MapPackageArtifact, MapSnapshot, PublicMapBundle
from tests.test_map_style_dependencies import inputs
from tests.test_map_place_api import prepare
from tests.test_offline_maps import client, db_session


MVT = b'\x1a\x0c\x0a\x05place\x28\x80\x20\x78\x02'


def registered(client, db_session, tmp_path, *, tile_content=None, style_update=None, sprites=False):
    old, _ = prepare(client, db_session, tmp_path, index=False)
    old_row = db_session.get(MapSnapshot, old['id'])
    old_row.status = 'superseded'
    incoming = tmp_path / 'render-input'
    incoming.mkdir()
    style, manifest = inputs(incoming)
    sprite_contents = {}
    if sprites:
        from PIL import Image

        template = next(a for a in manifest['assets'] if a['role'] == 'sprite')
        manifest['assets'] = [a for a in manifest['assets'] if a['role'] != 'sprite']
        for scale in (1, 2):
            base = 'sprite' if scale == 1 else 'sprite-2x'
            buffer = io.BytesIO()
            Image.new('RGBA', (scale, scale), (255, 255, 255, 255)).save(buffer, format='PNG')
            sprite_contents[f'{base}.png'] = buffer.getvalue()
            sprite_contents[f'{base}.json'] = json.dumps({'dot': {
                'x': 0, 'y': 0, 'width': scale, 'height': scale, 'pixelRatio': scale}}).encode()
            for extension in ('png', 'json'):
                manifest['assets'].append({**copy.deepcopy(template), 'name': f'{base}.{extension}'})
        style['sprite'] = 'aic-map://sprite'
        style['layers'][0]['layout']['icon-image'] = 'dot'
    if style_update:
        style_update(style)
    database = incoming / 'vector.mbtiles'
    with closing(sqlite3.connect(database)) as connection:
        connection.execute('CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)')
        connection.execute('INSERT INTO tiles VALUES (6, 54, 42, ?)',
                           (gzip.compress(MVT) if tile_content is None else tile_content,))
        connection.commit()
    contents = {}
    for index, asset in enumerate(manifest['assets']):
        content = json.dumps(style).encode() if asset['role'] == 'style' else b'fixture'
        if asset['role'] == 'vector':
            content = database.read_bytes()
        if asset['name'] in sprite_contents:
            content = sprite_contents[asset['name']]
        digest = hashlib.sha256(content).hexdigest()
        asset.update(size_bytes=len(content), sha256=digest,
                     chunks=[{'file': f'render-{index}.part', 'size_bytes': len(content), 'sha256': digest}])
        contents[asset['name']] = content
    digest = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                      separators=(',', ':')).encode()).hexdigest()
    bundle = PublicMapBundle(bundle_id=manifest['bundle_id'], provider=manifest['provider'],
        source_version=manifest['source_version'], license_record=manifest['license'],
        bounds=manifest['bounds'], manifest=manifest, package_hash=digest, status='accepted')
    db_session.add(bundle)
    db_session.flush()
    for asset in manifest['assets']:
        key = f"bundles/{digest}/assets/{asset['name']}"
        if asset['role'] == 'glyphs':
            key = f"bundles/{digest}/glyphs/noto-sans-cjk-sc-regular/{asset['name'][7:]}"
        path = Path(settings.MAP_PACKAGE_ROOT) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents[asset['name']])
        record = MapPackageArtifact(public_bundle_id=bundle.id, storage_key=key,
            artifact_kind='mbtiles' if asset['role'] == 'vector' else asset['role'],
            size_bytes=asset['size_bytes'], sha256=asset['sha256'])
        db_session.add(record)
        if asset['role'] == 'style':
            style_path, style_record = path, record
    snapshot = MapSnapshot(id=str(uuid4()), version='render-fixture',
        operational_area_id=old_row.operational_area_id, public_bundle_id=bundle.id,
        status='current', manifest={'bounds': manifest['bounds']}, feature_watermark='fixture')
    db_session.add(snapshot)
    db_session.commit()
    return snapshot, bundle, style_path, style_record


def test_style_is_bound_to_authorized_snapshot(client, db_session, tmp_path):
    snapshot, _, _, _ = registered(client, db_session, tmp_path)
    response = client.get('/api/maps/current/style.json')
    assert response.status_code == 200, response.text
    style = response.json()
    assert style['sources']['public']['tiles'] == [f'/api/maps/tiles/{snapshot.id}/{{z}}/{{x}}/{{y}}']
    assert style['glyphs'] == f'/api/maps/{snapshot.id}/glyphs/{{fontstack}}/{{range}}.pbf'
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    db_session.info['authorized_area_ids'] = []
    assert client.get(f'/api/maps/{snapshot.id}/style.json').status_code == 404


def test_schema2_manifest_matches_frontend_contract(client, db_session, tmp_path):
    snapshot, _, _, _ = registered(client, db_session, tmp_path)
    response = client.get('/api/maps/current/manifest')
    assert response.status_code == 200
    value = response.json()
    assert value['schema_version'] == '2.0'
    assert value['renderer'] == 'maplibre'
    assert value['style_url'] == f'/api/maps/{snapshot.id}/style.json'
    assert value['display_max_zoom'] == 19


def test_build_persists_vector_renderer_contract(client, db_session, tmp_path):
    snapshot, bundle, _, _ = registered(client, db_session, tmp_path)
    response = client.post('/api/map-snapshots/build', json={
        'operational_area_id': snapshot.operational_area_id, 'public_bundle_id': bundle.id})
    assert response.status_code == 201, response.text
    built = db_session.get(MapSnapshot, response.json()['id'])
    assert built.manifest['schema_version'] == '2.0'
    assert built.manifest['renderer'] == 'maplibre'
    assert built.manifest['style_url'] == f'/api/maps/{built.id}/style.json'


@pytest.mark.parametrize('damage', ['missing', 'hash', 'registration', 'size', 'symlink',
                                  'parent_symlink', 'manifest', 'not_accepted'])
def test_corrupt_style_is_unavailable(client, db_session, tmp_path, damage):
    _, bundle, path, record = registered(client, db_session, tmp_path)
    if damage == 'missing':
        path.unlink()
    elif damage == 'hash':
        path.write_bytes(b'x' * record.size_bytes)
    elif damage == 'registration':
        record.sha256 = '0' * 64
    elif damage == 'size':
        record.size_bytes = 2 * 1024 * 1024
    elif damage == 'symlink':
        path.unlink()
        path.symlink_to(tmp_path / 'secret')
    elif damage == 'parent_symlink':
        parent = path.parent
        moved = parent.with_name('moved')
        parent.rename(moved)
        parent.symlink_to(moved, target_is_directory=True)
    elif damage == 'manifest':
        bundle.manifest = {**bundle.manifest, 'source_version': 'tampered'}
    else:
        bundle.status = 'staging'
    db_session.commit()
    response = client.get('/api/maps/current/style.json')
    assert response.status_code == 503, response.text
    assert str(tmp_path) not in response.text


def test_legacy_map_does_not_advertise_vector_style(client, db_session, tmp_path):
    prepare(client, db_session, tmp_path, index=False)
    response = client.get('/api/maps/current/style.json')
    assert response.status_code == 404
    assert 'style_url' not in client.get('/api/maps/current/manifest').json()


def test_unknown_snapshot_style(client, db_session):
    assert client.get(f'/api/maps/{uuid4()}/style.json').status_code == 404


@pytest.mark.parametrize('compressed', [True, False])
def test_vector_tile_content_type_and_tms(client, db_session, tmp_path, compressed):
    snapshot, _, _, _ = registered(client, db_session, tmp_path,
                                   tile_content=gzip.compress(MVT) if compressed else MVT)
    response = client.get(f'/api/maps/tiles/{snapshot.id}/6/54/21')
    assert response.status_code == 200
    assert response.content == MVT
    assert response.headers['content-type'] == 'application/vnd.mapbox-vector-tile'
    assert response.headers['cache-control'] == 'private, no-store'
    missing = client.get(f'/api/maps/tiles/{snapshot.id}/6/54/22?blank_missing=true')
    assert missing.status_code == 404
    assert 'image/gif' not in missing.headers.get('content-type', '')
    db_session.info['authorized_area_ids'] = []
    assert client.get(f'/api/maps/tiles/{snapshot.id}/6/54/21').status_code == 404


@pytest.mark.parametrize('content', [b'\x1f\x8bgarbage', gzip.compress(MVT)[:-3],
    gzip.compress(MVT) + b'extra', gzip.compress(b'x' * (8 * 1024 * 1024 + 1)),
    b'x' * (2 * 1024 * 1024 + 1)], ids=['bad_gzip', 'truncated', 'trailing', 'zip_bomb', 'oversized'])
def test_vector_transport_rejects_corrupt_or_oversized_payload(client, db_session, tmp_path, content):
    snapshot, _, _, _ = registered(client, db_session, tmp_path, tile_content=content)
    response = client.get(f'/api/maps/tiles/{snapshot.id}/6/54/21')
    assert response.status_code == 503
    assert str(tmp_path) not in response.text


def test_registered_sprite_variants_are_bound_and_checked(client, db_session, tmp_path):
    snapshot, _, _, _ = registered(client, db_session, tmp_path, sprites=True)
    assert client.get('/api/maps/current/style.json').json()['sprite'] == f'/api/maps/{snapshot.id}/sprite'
    for suffix in ('.json', '@2x.json', '.png', '@2x.png'):
        response = client.get(f'/api/maps/{snapshot.id}/sprite{suffix}')
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'private, no-store'
        if suffix.endswith('.png'):
            assert response.content.startswith(b'\x89PNG\r\n\x1a\n')
        else:
            assert 'dot' in response.json()
    assert client.get(f'/api/maps/{snapshot.id}/sprite.exe').status_code == 404
    db_session.info['authorized_area_ids'] = []
    assert client.get(f'/api/maps/{snapshot.id}/sprite.png').status_code == 404


@pytest.mark.parametrize('update', [lambda s: s.update(glyphs='https://external.example/font.pbf'),
    lambda s: s.update(layers=None), lambda s: s.update(imports=[]),
    lambda s: s['sources']['public'].update(tiles=['https://external.example/{z}/{x}/{y}'])],
    ids=['external_font', 'invalid_layers', 'imports', 'external_tiles'])
def test_registered_style_still_rechecks_resource_boundary(client, db_session, tmp_path, update):
    registered(client, db_session, tmp_path, style_update=update)
    assert client.get('/api/maps/current/style.json').status_code == 503


def test_vector_store_hash_cache_rechecks_modified_file(client, db_session, tmp_path):
    snapshot, bundle, _, _ = registered(client, db_session, tmp_path)
    url = f'/api/maps/tiles/{snapshot.id}/6/54/21'
    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 200
    asset = db_session.query(MapPackageArtifact).filter_by(public_bundle_id=bundle.id, artifact_kind='mbtiles').one()
    path = Path(settings.MAP_PACKAGE_ROOT) / asset.storage_key
    path.write_bytes(b'x' * asset.size_bytes)
    assert client.get(url).status_code == 503


@pytest.mark.parametrize('coords', ['23/0/0', '6/64/0', '6/0/-1', '5/0/0'])
def test_vector_invalid_coordinates_never_return_raster_blank(client, db_session, tmp_path, coords):
    snapshot, _, _, _ = registered(client, db_session, tmp_path)
    assert client.get(f'/api/maps/tiles/{snapshot.id}/{coords}?blank_missing=true').status_code == 404


def test_render_endpoints_require_authentication(db_session, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.offline_maps import router
    from app.database import get_db

    monkeypatch.setattr(settings, 'AUTH_REQUIRED', True)
    app = FastAPI()
    app.include_router(router, prefix='/api')
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as anonymous:
        for path in ('/api/maps/current/style.json', '/api/maps/current/sprite.png',
                     '/api/maps/tiles/current/6/54/21'):
            assert anonymous.get(path).status_code == 401


def test_sqlite_reads_private_verified_copy_not_package_namespace(client, db_session, tmp_path, monkeypatch):
    snapshot, bundle, _, _ = registered(client, db_session, tmp_path)
    artifact = db_session.query(MapPackageArtifact).filter_by(public_bundle_id=bundle.id,
                                                             artifact_kind='mbtiles').one()
    source = Path(settings.MAP_PACKAGE_ROOT) / artifact.storage_key
    original_connect = sqlite3.connect
    queried_paths = []

    def replace_package_parent(database, *args, **kwargs):
        queried_paths.append(str(database))
        parent = source.parent
        parent.rename(parent.with_name('original-assets'))
        parent.mkdir()
        source.write_bytes(b'unverified replacement')
        return original_connect(database, *args, **kwargs)

    # Run the race only after the service has verified/read its public bundle.
    monkeypatch.setattr('app.services.map_vector_tile_service.sqlite3.connect', replace_package_parent)
    response = client.get(f'/api/maps/tiles/{snapshot.id}/6/54/21')
    assert response.status_code == 200, response.text
    assert response.content == MVT
    assert len(queried_paths) == 1
    assert '/dev/fd/' not in queried_paths[0]
    assert str(Path(settings.MAP_PACKAGE_ROOT)) not in queried_paths[0]
