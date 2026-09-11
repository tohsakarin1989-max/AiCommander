import copy
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.services.road_expansion_paths import time_expansion_paths, iter_time_expansion_paths
from app.services.vehicle_router import RoadCalculationError
from test_road_reachability_geometry import expansion


def test_geometry_import_does_not_load_business_database_or_secrets(tmp_path):
    environment = {key: value for key, value in os.environ.items() if key != 'SECRET_KEY'}
    environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run([sys.executable, '-c',
        "import sys; from app.services.road_polyline import decode_road_geometry; "
        "from app.services.road_time_geometry import clip_timed_path; "
        "assert 'app.database' not in sys.modules; assert 'app.config' not in sys.modules"],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def timed_expansion():
    raw = expansion()
    for feature, duration in zip(raw['features'], (5, 5, 60)):
        feature['properties']['duration'] = duration
    return raw


def test_branches_start_at_correlated_seed_and_follow_exact_ids():
    raw = timed_expansion()
    before = copy.deepcopy(raw)
    paths = time_expansion_paths(raw, {1: .5, 2: .5}, 30)
    assert [path['edge_ids'] for path in paths] == [[1], [2, 3]]
    assert all(path['points'][0] == [124.9995, 46.] for path in paths)
    assert raw == before


@pytest.mark.parametrize('fault', ['cycle', 'missing_parent', 'disconnected', 'nan', 'duplicate', 'missing_seed'])
def test_broken_branch_is_not_repaired_by_nearest_road(fault):
    raw, seeds = timed_expansion(), {1: .5, 2: .5}
    prop = raw['features'][-1]['properties']
    if fault == 'cycle':
        prop['pred_edge_id'] = 3
        prop['duration'] = 1
    elif fault == 'missing_parent':
        prop['pred_edge_id'] = 999
    elif fault == 'disconnected':
        raw['features'][-1]['geometry']['coordinates'][0][0] += .01
    elif fault == 'nan':
        prop['duration'] = float('nan')
    elif fault == 'duplicate':
        raw['features'].append(copy.deepcopy(raw['features'][0]))
    else:
        seeds.pop(1)
    with pytest.raises(RoadCalculationError):
        time_expansion_paths(raw, seeds, 30)


def test_capacity_limit_is_not_reported_as_corrupt_graph():
    raw = timed_expansion()
    root = raw['features'][0]
    raw['features'] = []
    for identifier in range(1, 4098):
        edge = copy.deepcopy(root)
        edge['properties']['edge_id'] = identifier
        raw['features'].append(edge)
    with pytest.raises(RoadCalculationError, match='^road_calculation_capacity_exceeded$'):
        time_expansion_paths(raw, {identifier: .5 for identifier in range(1, 4098)}, 30)


def test_streaming_still_rejects_late_unrooted_component():
    raw = timed_expansion()
    raw['features'][-1]['properties']['pred_edge_id'] = 3
    raw['features'][-1]['properties']['duration'] = 1
    iterator = iter_time_expansion_paths(raw, {1: .5, 2: .5}, 30)
    assert iter(iterator) is iterator
    assert next(iterator)['edge_ids'] == [1]
    with pytest.raises(RoadCalculationError, match='road_engine_response_invalid'):
        list(iterator)
