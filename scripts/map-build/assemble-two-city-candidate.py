#!/usr/bin/env python3
"""Reproduce the 20260908 public candidate from fixed, previously built inputs.

Offline build-operator tool, not an API. No business data or current-map writes.
The resulting transport and assembly still require acceptance before publishing.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'backend'))
from app.services.map_package_builder import build_package
from app.services.map_package_materialize import _write_final, materialize_package
from app.services.map_package_set import MAX_SET_BYTES, _open_file, read_manifest, verify_directory

BOUNDS = [121.9954687124249, 45.11031168347853, 127.06370572422722, 49.19124651842884]
GLYPH_MANIFEST_SHA = '924bbcf67f2c71dd9f7db44eda80d5d365f97cd9256accffa486c8c9ef66d3fa'
COMPOSITE_GLYPH_MANIFEST_SHA = '3c8637c94a68f9f47fdd2c373435e3506492230c19e4a3914502a3a2198ae308'
FONT_LICENSE_SHA = '6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2'
MONGOLIAN_LICENSE_SHA = 'b0158b3c0b16c20e22ea662850503a7980111c5c704501e942cc1a7ed12dc011'
EMOJI_LICENSE_SHA = '500bb1ccf43df7bbb522112f9133a52b16e1c35e809632f5d8609b179152de5b'
FIXED = [
    ('vector-candidate-v2/two-city.mbtiles', 'two-city.mbtiles', 'vector', '57ac644ba0ce3a57f88339839f7a737bfb797ae324a4f4afdeadf2a5c34e4b4d'),
    ('vector-candidate-v2/places.sqlite', 'places.sqlite', 'gazetteer', 'a3ccdf144f53be542480e1533c9df946b898786d9422e4eb75dfafb645242839'),
    ('merged-three-regions-v1/merged.osm.pbf', 'public-source.osm.pbf', 'road_source', '7571b3f8838f55816c1565fdc84138f7a08d582220f830e6acdf4e0b338f5f8b'),
    ('two-city-region-v3/extraction-region.geojson', 'extraction-region.geojson', 'boundaries', '2093e9a5284ea0de0389be32b929bd42630d341e03fbdb3b1738f1ae1bb29d49'),
    ('two-city-region-v3/city-boundaries.geojson', 'city-boundaries.geojson', 'boundaries', 'ef9f162093c0368e55b3933597b3c6132ce1766c498113057b76332b2badd82d'),
]
EXPORT_STYLE = """
import ts from 'typescript';
import {readFile} from 'node:fs/promises';
import {validateStyleMin} from '@maplibre/maplibre-gl-style-spec';
let input=''; for await(const c of process.stdin) input+=c;
const {bounds,fontProfile}=JSON.parse(input);
const compiled=ts.transpileModule(await readFile('src/components/Map/offlineVectorStyle.ts','utf8'),
 {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}});
const module=await import('data:text/javascript;base64,'+Buffer.from(compiled.outputText).toString('base64'));
const style=module.createOfflineVectorStyle('12345678-1234-1234-1234-123456789abc',bounds,fontProfile);
if(validateStyleMin(style).length) throw new Error('invalid frontend style');
delete style.metadata['aic:snapshot-id'];
style.glyphs='aic-map://glyphs/{fontstack}/{range}.pbf';
style.sources.public.tiles=['aic-map://public/{z}/{x}/{y}'];
if(validateStyleMin(style).length) throw new Error('invalid transport style');
console.log(JSON.stringify(style));
"""


def open_source(path):
    root = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        fd = _open_file(root, str(path.absolute())[1:])
    finally:
        os.close(root)
    stream = os.fdopen(fd, 'rb')
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_SET_BYTES:
        stream.close()
        raise ValueError('invalid_source_file')
    return stream


def asset(path, name, role, expected, license_record, attribution):
    with open_source(path) as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        size = os.fstat(stream.fileno()).st_size
    if expected != digest:
        raise ValueError('source_hash_mismatch')
    return dict(name=name, role=role, path=str(path), sha256=digest,
                size_bytes=size, license=license_record, attribution=attribution)


def fixed_json(path, expected):
    """Hash and parse the same bounded bytes, never reopen an unbound manifest."""
    with open_source(path) as source:
        content = source.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != expected:
        raise ValueError('source_hash_mismatch')
    return json.loads(content)


def assemble(source, output, *, font_profile='cjk-v1'):
    from app.services.map_font_profiles import font_profile as get_profile
    profile = get_profile({'font_profile': font_profile})
    composite = font_profile == 'cjk-mongolian-emoji-v1'
    source, output = source.absolute(), output.absolute()
    public = 'OpenStreetMap contributors; Geofabrik extracts 20260908'
    assets = [asset(source / rel, name, role, digest, 'ODbL-1.0', public)
              for rel, name, role, digest in FIXED]
    glyph_folder = 'glyphs-composite-v1' if composite else 'glyphs-cjk-v1'
    glyph_manifest = source / glyph_folder / 'glyph-manifest.json'
    glyph_report = fixed_json(glyph_manifest, COMPOSITE_GLYPH_MANIFEST_SHA if composite else GLYPH_MANIFEST_SHA)
    if glyph_report['fontstack'] != profile.fontstack:
        raise ValueError('invalid_fixed_glyph_manifest')
    glyphs = glyph_report['files']
    font_attribution = 'Noto CJK, Mongolian and Emoji contributors' if composite else 'Noto CJK contributors'
    expected_names = {f'{i}-{i+255}.pbf' for i in range(0, 65536, 256)}
    if composite:
        expected_names.add('127744-127999.pbf')
    if len(glyphs) != len(expected_names) or {g['name'] for g in glyphs} != expected_names:
        raise ValueError('invalid_fixed_glyph_manifest')
    for glyph in glyphs:
        assets.append(asset(source / glyph_folder / profile.fontstack / glyph['name'],
                            f"glyphs-{glyph['name']}", 'glyphs', glyph['sha256'], 'OFL-1.1', font_attribution))
    assets.append(asset(source / 'fonts-sans2.004/LICENSE', 'noto-ofl.txt', 'license',
                        FONT_LICENSE_SHA, 'OFL-1.1', 'Noto CJK contributors'))
    if composite:
        for rel, name, expected in [
            ('fonts-fallback-v1/mongolian/OFL.txt', 'noto-mongolian-ofl.txt', MONGOLIAN_LICENSE_SHA),
            ('fonts-fallback-v1/NotoEmoji-OFL.txt', 'noto-emoji-ofl.txt', EMOJI_LICENSE_SHA),
        ]:
            assets.append(asset(source / rel, name, 'license', expected, 'OFL-1.1', 'Noto contributors'))
    exported = subprocess.run(['node', '--input-type=module', '-e', EXPORT_STYLE],
                              cwd=REPO / 'frontend', input=json.dumps({'bounds': BOUNDS, 'fontProfile': font_profile}),
                              capture_output=True, text=True, timeout=30, check=True)
    style = json.loads(exported.stdout)
    from PIL import Image
    png = io.BytesIO()
    Image.new('RGBA', (1, 1), (0, 0, 0, 0)).save(png, format='PNG')
    generated = {'style.json': json.dumps(style, ensure_ascii=False).encode(),
                 'sprite.json': b'{}', 'sprite-2x.json': b'{}',
                 'sprite.png': png.getvalue(), 'sprite-2x.png': png.getvalue()}
    output.mkdir(mode=0o700)  # new candidate only; failures retained without receipt
    for name, content in generated.items():
        _write_final(output / name, content)
        assets.append(asset(output / name, name, 'style' if name == 'style.json' else 'sprite',
                            hashlib.sha256(content).hexdigest(), 'project-generated', 'AiCommander'))
    recipe = dict(schema_version='2.0', bundle_id='daqing-qiqihar-20260908-candidate-v3' if composite else 'daqing-qiqihar-20260908-candidate-v2',
                  source_version='2026-09-08T20:21:01Z', provider='OpenStreetMap via Geofabrik',
                  license='ODbL-1.0; OFL-1.1; OpenMapTiles schema CC-BY-4.0',
                  attribution=public + '; OpenMapTiles contributors; ' + font_attribution,
                  contains_internal_data=False, bounds=BOUNDS, min_zoom=6, max_zoom=16,
                  display_max_zoom=19, assets=assets)
    if composite:
        recipe['font_profile'] = font_profile
    _write_final(output / 'recipe.json', json.dumps(recipe, ensure_ascii=False, indent=2).encode())
    report = build_package(recipe, output / 'transport')
    manifest = read_manifest(output / 'transport')
    if verify_directory(output / 'transport', manifest)['status'] != 'integrity_verified':
        raise ValueError('transport_readback_failed')
    assembled = materialize_package(output / 'transport', manifest, output)
    report.update(assembly=assembled.name, style_syntax_verified=True,
                  note='Render, geography, font coverage and routing acceptance still required')
    _write_final(output / 'build-receipt.json', json.dumps(report, ensure_ascii=False).encode())
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--font-profile', choices=['cjk-v1', 'cjk-mongolian-emoji-v1'], default='cjk-v1')
    args = parser.parse_args()
    print(json.dumps(assemble(args.source, args.output, font_profile=args.font_profile), ensure_ascii=False))
