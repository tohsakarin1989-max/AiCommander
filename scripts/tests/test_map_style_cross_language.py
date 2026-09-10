"""The actual frontend style must satisfy backend local-resource rules."""
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from app.services.map_style_dependencies import bind_style_snapshot, validate_style_dependencies
from tests.test_map_style_dependencies import inputs, SNAPSHOT


def test_current_frontend_style_survives_package_binding(tmp_path):
    frontend = Path(__file__).resolve().parents[2] / 'frontend'
    script = """
import ts from 'typescript';
import {readFile} from 'node:fs/promises';
import {validateStyleMin} from '@maplibre/maplibre-gl-style-spec';
const result = ts.transpileModule(await readFile('src/components/Map/offlineVectorStyle.ts','utf8'),
  {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}});
const module = await import('data:text/javascript;base64,'+Buffer.from(result.outputText).toString('base64'));
const style = module.createOfflineVectorStyle('12345678-1234-1234-1234-123456789abc',[122,45,127,50]);
if (validateStyleMin(style).length) throw new Error('invalid frontend style');
style.glyphs='aic-map://glyphs/{fontstack}/{range}.pbf';
style.sources.public.tiles=['aic-map://public/{z}/{x}/{y}'];
console.log(JSON.stringify(style));
"""
    output = subprocess.run(['node', '--input-type=module', '-e', script], cwd=frontend,
                            capture_output=True, text=True, timeout=20)
    assert output.returncode == 0, output.stderr
    style = json.loads(output.stdout)
    _, manifest = inputs(tmp_path)
    source_layers = {layer['source-layer'] for layer in style['layers'] if 'source-layer' in layer}
    report = validate_style_dependencies(output.stdout.encode(), manifest,
                                        source_layers=source_layers, sprite_names=set())
    assert report['layer_count'] == 14
    bound = bind_style_snapshot(output.stdout.encode(), manifest, SNAPSHOT,
                               source_layers=source_layers, sprite_names=set())
    assert bound['sources']['public']['tiles'] == [f'/api/maps/tiles/{SNAPSHOT}/{{z}}/{{x}}/{{y}}']
    validator = """
import {validateStyleMin} from '@maplibre/maplibre-gl-style-spec';
let content=''; for await (const chunk of process.stdin) content+=chunk;
console.log(JSON.stringify(validateStyleMin(JSON.parse(content))));
"""
    checked = subprocess.run(['node', '--input-type=module', '-e', validator], cwd=frontend,
        input=json.dumps(bound), capture_output=True, text=True, timeout=10, check=True)
    assert json.loads(checked.stdout) == []
