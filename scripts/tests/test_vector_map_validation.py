"""Use actual MVT encode/decode, not mocked decoder success."""
import gzip
from contextlib import closing
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import mapbox_vector_tile
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from app.services.vector_map_validation import validate_vector_mbtiles


BOUNDS = [122, 45, 127, 49]


def fixture_map(tmp_path, damage=None):
    path = tmp_path / 'map.mbtiles'
    raw = mapbox_vector_tile.encode({'name': 'place', 'features': [
        {'geometry': 'POINT(12 30)', 'properties': {'name': '大庆'}}]})
    payload = gzip.compress(raw)
    if damage == 'protobuf':
        payload = gzip.compress(b'not protobuf')
    elif damage == 'gzip':
        payload = payload[:-3]
    elif damage == 'trailing':
        payload += b'junk'
    elif damage == 'bomb':
        payload = gzip.compress(b'A' * (8 * 1024 * 1024 + 1))
    elif damage == 'empty':
        payload = gzip.compress(b'')
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript('CREATE TABLE metadata(name TEXT,value TEXT);'
            'CREATE TABLE tiles(zoom_level INTEGER,tile_column INTEGER,tile_row INTEGER,tile_data BLOB);')
        metadata = {'format': 'pbf', 'minzoom': '6', 'maxzoom': '16',
                    'bounds': '122,45,127,49',
                    'json': json.dumps({'vector_layers': [{'id': 'place', 'fields': {'name': 'String'}}]})}
        if damage == 'format':
            metadata['format'] = 'png'
        elif damage == 'metadata':
            metadata['json'] = '{}'
        elif damage == 'deep_json':
            metadata['json'] = '[' * 10_000 + '0' + ']' * 10_000
        connection.executemany('INSERT INTO metadata VALUES (?,?)', metadata.items())
        for zoom in range(6, 17):
            if damage == 'gap' and zoom == 10:
                continue
            connection.execute('INSERT INTO tiles VALUES (?,?,?,?)',
                               (zoom, 0 if damage != 'coordinate' else -1, 0, payload))
        if damage == 'duplicate':
            connection.execute('INSERT INTO tiles SELECT * FROM tiles LIMIT 1')
    return path


def validate(path):
    return validate_vector_mbtiles(path, hashlib.sha256(path.read_bytes()).hexdigest(),
                                   bounds=BOUNDS, min_zoom=6, max_zoom=16)


def test_full_decode_and_readonly_source(tmp_path):
    path = fixture_map(tmp_path)
    before = path.read_bytes()
    report = validate(path)
    assert report['tile_count'] == 11
    assert report['feature_count'] == 11
    assert report['layers'] == ['place']
    assert report['publish_ready'] is False
    assert report['sha256'] == hashlib.sha256(before).hexdigest()
    assert path.read_bytes() == before


def test_label_audit_uses_first_present_property_and_counts_cached_tiles(tmp_path):
    path = fixture_map(tmp_path)
    raw = mapbox_vector_tile.encode({'name': 'place', 'features': [
        {'geometry': 'POINT(12 30)', 'properties': {'name:zh': '大庆', 'name': 'Unused'}},
        {'geometry': 'POINT(14 30)', 'properties': {'name:latin': 'Š', 'name': 'Unused'}},
        {'geometry': 'POINT(15 30)', 'properties': {'name': '🏥'}},
        {'geometry': 'POINT(16 30)', 'properties': {'name:zh': '', 'name': 'Unused'}},
    ]})
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute('UPDATE tiles SET tile_data=?', (gzip.compress(raw),))
    report = validate_vector_mbtiles(path, hashlib.sha256(path.read_bytes()).hexdigest(),
        bounds=BOUNDS, min_zoom=6, max_zoom=16,
        label_fields={'place': ('name:zh', 'name:latin', 'name')})
    audit = report['label_audit']
    assert audit['label_count'] == 33  # Repeated tiles remain counted, not sampled.
    assert audit['codepoints'] == sorted(map(ord, '大庆Š🏥'))
    assert audit['shaping_verified'] is False


@pytest.mark.parametrize('fields', [{}, {'place': ()}, {'place': ('name', 'name')},
    {'place': 'name'}, {'../place': ('name',)}, {'place': ('../name',)}])
def test_label_audit_rejects_invalid_contract(tmp_path, fields):
    path = fixture_map(tmp_path)
    with pytest.raises(ValueError, match='invalid_label_contract'):
        validate_vector_mbtiles(path, hashlib.sha256(path.read_bytes()).hexdigest(),
            bounds=BOUNDS, min_zoom=6, max_zoom=16, label_fields=fields)


def test_label_audit_does_not_silently_coerce_nontext_names(tmp_path):
    path = fixture_map(tmp_path)
    raw = mapbox_vector_tile.encode({'name': 'place', 'features': [
        {'geometry': 'POINT(12 30)', 'properties': {'name': 12}}]})
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute('UPDATE tiles SET tile_data=?', (gzip.compress(raw),))
    with pytest.raises(ValueError, match='invalid_label_value'):
        validate_vector_mbtiles(path, hashlib.sha256(path.read_bytes()).hexdigest(),
            bounds=BOUNDS, min_zoom=6, max_zoom=16, label_fields={'place': ('name',)})


def test_label_cache_does_not_retain_per_tile_character_sets(tmp_path, monkeypatch):
    import weakref
    from app.services import vector_map_validation as service

    path = fixture_map(tmp_path)
    with closing(sqlite3.connect(path)) as connection, connection:
        for zoom in range(6, 17):
            raw = mapbox_vector_tile.encode({'name': 'place', 'features': [
                {'geometry': f'POINT({zoom} 30)', 'properties': {'name': '大庆'}}]})
            connection.execute('UPDATE tiles SET tile_data=? WHERE zoom_level=?',
                               (gzip.compress(raw), zoom))
    references, retained = [], []
    original = service._decode

    def observe(*args):
        retained.append(sum(ref() is not None for ref in references))
        result = original(*args)
        references.append(weakref.ref(result[3]))
        return result

    monkeypatch.setattr(service, '_decode', observe)
    report = validate_vector_mbtiles(path, hashlib.sha256(path.read_bytes()).hexdigest(),
        bounds=BOUNDS, min_zoom=6, max_zoom=16, label_fields={'place': ('name',)})
    assert report['label_audit']['label_count'] == 11
    assert len(references) == 11
    assert max(retained) <= 1


@pytest.mark.parametrize('damage', ['protobuf', 'gzip', 'trailing', 'bomb', 'empty',
    'format', 'metadata', 'deep_json', 'gap', 'coordinate', 'duplicate'])
def test_rejects_broken_content(tmp_path, damage):
    with pytest.raises(ValueError):
        validate(fixture_map(tmp_path, damage))


def test_hash_mismatch(tmp_path):
    path = fixture_map(tmp_path)
    with pytest.raises(ValueError, match='checksum'):
        validate_vector_mbtiles(path, '0' * 64, bounds=BOUNDS, min_zoom=6, max_zoom=16)


def test_symlink_is_not_opened(tmp_path):
    path = fixture_map(tmp_path)
    link = tmp_path / 'link.mbtiles'
    link.symlink_to(path)
    with pytest.raises((ValueError, OSError)):
        validate(link)


@pytest.mark.parametrize('damage', ['duplicate_layer', 'tag_index', 'odd_tags',
    'huge_command', 'unknown_command', 'zero_command', 'missing_line',
    'open_polygon', 'extent', 'version'])
def test_invalid_mvt_structure(tmp_path, damage):
    from mapbox_vector_tile.decoder import TileData

    path = fixture_map(tmp_path)
    with closing(sqlite3.connect(path)) as connection, connection:
        raw = gzip.decompress(connection.execute('SELECT tile_data FROM tiles LIMIT 1').fetchone()[0])
        tile = TileData(raw).tile
        layer = tile.layers[0]
        feature = layer.features[0]
        if damage == 'duplicate_layer':
            tile.layers.add().CopyFrom(layer)
        elif damage == 'tag_index':
            feature.tags[0] = 999
        elif damage == 'odd_tags':
            feature.tags.append(0)
        elif damage == 'extent':
            layer.extent = 0
        elif damage == 'version':
            layer.version = 9
        else:
            del feature.geometry[:]
            if damage == 'missing_line':
                feature.type = 2
                feature.geometry.extend([9, 0, 0])
            elif damage == 'open_polygon':
                feature.type = 3
                feature.geometry.extend([9, 0, 0, 18, 2, 0, 0, 2])
            else:
                feature.geometry.extend({'huge_command': [0xfffffff9],
                    'unknown_command': [9, 0, 0, 11], 'zero_command': [1]}[damage])
        connection.execute('UPDATE tiles SET tile_data=?', (gzip.compress(tile.SerializeToString()),))
    with pytest.raises(ValueError):
        validate(path)


@pytest.mark.parametrize('bounds', [[0, 0, 1, 1], [float('nan'), 45, 127, 49],
    [10**400, 45, 127, 49], None])
def test_invalid_bounds_contract(tmp_path, bounds):
    path = fixture_map(tmp_path)
    with pytest.raises(ValueError):
        validate_vector_mbtiles(path, hashlib.sha256(path.read_bytes()).hexdigest(),
                               bounds=bounds, min_zoom=6, max_zoom=16)


def test_deadline_prevents_validation_success(tmp_path):
    path = fixture_map(tmp_path)
    with pytest.raises(ValueError, match='timeout'):
        validate_vector_mbtiles(path, hashlib.sha256(path.read_bytes()).hexdigest(),
                               bounds=BOUNDS, min_zoom=6, max_zoom=16, timeout_seconds=1e-12)


def test_cli_success_and_corruption(tmp_path):
    path = fixture_map(tmp_path)
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'verify-vector-map.py'),
               str(path), '--sha256', hashlib.sha256(path.read_bytes()).hexdigest(),
               '--bounds', '122', '45', '127', '49']
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0
    assert json.loads(result.stdout)['tile_count'] == 11
    path.write_bytes(b'corrupt')
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode == 2
    assert json.loads(result.stdout)['publish_ready'] is False
    assert str(tmp_path) not in result.stdout


def test_cli_can_audit_fixed_public_label_fields(tmp_path):
    path = fixture_map(tmp_path)
    result = subprocess.run([sys.executable,
        str(Path(__file__).resolve().parents[1] / 'verify-vector-map.py'), str(path),
        '--sha256', hashlib.sha256(path.read_bytes()).hexdigest(),
        '--bounds', '122', '45', '127', '49', '--audit-public-labels'],
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    audit = json.loads(result.stdout)['label_audit']
    assert audit['label_count'] == 11
    assert audit['codepoints'] == sorted(map(ord, '大庆'))
    assert audit['fields']['place'] == ['name:zh', 'name:latin', 'name']


@pytest.mark.parametrize('geometry', [
    'MULTIPOINT((1 2),(3 4))',
    'LINESTRING(1 2,3 4)',
    'MULTILINESTRING((1 2,3 4),(5 6,7 8))',
    'POLYGON((0 0,10 0,10 10,0 10,0 0))',
    'MULTIPOLYGON(((0 0,10 0,10 10,0 10,0 0)),((20 20,30 20,30 30,20 30,20 20)))',
])
def test_valid_geometry_types(tmp_path, geometry):
    path = fixture_map(tmp_path)
    raw = mapbox_vector_tile.encode({'name': 'place', 'features': [
        {'geometry': geometry, 'properties': {'name': '公开要素'}}]})
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute('UPDATE tiles SET tile_data=?', (gzip.compress(raw),))
    assert validate(path)['feature_count'] == 11


def test_last_tile_finishing_after_deadline_is_not_success(tmp_path, monkeypatch):
    from app.services import vector_map_validation as service

    path = fixture_map(tmp_path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute('DELETE FROM tiles WHERE zoom_level != 6')
        connection.execute("UPDATE metadata SET value='6' WHERE name='maxzoom'")
    clock = [0.0]
    original = service._decode

    def slow_decode(*args):
        result = original(*args)
        clock[0] = 2.0
        return result

    monkeypatch.setattr(service.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(service, '_decode', slow_decode)
    with pytest.raises(ValueError, match='timeout'):
        service.validate_vector_mbtiles(path, hashlib.sha256(path.read_bytes()).hexdigest(),
            bounds=BOUNDS, min_zoom=6, max_zoom=6, timeout_seconds=1)


def test_deep_json_cli_is_controlled_failure(tmp_path):
    path = fixture_map(tmp_path, 'deep_json')
    result = subprocess.run([sys.executable,
        str(Path(__file__).resolve().parents[1] / 'verify-vector-map.py'), str(path),
        '--sha256', hashlib.sha256(path.read_bytes()).hexdigest(),
        '--bounds', '122', '45', '127', '49'],
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 2
    assert json.loads(result.stdout)['status'] == 'validation_failed'
    assert not result.stderr
