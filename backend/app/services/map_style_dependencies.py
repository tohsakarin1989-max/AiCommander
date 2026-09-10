"""Validate a public style's local dependency closure and bind a snapshot.

This is not the MapLibre syntax validator or a binary/font coverage check.
The import worker must also perform those checks before accepting the bundle.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

from app.services.map_package_set import parse_manifest
from app.services.map_glyph_validation import glyph_asset_range
from app.services.map_font_profiles import font_profile


FONT = 'Noto Sans CJK SC Regular'
GLYPHS = 'aic-map://glyphs/{fontstack}/{range}.pbf'
TILES = 'aic-map://public/{z}/{x}/{y}'
SPRITE = 'aic-map://sprite'
ROOT_FIELDS = {'version', 'name', 'metadata', 'sources', 'glyphs', 'sprite', 'layers',
               'center', 'zoom', 'bearing', 'pitch', 'transition'}
SOURCE_FIELDS = {'type', 'tiles', 'minzoom', 'maxzoom', 'bounds', 'attribution'}
LAYER_FIELDS = {'id', 'type', 'source', 'source-layer', 'minzoom', 'maxzoom',
                'filter', 'layout', 'paint', 'metadata'}


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_style_key')
        result[key] = value
    return result


def _load(content: bytes) -> dict[str, Any]:
    if not isinstance(content, bytes) or not 0 < len(content) <= 1024 * 1024:
        raise ValueError('invalid_style_size')
    try:
        value = json.loads(content, object_pairs_hook=_object, parse_constant=_invalid_number,
                           parse_float=_finite_float)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('invalid_style_json') from exc
    if not isinstance(value, dict):
        raise ValueError('invalid_style_object')
    return value


def _invalid_number(_: str) -> None:
    raise ValueError('invalid_style_number')


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('invalid_style_number')
    return number


def _check_nested(value: Any, icons: set[str], has_sprite: bool, depth: int = 0,
                  fonts: tuple[str, ...] = (FONT,)) -> None:
    if depth > 64:
        raise ValueError('style_nesting_limit')
    if isinstance(value, dict):
        for key, item in value.items():
            # Formatted labels may carry per-section font overrides. They must
            # not silently select another, unbundled font via an expression.
            if key == 'text-font' and item != list(fonts):
                raise ValueError('unbundled_style_font')
            if key in {'icon-image', 'fill-pattern', 'line-pattern', 'background-pattern'}:
                if not isinstance(item, str) or item not in icons or not has_sprite:
                    raise ValueError('unbundled_style_icon')
            _check_nested(item, icons, has_sprite, depth + 1, fonts)
    elif isinstance(value, list):
        if value and value[0] == 'image':
            if len(value) != 2 or not isinstance(value[1], str) or value[1] not in icons or not has_sprite:
                raise ValueError('unbundled_style_image')
        for item in value:
            _check_nested(item, icons, has_sprite, depth + 1, fonts)


def validate_style_dependencies(content: bytes, manifest: dict[str, Any], *,
                                source_layers: set[str], sprite_names: set[str]) -> dict[str, Any]:
    """Require local logical URLs; source layer/icon sets come from decoded assets."""
    manifest = parse_manifest(json.dumps(manifest, ensure_ascii=False).encode())
    profile = font_profile(manifest)
    style = _load(content)
    if set(style) - ROOT_FIELDS or type(style.get('version')) is not int or style['version'] != 8:
        raise ValueError('unsupported_offline_style')
    if not isinstance(style.get('metadata', {}), dict):
        raise ValueError('invalid_style_metadata')
    if style.get('glyphs') != GLYPHS:
        raise ValueError('external_style_glyphs')
    sources = style.get('sources')
    if not isinstance(sources, dict) or set(sources) != {'public'}:
        raise ValueError('unsupported_style_sources')
    source = sources['public']
    if (not isinstance(source, dict) or set(source) - SOURCE_FIELDS
            or source.get('type') != 'vector' or source.get('tiles') != [TILES]
            or type(source.get('minzoom')) is not int or type(source.get('maxzoom')) is not int
            or source['minzoom'] != manifest['min_zoom'] or source['maxzoom'] != manifest['max_zoom']
            or source.get('bounds') != manifest['bounds']):
        raise ValueError('unbound_style_source')
    attribution = source.get('attribution', '')
    if not isinstance(attribution, str) or len(attribution) > 1024 or '<' in attribution or '>' in attribution:
        raise ValueError('invalid_style_attribution')
    assets = manifest['assets']
    glyph_names = {a['name'] for a in assets if a['role'] == 'glyphs'}
    expected = {f'glyphs-{start}-{start + 255}.pbf' for start in range(0, 65536, 256)}
    if not expected <= glyph_names:
        raise ValueError('incomplete_style_glyphs')
    for name in glyph_names:
        glyph_asset_range(name)
    has_sprite = 'sprite' in style
    if has_sprite:
        sprites = {a['name'] for a in assets if a['role'] == 'sprite'}
        if style['sprite'] != SPRITE or not {'sprite.json', 'sprite.png', 'sprite-2x.json', 'sprite-2x.png'} <= sprites:
            raise ValueError('unbundled_style_sprite')
    layers = style.get('layers')
    if not isinstance(layers, list) or not 1 <= len(layers) <= 128:
        raise ValueError('invalid_style_layers')
    ids = set()
    for layer in layers:
        if (not isinstance(layer, dict) or set(layer) - LAYER_FIELDS
                or not isinstance(layer.get('id'), str) or not 1 <= len(layer['id']) <= 100
                or layer['id'] in ids or not isinstance(layer.get('type'), str)
                or layer['type'] not in {'background', 'fill', 'line', 'symbol', 'circle'}):
            raise ValueError('unsupported_style_layer')
        ids.add(layer['id'])
        if layer['type'] != 'background':
            if (layer.get('source') != 'public' or not isinstance(layer.get('source-layer'), str)
                    or layer['source-layer'] not in source_layers):
                raise ValueError('unbundled_style_layer')
        elif 'source' in layer or 'source-layer' in layer:
            raise ValueError('invalid_background_source')
        layout = layer.get('layout', {})
        if not isinstance(layout, dict) or not isinstance(layer.get('paint', {}), dict):
            raise ValueError('invalid_style_layer_properties')
        if 'text-field' in layout and layout.get('text-font') != list(profile.fonts):
            raise ValueError('unbundled_style_font')
    _check_nested(style, sprite_names, has_sprite, fonts=profile.fonts)
    return {'status': 'local_dependencies_declared', 'publish_ready': False,
            'glyph_range_count': len(glyph_names), 'layer_count': len(layers),
            'sprite_required': has_sprite, 'fontstack': profile.fontstack}


def bind_style_snapshot(content: bytes, manifest: dict[str, Any], snapshot_id: str, *,
                        source_layers: set[str], sprite_names: set[str]) -> dict[str, Any]:
    """Replace only validated logical resource slots; never global string replace."""
    if not isinstance(snapshot_id, str) or not re.fullmatch(
            r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', snapshot_id):
        raise ValueError('invalid_style_snapshot')
    validate_style_dependencies(content, manifest, source_layers=source_layers, sprite_names=sprite_names)
    style = _load(content)
    style['glyphs'] = f'/api/maps/{snapshot_id}/glyphs/{{fontstack}}/{{range}}.pbf'
    style['sources']['public']['tiles'] = [f'/api/maps/tiles/{snapshot_id}/{{z}}/{{x}}/{{y}}']
    style['metadata'] = {**style.get('metadata', {}), 'aic:snapshot-id': snapshot_id}
    if 'sprite' in style:
        style['sprite'] = f'/api/maps/{snapshot_id}/sprite'
    return style
