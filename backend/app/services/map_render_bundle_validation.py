"""Map worker entrypoint: bind render checks to an assembled schema-2 manifest.

No database registration or publication. Geography, routing and complex text
shaping remain separate acceptance gates.
"""
import hashlib
import os
from pathlib import Path
import stat

from app.services.map_glyph_validation import glyph_asset_range, inspect_glyph_range
from app.services.map_package_set import read_manifest
from app.services.map_sprite_validation import validate_sprite_scales
from app.services.map_style_dependencies import validate_style_dependencies
from app.services.vector_map_validation import validate_vector_mbtiles
from app.services.place_index_validation import validate_place_index
from app.services.map_font_profiles import font_profile
from app.services.map_label_contract import label_contract
from app.services.map_style_syntax import validate_style_syntax


def validate_render_bundle(directory: Path) -> dict:
    """Server-owned assembly directory only; run off the core request path."""
    manifest = read_manifest(directory)
    profile = font_profile(manifest)
    indexed = {a['name']: (index, a) for index, a in enumerate(manifest['assets'])}
    root = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        def read(name: str, limit: int) -> bytes:
            index, asset = indexed[name]
            if not 0 < asset['size_bytes'] <= limit:
                raise ValueError('invalid_render_asset_size')
            fd = os.open(f'asset-{index:04d}.bin', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=root)
            with os.fdopen(fd, 'rb') as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size != asset['size_bytes']:
                    raise ValueError('invalid_render_asset_file')
                content = source.read(asset['size_bytes'] + 1)
            if len(content) != asset['size_bytes'] or hashlib.sha256(content).hexdigest() != asset['sha256']:
                raise ValueError('render_asset_hash_mismatch')
            return content

        vectors = [(index, a) for index, a in enumerate(manifest['assets']) if a['role'] == 'vector']
        styles = [a for a in manifest['assets'] if a['role'] == 'style']
        if len(vectors) != 1 or len(styles) != 1:
            raise ValueError('ambiguous_render_assets')
        vector_index, asset = vectors[0]
        style_content = read(styles[0]['name'], 1024 * 1024)
        label_fields, literal_codepoints = label_contract(style_content)
        # This validator hash-copies the source before opening SQLite, so it
        # does not trust an assembly receipt or a caller's layer-name list.
        vector = validate_vector_mbtiles(directory / f'asset-{vector_index:04d}.bin',
            asset['sha256'], bounds=manifest['bounds'], min_zoom=manifest['min_zoom'],
            max_zoom=manifest['max_zoom'], label_fields=label_fields or None)
        if vector['size_bytes'] != asset['size_bytes']:
            raise ValueError('vector_asset_size_mismatch')
        glyphs = [a for a in manifest['assets'] if a['role'] == 'glyphs']
        expected = {f'glyphs-{start}-{start + 255}.pbf' for start in range(0, 65536, 256)}
        if not expected <= {a['name'] for a in glyphs}:
            raise ValueError('incomplete_render_glyph_ranges')
        ids, drawable = set(), set()
        for asset in glyphs:
            found, visible = inspect_glyph_range(read(asset['name'], 2 * 1024 * 1024),
                glyph_asset_range(asset['name']), fontstack=profile.fontstack)
            ids.update(found)
            drawable.update(visible)
        indexes = [a for a in manifest['assets'] if a['role'] == 'gazetteer']
        sources = [a for a in manifest['assets'] if a['role'] == 'road_source']
        regions = {a['sha256'] for a in manifest['assets'] if a['role'] == 'boundaries'}
        if len(indexes) != 1 or len(sources) != 1:
            raise ValueError('ambiguous_place_sources')
        places = validate_place_index(read(indexes[0]['name'], 64 * 1024 * 1024),
            source_sha256=sources[0]['sha256'], region_sha256=regions, bounds=manifest['bounds'])
        missing = set(places.pop('primary_codepoints')) - drawable
        if missing:
            raise ValueError('missing_primary_place_glyphs')
        sprite_names = {a['name'] for a in manifest['assets'] if a['role'] == 'sprite'}
        if sprite_names != {'sprite.json', 'sprite.png', 'sprite-2x.json', 'sprite-2x.png'}:
            raise ValueError('incomplete_render_sprite_pair')
        icons = validate_sprite_scales(read('sprite.json', 1024 * 1024),
            read('sprite.png', 16 * 1024 * 1024), read('sprite-2x.json', 1024 * 1024),
            read('sprite-2x.png', 16 * 1024 * 1024))
        style = validate_style_dependencies(style_content, manifest,
            source_layers=set(vector['layers']), sprite_names=icons)
        syntax = validate_style_syntax(style_content)
        label_audit = vector.get('label_audit', {})
        required = set(label_audit.get('codepoints', [])) | literal_codepoints
        if required - drawable:
            raise ValueError('missing_vector_label_glyphs')
        return {'status': 'render_content_validated', 'publish_ready': False,
                'bundle_id': manifest['bundle_id'], 'vector': vector, 'style': style,
                'glyph_ranges': len(glyphs), 'glyph_count': len(ids),
                'places': places, 'primary_place_font_coverage_verified': True,
                'label_codepoint_coverage_verified': True,
                'label_codepoint_count': len(required), 'text_shaping_verified': False,
                'sprite_icons': len(icons), 'road_topology_verified': False,
                'geographic_coverage_verified': False, 'font_coverage_verified': False,
                'style_syntax_verified': True, 'style_syntax': syntax}
    finally:
        os.close(root)
