"""Real vector decoder plus actual glyph and PNG payloads through one entrypoint."""
import hashlib
import gzip
import json
import sqlite3
from contextlib import closing
from pathlib import Path
import sys
import subprocess

import pytest
import mapbox_vector_tile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from app.services.map_render_bundle_validation import validate_render_bundle
from tests.test_map_style_dependencies import inputs
from tests.test_map_glyph_validation import stack, glyph, field
from app.services.public_place_index import build_index
from tests.test_public_place_index import place
from tests.test_map_sprite_validation import png
from test_vector_map_validation import fixture_map


@pytest.fixture
def db_session(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'isolated-map-render-fixture-secret-not-for-deployment')
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    import app.models  # noqa: F401
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def assembled(tmp_path, damage=None, *, composite=False):
    style, manifest = inputs(tmp_path)
    font_name = 'Noto Sans CJK SC Regular'
    if composite:
        manifest['font_profile'] = 'cjk-mongolian-emoji-v1'
        font_name += ',Noto Sans Mongolian Regular,Noto Emoji Regular'
        for layer in style['layers']:
            if layer['type'] == 'symbol':
                layer['layout']['text-font'] = font_name.split(',')
    vector_path = fixture_map(tmp_path)
    if damage == 'vector_label_glyph':
        tile = mapbox_vector_tile.encode({'name': 'place', 'features': [
            {'geometry': 'POINT(12 30)', 'properties': {'name': '桥'}}]})
        with closing(sqlite3.connect(vector_path)) as connection, connection:
            connection.execute('UPDATE tiles SET tile_data=?', (gzip.compress(tile),))
    vector = vector_path.read_bytes()
    reference = b'not part of render validation'
    reference_hash = hashlib.sha256(reference).hexdigest()
    index_path = tmp_path / 'gazetteer.sqlite'
    build_index(index_path, [place()], {'source_sha256': reference_hash,
                                       'region_sha256': reference_hash})
    manifest['bounds'] = [122, 45, 127, 49]
    style['sources']['public']['bounds'] = manifest['bounds']
    if damage == 'layer':
        style['layers'][0]['source-layer'] = 'absent'
    if damage == 'label_only_glyph':
        style['layers'][0]['layout']['text-field'] = '桥'
    if damage == 'style_syntax':
        style['layers'][0]['paint'] = {'text-color': 'not-a-color'}
    template = next(a for a in manifest['assets'] if a['role'] == 'sprite')
    manifest['assets'] = [a for a in manifest['assets'] if a['role'] != 'sprite']
    for name in ('sprite.json', 'sprite.png', 'sprite-2x.json', 'sprite-2x.png'):
        manifest['assets'].append({**template, 'name': name})
    for index, asset in enumerate(manifest['assets']):
        content = reference
        if asset['role'] == 'vector':
            content = vector
        elif asset['role'] == 'style':
            content = json.dumps(style).encode()
        elif asset['role'] == 'glyphs':
            span = asset['name'][7:-4]
            start, end = map(int, span.split('-'))
            codes = [] if damage == 'missing_glyph' else [ord(c) for c in '大庆市' if start <= ord(c) <= end]
            encoded = [glyph(code=c, bitmap=(b'\x01' * 49 if damage == 'transparent_glyph' else b'\xff' * 49)) for c in codes]
            if damage == 'blank_glyph':
                encoded = [b''.join(field(k, v) for k, v in {
                    1: c, 3: 0, 4: 0, 5: 0, 6: 0, 7: 6}.items()) for c in codes]
            name = 'Noto Sans CJK SC Regular' if damage == 'mixed_font' and start == 0 else font_name
            content = stack(encoded, name=name.encode(), span=span.encode())
            if damage == 'glyph' and span == '0-255':
                content = b'not protobuf'
        elif asset['role'] == 'gazetteer':
            content = index_path.read_bytes()
        elif asset['role'] == 'sprite':
            content = b'{}' if asset['name'].endswith('.json') else png((1, 1))
            if damage == 'sprite' and asset['name'] == 'sprite.png':
                content = b'not png'
        digest = hashlib.sha256(content).hexdigest()
        asset.update(sha256=digest, size_bytes=len(content), chunks=[{
            'file': f'part-{index}.part', 'sha256': digest, 'size_bytes': len(content)}])
        (tmp_path / f'asset-{index:04d}.bin').write_bytes(content)
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    return tmp_path


def test_render_bundle_uses_real_decoded_layers(tmp_path):
    report = validate_render_bundle(assembled(tmp_path))
    assert report['status'] == 'render_content_validated'
    assert report['vector']['layers'] == ['place']
    assert report['glyph_ranges'] == 256
    assert report['glyph_count'] == 3
    assert report['places']['place_count'] == 1
    assert report['primary_place_font_coverage_verified'] is True
    assert report['label_codepoint_coverage_verified'] is True
    assert report['text_shaping_verified'] is False
    assert report['style_syntax_verified'] is True
    assert report['style_syntax']['validator'] == '@maplibre/maplibre-gl-style-spec'
    assert report['publish_ready'] is False
    assert report['road_topology_verified'] is False


def test_composite_render_bundle_accepts_only_consistent_font_identity(tmp_path):
    valid = tmp_path / 'valid'
    valid.mkdir()
    report = validate_render_bundle(assembled(valid, composite=True))
    assert report['status'] == 'render_content_validated'
    assert report['glyph_ranges'] == 256
    assert report['publish_ready'] is False
    mixed = tmp_path / 'mixed'
    mixed.mkdir()
    with pytest.raises(ValueError, match='glyph_stack_mismatch'):
        validate_render_bundle(assembled(mixed, 'mixed_font', composite=True))


def test_supplementary_glyph_content_is_not_just_a_manifest_declaration(tmp_path):
    directory = assembled(tmp_path)
    manifest = json.loads((directory / 'manifest.json').read_bytes())
    content = stack([glyph(code=127973)], span=b'127744-127999')
    index = len(manifest['assets'])
    digest = hashlib.sha256(content).hexdigest()
    manifest['assets'].append(dict(name='glyphs-127744-127999.pbf', role='glyphs',
        license='fixture', attribution='fixture', size_bytes=len(content), sha256=digest,
        chunks=[dict(file='extra-glyph.part', size_bytes=len(content), sha256=digest)]))
    (directory / f'asset-{index:04d}.bin').write_bytes(content)
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    report = validate_render_bundle(directory)
    assert report['glyph_ranges'] == 257
    assert report['glyph_count'] == 4
    assert report['publish_ready'] is False
    # A matching hash cannot hide a payload whose embedded range is wrong.
    bad = stack([glyph(code=127973)], span=b'0-255')
    manifest['assets'][-1].update(size_bytes=len(bad), sha256=hashlib.sha256(bad).hexdigest(),
        chunks=[dict(file='extra-glyph.part', size_bytes=len(bad), sha256=hashlib.sha256(bad).hexdigest())])
    (directory / f'asset-{index:04d}.bin').write_bytes(bad)
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='glyph_stack_mismatch'):
        validate_render_bundle(directory)


def test_builder_materializer_and_decoder_preserve_license_assets(tmp_path):
    from app.services.map_package_builder import build_package
    from app.services.map_package_materialize import materialize_package
    from app.services.map_package_set import read_manifest, verify_directory

    original = tmp_path / 'original'
    original.mkdir()
    assembled(original)
    recipe = read_manifest(original)
    for index, asset in enumerate(recipe['assets']):
        asset.pop('chunks')
        asset['path'] = str(original / f'asset-{index:04d}.bin')
    legal = original / 'license.txt'
    legal.write_text('Test license fixture, not a production license.')
    content = legal.read_bytes()
    recipe['assets'].append(dict(name='license.txt', role='license', path=str(legal),
                                size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
                                license='fixture', attribution='fixture'))
    transport = tmp_path / 'transport'
    build_package(recipe, transport)
    manifest = read_manifest(transport)
    assert verify_directory(transport, manifest)['status'] == 'integrity_verified'
    staging = tmp_path / 'staging'
    staging.mkdir()
    output = materialize_package(transport, manifest, staging)
    result = validate_render_bundle(output)
    assert result['status'] == 'render_content_validated'
    assert result['publish_ready'] is False
    assert (output / f"asset-{len(manifest['assets']) - 1:04d}.bin").read_bytes() == content


@pytest.mark.parametrize('damage,reason', [('layer', 'unbundled_style_layer'),
    ('label_only_glyph', 'missing_vector_label_glyphs'),
    ('vector_label_glyph', 'missing_vector_label_glyphs'),
    ('style_syntax', 'invalid_style_syntax'),
    ('glyph', 'invalid_glyph_field'), ('sprite', 'invalid_sprite_image'),
    ('missing_glyph', 'missing_primary_place_glyphs'), ('blank_glyph', 'missing_primary_place_glyphs'),
    ('transparent_glyph', 'missing_primary_place_glyphs')])
def test_hash_correct_but_semantically_invalid_assets_fail(tmp_path, damage, reason):
    with pytest.raises(ValueError, match=reason):
        validate_render_bundle(assembled(tmp_path, damage))


def test_changed_assembly_is_not_trusted(tmp_path):
    directory = assembled(tmp_path)
    manifest = json.loads((directory / 'manifest.json').read_text())
    index = next(i for i, a in enumerate(manifest['assets']) if a['role'] == 'style')
    (directory / f'asset-{index:04d}.bin').write_bytes(b'changed')
    with pytest.raises(ValueError):
        validate_render_bundle(directory)


def test_cli_is_an_explicit_partial_content_gate(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'verify-map-render-bundle.py'
    result = subprocess.run([sys.executable, str(script), str(assembled(tmp_path))],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['publish_ready'] is False


def test_cli_missing_directory_does_not_leak_operator_path(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'verify-map-render-bundle.py'
    missing = tmp_path / 'private-operator-path'
    result = subprocess.run([sys.executable, str(script), str(missing)],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert str(missing) not in result.stdout + result.stderr
    assert json.loads(result.stdout)['status'] == 'render_validation_failed'


def test_durable_upload_worker_uses_real_render_decoder(tmp_path, db_session, monkeypatch):
    from app.config import settings
    from app.services.map_package_import_service import create_import, put_chunk, submit_import
    from app.services.map_package_import_worker import process_next
    from app.models.map_package_import import MapPackageImport
    directory = assembled(tmp_path)
    monkeypatch.setattr(settings, 'MAP_PACKAGE_ROOT', str(tmp_path / 'import-storage'))
    content = (directory / 'manifest.json').read_bytes()
    manifest = json.loads(content)
    run_id = create_import(db_session, content, user_id=None).id
    for index, asset in enumerate(manifest['assets']):
        put_chunk(db_session, run_id, asset['chunks'][0]['file'],
                  (directory / f'asset-{index:04d}.bin').read_bytes())
    submit_import(db_session, run_id)
    assert process_next(db_session)['status'] == 'render_validated'
    row = db_session.get(MapPackageImport, run_id)
    assert row.report['vector']['tile_count'] == 11
    assert row.report['glyph_ranges'] == 256
    assert row.report['publish_ready'] is False
