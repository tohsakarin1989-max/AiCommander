"""Package-set integrity is distinct from map content acceptance."""
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.map_package_set import parse_manifest, verify_directory


def package(tmp_path):
    assets = []
    for role in ('vector', 'gazetteer', 'style', 'glyphs', 'sprite', 'road_source', 'boundaries'):
        data = (role + '-public-data').encode()
        pieces = [data[:5], data[5:]]
        chunks = []
        for i, piece in enumerate(pieces):
            name = f'{role}-{i}.part'
            (tmp_path / name).write_bytes(piece)
            chunks.append({'file': name, 'size_bytes': len(piece),
                           'sha256': hashlib.sha256(piece).hexdigest()})
        assets.append({'name': role, 'role': role, 'size_bytes': len(data),
                       'license': 'fixture-license', 'attribution': 'fixture-contributor',
                       'sha256': hashlib.sha256(data).hexdigest(), 'chunks': chunks})
    return {'schema_version': '2.0', 'bundle_id': 'two-city-test',
            'source_version': '2026-09-08', 'provider': 'OSM public source',
            'license': 'ODbL-1.0', 'attribution': 'OpenStreetMap contributors',
            'contains_internal_data': False, 'bounds': [122, 45, 127, 50],
            'min_zoom': 6, 'max_zoom': 16, 'display_max_zoom': 19, 'assets': assets}


def test_complete_set_reports_integrity_not_publish_ready(tmp_path):
    manifest = package(tmp_path)
    parsed = parse_manifest(json.dumps(manifest).encode())
    result = verify_directory(tmp_path, parsed)
    assert result['status'] == 'integrity_verified'
    assert result['publish_ready'] is False
    assert len(result['assets']) == 7
    assert len(result['verified_chunks']) == 14


@pytest.mark.parametrize('damage', ['missing', 'modified', 'reordered', 'full_hash', 'symlink'])
def test_incomplete_or_mismatched_set_never_passes(tmp_path, damage):
    manifest = package(tmp_path)
    first = manifest['assets'][0]
    chunk_path = tmp_path / first['chunks'][0]['file']
    if damage == 'missing':
        chunk_path.unlink()
    elif damage == 'modified':
        chunk_path.write_bytes(b'xxxxx')
    elif damage == 'reordered':
        first['chunks'].reverse()
    elif damage == 'full_hash':
        first['sha256'] = '0' * 64
    else:
        chunk_path.unlink()
        chunk_path.symlink_to(tmp_path / manifest['assets'][1]['chunks'][0]['file'])
    result = verify_directory(tmp_path, parse_manifest(json.dumps(manifest).encode()))
    assert result['status'] == 'incomplete_or_invalid'
    assert result['publish_ready'] is False
    assert result['errors']


@pytest.mark.parametrize('field,value', [
    ('contains_internal_data', True), ('contains_internal_data', 'false'),
    ('bounds', [127, 45, 122, 50]), ('max_zoom', True),
    ('display_max_zoom', 23), ('schema_version', '1.0'), ('unexpected', 'field'),
])
def test_manifest_rejects_invalid_contract(tmp_path, field, value):
    manifest = package(tmp_path)
    manifest[field] = value
    with pytest.raises(ValueError):
        parse_manifest(json.dumps(manifest).encode())


@pytest.mark.parametrize('damage', ['path', 'duplicate', 'missing_role', 'size', 'hash', 'url'])
def test_assets_are_complete_and_allowlisted(tmp_path, damage):
    manifest = package(tmp_path)
    first = manifest['assets'][0]
    if damage == 'path':
        first['chunks'][0]['file'] = '../outside.part'
    elif damage == 'duplicate':
        manifest['assets'].append(copy.deepcopy(first))
    elif damage == 'missing_role':
        manifest['assets'].pop()
    elif damage == 'size':
        first['size_bytes'] += 1
    elif damage == 'hash':
        first['sha256'] = 'invalid'
    else:
        first['url'] = 'https://example.com/tiles'
    with pytest.raises(ValueError):
        parse_manifest(json.dumps(manifest).encode())


def test_duplicate_json_keys_rejected():
    with pytest.raises(ValueError):
        parse_manifest(b'{"schema_version":"1.0","schema_version":"2.0"}')


@pytest.mark.parametrize('profile', ['cjk-v1', 'cjk-mongolian-emoji-v1'])
def test_fixed_font_profiles_are_explicit_and_legacy_is_unchanged(tmp_path, profile):
    manifest = package(tmp_path)
    assert 'font_profile' not in parse_manifest(json.dumps(manifest).encode())
    manifest['font_profile'] = profile
    assert parse_manifest(json.dumps(manifest).encode())['font_profile'] == profile


@pytest.mark.parametrize('profile', ['external-font', '../font', None, [], True])
def test_unknown_font_profiles_are_rejected(tmp_path, profile):
    manifest = package(tmp_path)
    manifest['font_profile'] = profile
    with pytest.raises(ValueError):
        parse_manifest(json.dumps(manifest).encode())


def test_license_asset_is_optional_but_does_not_replace_required_roles(tmp_path):
    manifest = package(tmp_path)
    legal = copy.deepcopy(manifest['assets'][0])
    legal.update(name='ofl.txt', role='license')
    for index, chunk in enumerate(legal['chunks']):
        chunk['file'] = f'license-{index}.part'
    manifest['assets'].append(legal)
    assert parse_manifest(json.dumps(manifest).encode())['assets'][-1]['role'] == 'license'
    manifest['assets'].pop(0)
    with pytest.raises(ValueError, match='missing_package_role'):
        parse_manifest(json.dumps(manifest).encode())


def test_resume_reports_only_verified_chunks(tmp_path):
    manifest = package(tmp_path)
    path = tmp_path / manifest['assets'][0]['chunks'][0]['file']
    original = path.read_bytes()
    path.unlink()
    parsed = parse_manifest(json.dumps(manifest).encode())
    first = verify_directory(tmp_path, parsed)
    assert len(first['verified_chunks']) == 13
    path.write_bytes(original)
    assert verify_directory(tmp_path, parsed)['status'] == 'integrity_verified'


def test_cli_exit_codes_and_read_only_report(tmp_path):
    manifest = package(tmp_path)
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    script = Path(__file__).resolve().parents[2] / 'scripts' / 'verify-map-package-set.py'
    args = [sys.executable, str(script), str(tmp_path)]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert json.loads(result.stdout)['publish_ready'] is False
    (tmp_path / manifest['assets'][0]['chunks'][0]['file']).unlink()
    assert subprocess.run(args, capture_output=True, check=False).returncode == 1
    (tmp_path / 'manifest.json').write_text('{}')
    assert subprocess.run(args, capture_output=True, check=False).returncode == 2


@pytest.mark.parametrize('kind', ['fifo', 'symlink', 'huge_coordinate'])
def test_cli_rejects_special_manifest_and_extreme_numbers(tmp_path, kind):
    manifest = package(tmp_path)
    target = tmp_path / 'manifest.json'
    if kind == 'fifo':
        os.mkfifo(target)
    elif kind == 'symlink':
        target.symlink_to(tmp_path / 'vector-0.part')
    else:
        manifest['bounds'][0] = 10 ** 400
        target.write_text(json.dumps(manifest))
    script = Path(__file__).resolve().parents[2] / 'scripts' / 'verify-map-package-set.py'
    result = subprocess.run([sys.executable, str(script), str(tmp_path)],
                            capture_output=True, text=True, timeout=2, check=False)
    assert result.returncode == 2
    assert json.loads(result.stdout)['status'] == 'invalid_package'
    assert 'Traceback' not in result.stderr
