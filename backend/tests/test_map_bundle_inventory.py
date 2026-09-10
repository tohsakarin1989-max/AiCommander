"""Inventory checks are separate from the importer's semantic acceptance."""
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.config import settings
from app.models.map_foundation import MapPackageArtifact, MapSnapshot, PublicMapBundle
from app.services.map_bundle_inventory import verify_bundle_inventory
from tests.test_offline_maps import client, db_session
from tests.test_map_package_set import package


def inventory(db_session, tmp_path, *, root=None, vector_bytes=None, glyph_span='0-255', font_profile=None):
    incoming = tmp_path / 'incoming'
    incoming.mkdir()
    manifest = package(incoming)
    if font_profile is not None:
        manifest['font_profile'] = font_profile
    if vector_bytes is not None:
        vector = next(a for a in manifest['assets'] if a['role'] == 'vector')
        vector['size_bytes'] = len(vector_bytes)
        vector['sha256'] = hashlib.sha256(vector_bytes).hexdigest()
        for chunk, content in zip(vector['chunks'], (vector_bytes[:5], vector_bytes[5:])):
            (incoming / chunk['file']).write_bytes(content)
            chunk.update(size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    glyph = next(a for a in manifest['assets'] if a['role'] == 'glyphs')
    glyph['name'] = f'glyphs-{glyph_span}.pbf'
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    bundle = PublicMapBundle(bundle_id=manifest['bundle_id'], provider=manifest['provider'],
        source_version=manifest['source_version'], license_record=manifest['license'],
        bounds=manifest['bounds'], manifest=manifest, package_hash=digest, status='accepted')
    db_session.add(bundle)
    db_session.flush()
    root = root or tmp_path / 'storage'
    artifacts = []
    for asset in manifest['assets']:
        key = f"bundles/{digest}/assets/{asset['name']}"
        if asset['role'] == 'glyphs':
            slug = 'cjk-mongolian-emoji-v1' if font_profile == 'cjk-mongolian-emoji-v1' else 'noto-sans-cjk-sc-regular'
            key = f'bundles/{digest}/glyphs/{slug}/{glyph_span}.pbf'
        target = root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b''.join((incoming / c['file']).read_bytes() for c in asset['chunks']))
        artifact = MapPackageArtifact(public_bundle_id=bundle.id, storage_key=key,
            artifact_kind='mbtiles' if asset['role'] == 'vector' else asset['role'],
            size_bytes=asset['size_bytes'], sha256=asset['sha256'])
        db_session.add(artifact)
        artifacts.append(artifact)
    db_session.commit()
    return bundle, root, artifacts


def test_inventory_is_bound_to_manifest_and_all_files(db_session, tmp_path):
    bundle, root, artifacts = inventory(db_session, tmp_path)
    assert verify_bundle_inventory(db_session, bundle, root, verify_hash=True)
    assert len(artifacts) == 7


def test_composite_inventory_cannot_use_legacy_font_directory(db_session, tmp_path):
    bundle, root, artifacts = inventory(db_session, tmp_path, font_profile='cjk-mongolian-emoji-v1')
    assert verify_bundle_inventory(db_session, bundle, root, verify_hash=True)
    item = next(a for a in artifacts if a.artifact_kind == 'glyphs')
    old_path = root / item.storage_key
    item.storage_key = item.storage_key.replace('cjk-mongolian-emoji-v1', 'noto-sans-cjk-sc-regular')
    new_path = root / item.storage_key
    new_path.parent.mkdir(parents=True)
    old_path.rename(new_path)
    db_session.commit()
    assert not verify_bundle_inventory(db_session, bundle, root, verify_hash=True)


def test_supplementary_glyph_inventory_hash_is_checked(db_session, tmp_path):
    bundle, root, artifacts = inventory(db_session, tmp_path, glyph_span='127744-127999')
    assert verify_bundle_inventory(db_session, bundle, root, verify_hash=True)
    glyph = next(a for a in artifacts if a.artifact_kind == 'glyphs')
    (root / glyph.storage_key).write_bytes(b'x' * glyph.size_bytes)
    assert not verify_bundle_inventory(db_session, bundle, root, verify_hash=True)


@pytest.mark.parametrize('damage', ['missing', 'bytes', 'hash', 'size', 'wrong_bundle',
    'extra', 'kind', 'path', 'symlink', 'manifest', 'not_accepted'])
def test_any_mismatch_rejects_whole_inventory(db_session, tmp_path, damage):
    bundle, root, artifacts = inventory(db_session, tmp_path)
    item = artifacts[-1]
    path = root / item.storage_key
    if damage == 'missing':
        path.unlink()
    elif damage == 'bytes':
        path.write_bytes(b'x' * item.size_bytes)
    elif damage == 'hash':
        item.sha256 = '0' * 64
    elif damage == 'size':
        item.size_bytes += 1
    elif damage == 'wrong_bundle':
        item.public_bundle_id = None
    elif damage == 'extra':
        db_session.add(MapPackageArtifact(public_bundle_id=bundle.id, storage_key='unexpected',
            artifact_kind='style', sha256='a' * 64, size_bytes=1))
    elif damage == 'kind':
        item.artifact_kind = 'style'
    elif damage == 'path':
        item.storage_key = '../outside'
    elif damage == 'symlink':
        path.unlink()
        path.symlink_to(root / artifacts[0].storage_key)
    elif damage == 'not_accepted':
        bundle.status = 'staging'
    else:
        bundle.manifest = {**bundle.manifest, 'source_version': 'tampered'}
    db_session.commit()
    assert not verify_bundle_inventory(db_session, bundle, root, verify_hash=True)


def test_metadata_probe_is_not_a_hash_validation(db_session, tmp_path):
    bundle, root, artifacts = inventory(db_session, tmp_path)
    item = artifacts[-1]
    (root / item.storage_key).write_bytes(b'x' * item.size_bytes)
    assert verify_bundle_inventory(db_session, bundle, root, verify_hash=False)
    assert not verify_bundle_inventory(db_session, bundle, root, verify_hash=True)


def test_parent_directory_symlink_is_rejected(db_session, tmp_path):
    bundle, root, artifacts = inventory(db_session, tmp_path)
    directory = (root / artifacts[0].storage_key).parent
    moved = root / 'moved-assets'
    directory.rename(moved)
    directory.symlink_to(moved, target_is_directory=True)
    assert not verify_bundle_inventory(db_session, bundle, root, verify_hash=True)


def test_publication_and_rollback_check_all_assets(client, db_session, tmp_path):
    from tests.test_map_place_api import prepare

    old, _ = prepare(client, db_session, tmp_path, index=False)
    old_row = db_session.get(MapSnapshot, old['id'])
    bundle, root, artifacts = inventory(db_session, tmp_path, root=Path(settings.MAP_PACKAGE_ROOT))
    # The importer is not under test: inject a ready snapshot and accepted
    # transport fixtures to exercise only atomic publication inventory gates.
    candidate = MapSnapshot(id=str(uuid4()), version='inventory-candidate', status='ready',
        operational_area_id=old_row.operational_area_id, public_bundle_id=bundle.id,
        manifest={}, feature_watermark='fixture')
    db_session.add(candidate)
    db_session.commit()
    glyph = next(a for a in artifacts if a.artifact_kind == 'glyphs')
    glyph_path = root / glyph.storage_key
    original = glyph_path.read_bytes()
    glyph_path.write_bytes(b'x' * len(original))
    assert client.post(f'/api/map-snapshots/{candidate.id}/publish').status_code == 503
    db_session.expire_all()
    assert old_row.status == 'current'
    assert candidate.status == 'ready'
    glyph_path.write_bytes(original)
    assert client.post(f'/api/map-snapshots/{candidate.id}/publish').status_code == 200
    assert client.post(f"/api/map-snapshots/{old['id']}/rollback").status_code == 200
    glyph_path.unlink()
    assert client.post(f'/api/map-snapshots/{candidate.id}/rollback').status_code == 503
    db_session.expire_all()
    assert old_row.status == 'current'
    assert candidate.status == 'superseded'


def test_build_rejects_damaged_companion_even_with_readable_mbtiles(client, db_session, tmp_path):
    from tests.test_offline_maps import _default_area, _mbtiles_bytes

    area = _default_area(db_session)
    bundle, root, artifacts = inventory(db_session, tmp_path,
        root=Path(settings.MAP_PACKAGE_ROOT), vector_bytes=_mbtiles_bytes(tmp_path))
    companion = next(a for a in artifacts if a.artifact_kind == 'style')
    (root / companion.storage_key).unlink()
    response = client.post('/api/map-snapshots/build', json={
        'operational_area_id': area.id, 'public_bundle_id': bundle.id})
    assert response.status_code == 503
    assert db_session.query(MapSnapshot).count() == 0


@pytest.mark.parametrize('version', ['1.0', '2.1', None])
def test_schema_change_cannot_fall_back_to_legacy_validation(client, db_session, tmp_path, version):
    from app.services.offline_map_service import OfflineMapService
    from tests.test_offline_maps import _default_area, _mbtiles_bytes

    area = _default_area(db_session)
    bundle, root, artifacts = inventory(db_session, tmp_path,
        root=Path(settings.MAP_PACKAGE_ROOT), vector_bytes=_mbtiles_bytes(tmp_path))
    glyph = next(a for a in artifacts if a.artifact_kind == 'glyphs')
    (root / glyph.storage_key).unlink()
    candidate = MapSnapshot(id=str(uuid4()), version='downgrade-fixture', status='ready',
        operational_area_id=area.id, public_bundle_id=bundle.id,
        manifest={}, feature_watermark='fixture')
    db_session.add(candidate)
    bundle.manifest = {**bundle.manifest, 'schema_version': version}
    db_session.commit()
    assert not OfflineMapService._snapshot_artifact_exists(db_session, candidate, verify_hash=True)
    response = client.post('/api/map-snapshots/build', json={
        'operational_area_id': area.id, 'public_bundle_id': bundle.id})
    assert response.status_code == 503
