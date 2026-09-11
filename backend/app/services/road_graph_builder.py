"""Local fixed-version graph compilation; no public API or automatic publication.

Source PBF must already be prepared by the permission-aware source compiler.
Paths are administrator/job configuration only. Failed jobs keep their own output
for inspection and never replace an existing graph or the current map.
"""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess

from app.services.road_graph_artifact import graph_inventory_sha256
from app.services.vehicle_router import ENGINE_VERSION, RoadCalculationError


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def compile_local_graph(source_pbf: Path, output: Path, *, expected_source_sha256: str):
    if importlib.metadata.version('pyvalhalla') != ENGINE_VERSION:
        raise RoadCalculationError('road_engine_version_mismatch')
    from valhalla import PYVALHALLA_DIR
    from valhalla.config import get_config
    source_pbf = Path(source_pbf).resolve(strict=True)
    if not source_pbf.is_file() or _digest(source_pbf) != expected_source_sha256:
        raise ValueError('road_graph_source_checksum_mismatch')
    output = Path(output)
    output.mkdir(exist_ok=False)
    tiles = output / 'tiles'
    tiles.mkdir()
    config = get_config(tile_dir=str(tiles), tile_extract='')
    config['mjolnir'].update(tile_url='', traffic_extract='', admin='', timezone='',
                             include_pedestrian=False, include_bicycle=False)
    config['mjolnir']['data_processing'].update(use_admin_db=False, apply_country_overrides=False,
                                               infer_internal_intersections=False, infer_turn_channels=False)
    config_path = output / 'config.json'
    config_path.write_text(json.dumps(config))
    try:
        with (output / 'build.log').open('wb') as log:
            subprocess.run([str(PYVALHALLA_DIR / 'bin' / 'valhalla_build_tiles'), '-j', '1',
                            '-c', str(config_path.resolve()), str(source_pbf)],
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)
    except (subprocess.SubprocessError, OSError) as error:
        raise RoadCalculationError('road_graph_build_failed') from error
    if _digest(source_pbf) != expected_source_sha256:
        raise ValueError('road_graph_source_changed_during_build')
    result = {'schema_version': 'road-graph-build-4.2.0-1', 'engine_version': ENGINE_VERSION,
              'source_sha256': expected_source_sha256, 'graph_sha256': graph_inventory_sha256(tiles),
              'config_sha256': _digest(config_path), 'status': 'built_not_published',
              'source_eligibility_certified': False}
    (output / 'build-manifest.json').write_text(json.dumps(result, indent=2))
    return result
