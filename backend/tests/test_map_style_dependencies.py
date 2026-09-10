import copy
import json

import pytest

from app.services.map_style_dependencies import bind_style_snapshot, validate_style_dependencies
from tests.test_map_package_set import package


SNAPSHOT = '12345678-1234-1234-1234-123456789abc'


def inputs(tmp_path):
    manifest = package(tmp_path)
    original = next(a for a in manifest['assets'] if a['role'] == 'glyphs')
    manifest['assets'] = [a for a in manifest['assets'] if a['role'] != 'glyphs']
    for start in range(0, 65536, 256):
        glyph = copy.deepcopy(original)
        glyph['name'] = f'glyphs-{start}-{start + 255}.pbf'
        for index, chunk in enumerate(glyph['chunks']):
            chunk['file'] = f'glyph-{start}-{index}.part'
        manifest['assets'].append(glyph)
    style = {'version': 8, 'glyphs': 'aic-map://glyphs/{fontstack}/{range}.pbf',
        'sources': {'public': {'type': 'vector',
            'tiles': ['aic-map://public/{z}/{x}/{y}'],
            'minzoom': 6, 'maxzoom': 16, 'bounds': manifest['bounds']}},
        'layers': [{'id': 'places', 'type': 'symbol', 'source': 'public',
                    'source-layer': 'place', 'layout': {'text-field': ['get', 'name'],
                    'text-font': ['Noto Sans CJK SC Regular']}}]}
    return style, manifest


def check(style, manifest, **kwargs):
    return validate_style_dependencies(json.dumps(style).encode(), manifest,
                                       source_layers={'place'}, sprite_names=set(), **kwargs)


def test_local_closed_dependencies_and_snapshot_binding(tmp_path):
    style, manifest = inputs(tmp_path)
    raw = json.dumps(style).encode()
    report = check(style, manifest)
    assert report['glyph_range_count'] == 256
    result = bind_style_snapshot(raw, manifest, SNAPSHOT, source_layers={'place'}, sprite_names=set())
    assert result['glyphs'] == f'/api/maps/{SNAPSHOT}/glyphs/{{fontstack}}/{{range}}.pbf'
    assert result['sources']['public']['tiles'] == [f'/api/maps/tiles/{SNAPSHOT}/{{z}}/{{x}}/{{y}}']
    assert 'aic-map://' in json.dumps(style)


def test_optional_supplementary_glyph_range_keeps_base_required(tmp_path):
    style, manifest = inputs(tmp_path)
    extra = copy.deepcopy(next(a for a in manifest['assets'] if a['role'] == 'glyphs'))
    extra['name'] = 'glyphs-127744-127999.pbf'
    for index, chunk in enumerate(extra['chunks']):
        chunk['file'] = f'extra-glyph-{index}.part'
    manifest['assets'].append(extra)
    assert check(style, manifest)['glyph_range_count'] == 257
    extra['name'] = 'glyphs-1114112-1114367.pbf'
    with pytest.raises(ValueError):
        check(style, manifest)


def test_composite_style_is_bound_to_declared_profile(tmp_path):
    style, manifest = inputs(tmp_path)
    manifest['font_profile'] = 'cjk-mongolian-emoji-v1'
    fonts = ['Noto Sans CJK SC Regular', 'Noto Sans Mongolian Regular', 'Noto Emoji Regular']
    style['layers'][0]['layout']['text-font'] = fonts
    assert check(style, manifest)['fontstack'] == ','.join(fonts)
    style['layers'][0]['layout']['text-font'] = fonts[:1]
    with pytest.raises(ValueError, match='unbundled_style_font'):
        check(style, manifest)


@pytest.mark.parametrize('damage', ['glyph_url', 'tile_url', 'source_url', 'source_extra',
    'imports', 'font_faces', 'font', 'layer', 'zoom', 'bounds', 'missing_glyph', 'sprite', 'icon'])
def test_undeclared_or_external_dependencies_rejected(tmp_path, damage):
    style, manifest = inputs(tmp_path)
    source = style['sources']['public']
    if damage == 'glyph_url':
        style['glyphs'] = 'https://example.com/{range}.pbf'
    elif damage == 'tile_url':
        source['tiles'] = ['/api/maps/tiles/another-snapshot/{z}/{x}/{y}']
    elif damage == 'source_url':
        source['url'] = 'https://example.com/tilejson'
    elif damage == 'source_extra':
        style['sources']['video'] = {'type': 'video', 'urls': ['https://example.com/video']}
    elif damage == 'imports':
        style['imports'] = [{'url': 'https://example.com/style'}]
    elif damage == 'font_faces':
        style['font-faces'] = {'remote': {'url': 'https://example.com/font'}}
    elif damage == 'font':
        style['layers'][0]['layout']['text-font'] = ['Unknown font']
    elif damage == 'layer':
        style['layers'][0]['source-layer'] = 'not_in_vector'
    elif damage == 'zoom':
        source['maxzoom'] = 19
    elif damage == 'bounds':
        source['bounds'] = [0, 0, 1, 1]
    elif damage == 'missing_glyph':
        manifest['assets'].pop()
    elif damage == 'sprite':
        style['sprite'] = 'https://example.com/sprite'
    else:
        style['layers'][0]['layout']['icon-image'] = 'unknown-icon'
    with pytest.raises(ValueError):
        check(style, manifest)


def test_binding_rejects_untrusted_snapshot_id(tmp_path):
    style, manifest = inputs(tmp_path)
    with pytest.raises(ValueError):
        bind_style_snapshot(json.dumps(style).encode(), manifest, '../other',
                            source_layers={'place'}, sprite_names=set())


@pytest.mark.parametrize('field', ['source-layer', 'type'])
def test_malformed_layer_type_is_controlled_failure(tmp_path, field):
    style, manifest = inputs(tmp_path)
    style['layers'][0][field] = ['unexpected']
    with pytest.raises(ValueError):
        check(style, manifest)


def test_formatted_label_cannot_override_font(tmp_path):
    style, manifest = inputs(tmp_path)
    style['layers'][0]['layout']['text-field'] = ['format', 'place',
        {'text-font': ['literal', ['Unknown font']]}]
    with pytest.raises(ValueError, match='font'):
        check(style, manifest)


def test_declared_sprite_binding_and_missing_retina(tmp_path):
    style, manifest = inputs(tmp_path)
    sprite = next(a for a in manifest['assets'] if a['role'] == 'sprite')
    manifest['assets'].remove(sprite)
    for name in ['sprite.png', 'sprite.json', 'sprite-2x.png', 'sprite-2x.json']:
        asset = copy.deepcopy(sprite)
        asset['name'] = name
        for index, chunk in enumerate(asset['chunks']):
            chunk['file'] = name.replace('.', '-') + f'-{index}.part'
        manifest['assets'].append(asset)
    style['sprite'] = 'aic-map://sprite'
    style['layers'][0]['layout']['icon-image'] = 'village'
    result = bind_style_snapshot(json.dumps(style).encode(), manifest, SNAPSHOT,
                                source_layers={'place'}, sprite_names={'village'})
    assert result['sprite'] == f'/api/maps/{SNAPSHOT}/sprite'
    manifest['assets'].pop()
    with pytest.raises(ValueError, match='sprite'):
        validate_style_dependencies(json.dumps(style).encode(), manifest,
                                    source_layers={'place'}, sprite_names={'village'})


@pytest.mark.parametrize('content', [b'{"version":8,"version":8}', b'[]',
    b'[' * 10000 + b'0' + b']' * 10000, b'', b'\xff'],
    ids=['duplicate-key', 'array', 'deep-nesting', 'empty', 'invalid-utf8'])
def test_bad_json_is_controlled_failure(tmp_path, content):
    _, manifest = inputs(tmp_path)
    with pytest.raises(ValueError):
        validate_style_dependencies(content, manifest, source_layers={'place'}, sprite_names=set())


def test_binding_updates_old_snapshot_metadata(tmp_path):
    style, manifest = inputs(tmp_path)
    style['metadata'] = {'aic:snapshot-id': 'old-id', 'aic:style-version': 'public-v1'}
    result = bind_style_snapshot(json.dumps(style).encode(), manifest, SNAPSHOT,
                                source_layers={'place'}, sprite_names=set())
    assert result['metadata'] == {'aic:snapshot-id': SNAPSHOT, 'aic:style-version': 'public-v1'}


@pytest.mark.parametrize('number', ['NaN', 'Infinity', '1e400'])
def test_nonfinite_numbers_cannot_reach_bound_json(tmp_path, number):
    style, manifest = inputs(tmp_path)
    content = json.dumps(style)[:-1] + ',"zoom":' + number + '}'
    with pytest.raises(ValueError):
        bind_style_snapshot(content.encode(), manifest, SNAPSHOT,
                            source_layers={'place'}, sprite_names=set())
