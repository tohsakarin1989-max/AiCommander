"""Offline build inputs are fixed local files, never request-provided URLs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.services.map_package_builder import build_package
from app.services.map_package_set import read_manifest, verify_directory


def recipe(tmp_path):
    assets = []
    for role in ('vector', 'gazetteer', 'style', 'glyphs', 'sprite', 'road_source', 'boundaries', 'license'):
        content = (role * 5).encode()
        path = tmp_path / f'{role}.bin'
        path.write_bytes(content)
        assets.append(dict(name=path.name, role=role, path=str(path),
                           size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
                           license='fixture', attribution='fixture'))
    return dict(schema_version='2.0', bundle_id='test-build', source_version='fixture',
                provider='fixture', license='fixture', attribution='fixture',
                contains_internal_data=False, bounds=[122, 45, 127, 50],
                min_zoom=6, max_zoom=16, display_max_zoom=19, assets=assets)


def test_build_readback_and_repeat_are_byte_identical(tmp_path):
    spec = recipe(tmp_path)
    for name in ('first', 'second'):
        result = build_package(spec, tmp_path / name, chunk_bytes=7)
        manifest = read_manifest(tmp_path / name)
        assert result['publish_ready'] is False
        assert verify_directory(tmp_path / name, manifest)['status'] == 'integrity_verified'
        assert all('path' not in asset for asset in manifest['assets'])
    assert (tmp_path / 'first/manifest.json').read_bytes() == (tmp_path / 'second/manifest.json').read_bytes()


@pytest.mark.parametrize('damage', ['hash', 'size', 'symlink', 'fifo', 'unknown_role', 'internal', 'relative'])
def test_bad_source_or_recipe_never_leaves_complete_output(tmp_path, damage):
    spec = recipe(tmp_path)
    asset = spec['assets'][0]
    path = Path(asset['path'])
    if damage == 'hash':
        asset['sha256'] = '0' * 64
    elif damage == 'size':
        asset['size_bytes'] += 1
    elif damage in ('symlink', 'fifo'):
        import os
        path.unlink()
        if damage == 'symlink':
            path.symlink_to(spec['assets'][1]['path'])
        else:
            os.mkfifo(path)
    elif damage == 'unknown_role':
        asset['role'] = 'unknown'
    elif damage == 'internal':
        spec['contains_internal_data'] = True
    else:
        asset['path'] = 'relative.bin'
    target = tmp_path / 'output'
    with pytest.raises((OSError, ValueError)):
        build_package(spec, target, chunk_bytes=7)
    assert not target.exists()


def test_existing_output_is_untouched(tmp_path):
    spec = recipe(tmp_path)
    target = tmp_path / 'existing'
    target.mkdir()
    (target / 'keep').write_text('keep')
    with pytest.raises(FileExistsError):
        build_package(spec, target)
    assert (target / 'keep').read_text() == 'keep'


@pytest.mark.parametrize('size', [0, -1, True, 16 * 1024 * 1024 + 1])
def test_invalid_chunk_size_fails_before_output(tmp_path, size):
    with pytest.raises(ValueError):
        build_package(recipe(tmp_path), tmp_path / 'output', chunk_bytes=size)
    assert not (tmp_path / 'output').exists()


def test_cli_build_and_existing_destination(tmp_path):
    source = tmp_path / 'recipe.json'
    source.write_text(json.dumps(recipe(tmp_path)))
    script = Path(__file__).resolve().parents[2] / 'scripts/build-map-package-set.py'
    args = [sys.executable, str(script), str(source), str(tmp_path / 'built')]
    environment = {key: value for key, value in os.environ.items()
                   if key not in {'SECRET_KEY', 'DATABASE_URL', 'REDIS_URL'}}
    result = subprocess.run(args, capture_output=True, text=True, timeout=5,
                            cwd=tmp_path, env=environment)
    assert result.returncode == 0
    assert json.loads(result.stdout)['status'] == 'transport_built'
    assert subprocess.run(args, capture_output=True, timeout=5).returncode == 2


def test_symlink_parent_is_not_followed(tmp_path):
    spec = recipe(tmp_path)
    alias = tmp_path / 'alias'
    alias.symlink_to(tmp_path, target_is_directory=True)
    spec['assets'][0]['path'] = str(alias / 'vector.bin')
    with pytest.raises(OSError):
        build_package(spec, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()
