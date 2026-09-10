import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'map-build/assemble-two-city-candidate.py'
SPEC = importlib.util.spec_from_file_location('two_city_candidate', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_asset_requires_fixed_hash_and_preserves_license(tmp_path):
    path = tmp_path / 'input.bin'
    path.write_bytes(b'public fixture')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    asset = MODULE.asset(path, 'input.bin', 'vector', digest, 'ODbL-1.0', 'fixture')
    assert asset['sha256'] == digest
    assert asset['license'] == 'ODbL-1.0'
    assert asset['path'] == str(path)
    with pytest.raises(ValueError, match='source_hash_mismatch'):
        MODULE.asset(path, 'input.bin', 'vector', '0' * 64, 'ODbL-1.0', 'fixture')


def test_missing_fixed_sources_does_not_create_output(tmp_path):
    output = tmp_path / 'output'
    with pytest.raises(OSError):
        MODULE.assemble(tmp_path, output)
    assert not output.exists()


def test_fixed_manifest_hash_applies_to_parsed_bytes(tmp_path):
    path = tmp_path / 'manifest.json'
    content = b'{"files": []}'
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    assert MODULE.fixed_json(path, digest) == {'files': []}
    path.write_bytes(b'{"files": ["changed"]}')
    with pytest.raises(ValueError, match='source_hash_mismatch'):
        MODULE.fixed_json(path, digest)
    huge = b' ' * (2 * 1024 * 1024 + 1)
    path.write_bytes(huge)
    with pytest.raises(ValueError, match='source_hash_mismatch'):
        MODULE.fixed_json(path, hashlib.sha256(huge).hexdigest())


@pytest.mark.parametrize('kind', ['fifo', 'symlink', 'directory'])
def test_asset_and_manifest_reject_special_inputs(tmp_path, kind):
    path = tmp_path / 'special'
    if kind == 'fifo':
        os.mkfifo(path)
    elif kind == 'symlink':
        target = tmp_path / 'regular'
        target.write_bytes(b'{}')
        path.symlink_to(target)
    else:
        path.mkdir()
    with pytest.raises((OSError, ValueError)):
        MODULE.asset(path, 'source.bin', 'vector', '0' * 64, 'fixture', 'fixture')
    with pytest.raises((OSError, ValueError)):
        MODULE.fixed_json(path, '0' * 64)


@pytest.mark.parametrize('composite', [False, True])
def test_complete_transport_recipe_with_real_style_export(tmp_path, monkeypatch, composite):
    fixed = []
    for rel, name, role, _ in MODULE.FIXED:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        content = f'fixture {name}'.encode()
        path.write_bytes(content)
        fixed.append((rel, name, role, hashlib.sha256(content).hexdigest()))
    monkeypatch.setattr(MODULE, 'FIXED', fixed)
    name = 'Noto Sans CJK SC Regular'
    if composite:
        name += ',Noto Sans Mongolian Regular,Noto Emoji Regular'
    folder = 'glyphs-composite-v1' if composite else 'glyphs-cjk-v1'
    glyph_dir = tmp_path / folder / name
    glyph_dir.mkdir(parents=True)
    glyphs = []
    starts = list(range(0, 65536, 256)) + ([127744] if composite else [])
    for start in starts:
        span = f'{start}-{start + 255}.pbf'
        (glyph_dir / span).write_bytes(b'fixture glyph')
        glyphs.append(dict(name=span, sha256=hashlib.sha256(b'fixture glyph').hexdigest()))
    manifest = tmp_path / folder / 'glyph-manifest.json'
    manifest.write_text(json.dumps(dict(files=glyphs, fontstack=name)))
    monkeypatch.setattr(MODULE, 'COMPOSITE_GLYPH_MANIFEST_SHA' if composite else 'GLYPH_MANIFEST_SHA',
                        hashlib.sha256(manifest.read_bytes()).hexdigest(), raising=False)
    legal = tmp_path / 'fonts-sans2.004/LICENSE'
    legal.parent.mkdir()
    legal.write_bytes(b'fixture license')
    monkeypatch.setattr(MODULE, 'FONT_LICENSE_SHA', hashlib.sha256(legal.read_bytes()).hexdigest())
    if composite:
        for relative, constant in [('fonts-fallback-v1/mongolian/OFL.txt', 'MONGOLIAN_LICENSE_SHA'),
                                   ('fonts-fallback-v1/NotoEmoji-OFL.txt', 'EMOJI_LICENSE_SHA')]:
            item = tmp_path / relative
            item.parent.mkdir(parents=True, exist_ok=True)
            item.write_bytes(b'fixture additional license')
            monkeypatch.setattr(MODULE, constant, hashlib.sha256(item.read_bytes()).hexdigest(), raising=False)
    output = tmp_path / 'output'
    options = {'font_profile': 'cjk-mongolian-emoji-v1'} if composite else {}
    result = MODULE.assemble(tmp_path, output, **options)
    assert result['status'] == 'transport_built'
    assert result['publish_ready'] is False
    assert result['assets'] == (270 if composite else 267)
    recipe = json.loads((output / 'recipe.json').read_bytes())
    style = json.loads((output / 'style.json').read_bytes())
    if composite:
        assert recipe['font_profile'] == 'cjk-mongolian-emoji-v1'
        assert len([asset for asset in recipe['assets'] if asset['role'] == 'license']) == 3
    else:
        assert 'font_profile' not in recipe
    for layer in style['layers']:
        if layer['type'] == 'symbol':
            assert layer['layout']['text-font'] == name.split(',')
    assert (output / result['assembly'] / 'assembled.json').is_file()
    before = (output / 'build-receipt.json').read_bytes()
    with pytest.raises(FileExistsError):
        MODULE.assemble(tmp_path, output, **options)
    assert (output / 'build-receipt.json').read_bytes() == before
