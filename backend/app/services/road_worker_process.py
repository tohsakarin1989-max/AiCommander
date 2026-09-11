"""Bounded local subprocess transport. Command and paths are server-controlled."""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from app.services.vehicle_router import RoadCalculationError


MAX_RESULT_BYTES = 4 * 1024 * 1024
ERROR_CODES = frozenset({
    'road_engine_unavailable', 'road_engine_version_mismatch', 'road_engine_calculation_failed',
    'road_engine_response_invalid', 'road_route_connection_unverified',
    'road_location_connection_unverified', 'road_vehicle_dimensions_missing',
    'road_worker_input_invalid',
    'road_calculation_capacity_exceeded',
})


def _run(command, payload, *, timeout_seconds, expected_schema='vehicle-route-4.2.0-1', cancel_event=None):
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 120):
        raise ValueError('road_worker_timeout_invalid')
    encoded = json.dumps(payload, allow_nan=False).encode()
    if len(encoded) > 65536:
        raise ValueError('road_worker_input_too_large')
    if cancel_event is not None and cancel_event.is_set():
        raise RoadCalculationError('road_calculation_cancelled')
    # A private anonymous input file avoids a blocked stdin pipe while polling
    # cancellation. The fixed-size request is written once, not resent.
    with tempfile.TemporaryFile() as request_input, tempfile.TemporaryFile() as output:
        request_input.write(encoded)
        request_input.seek(0)
        try:
            process = subprocess.Popen(command, stdin=request_input, stdout=output,
                stderr=subprocess.DEVNULL, start_new_session=True,
                cwd=Path(__file__).resolve().parents[2])
        except OSError as error:
            raise RoadCalculationError('road_engine_unavailable') from error
        try:
            deadline = time.monotonic() + timeout_seconds
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise RoadCalculationError('road_calculation_cancelled')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RoadCalculationError('road_calculation_timeout')
                try:
                    process.wait(timeout=min(.1, remaining) if cancel_event is not None else remaining)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if cancel_event is not None and cancel_event.is_set():
                raise RoadCalculationError('road_calculation_cancelled')
        finally:
            # Reap the owned process and any descendants even on interruption.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        if process.returncode != 0:
            raise RoadCalculationError('road_engine_calculation_failed')
        output.seek(0)
        raw = output.read(MAX_RESULT_BYTES + 1)
    if len(raw) > MAX_RESULT_BYTES:
        raise RoadCalculationError('road_engine_response_invalid')
    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise RoadCalculationError('road_engine_response_invalid') from error
    if not isinstance(envelope, dict):
        raise RoadCalculationError('road_engine_response_invalid')
    if 'error' in envelope:
        code = envelope['error']
        raise RoadCalculationError(code if isinstance(code, str) and code in ERROR_CODES
                                   else 'road_engine_calculation_failed')
    result = envelope.get('result')
    if not isinstance(result, dict) or result.get('schema_version') != expected_schema:
        raise RoadCalculationError('road_engine_response_invalid')
    if cancel_event is not None and cancel_event.is_set():
        raise RoadCalculationError('road_calculation_cancelled')
    return result


def run_route_process(tiles, start, end, vehicle, *, timeout_seconds=120, cancel_event=None):
    return _run([sys.executable, '-m', 'app.services.road_router_worker'],
                {'tiles': str(Path(tiles).resolve()), 'start': start.model_dump(),
                 'end': end.model_dump(), 'vehicle': vehicle.model_dump()},
                timeout_seconds=timeout_seconds, cancel_event=cancel_event)


def run_time_path_process(tiles, start, end, vehicle, seconds, *, timeout_seconds=120, cancel_event=None):
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 7200:
        raise ValueError('road_reachability_budget_invalid')
    return _run([sys.executable, '-m', 'app.services.road_router_worker'],
                {'operation': 'time_path', 'tiles': str(Path(tiles).resolve()),
                 'start': start.model_dump(), 'end': end.model_dump(),
                 'vehicle': vehicle.model_dump(), 'seconds': seconds},
                timeout_seconds=timeout_seconds, expected_schema='vehicle-time-path-4.2.0-1',
                cancel_event=cancel_event)


def run_time_reachability_process(tiles, origin, vehicle, seconds, *, timeout_seconds=120, cancel_event=None):
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 7200:
        raise ValueError('road_reachability_budget_invalid')
    return _run([sys.executable, '-m', 'app.services.road_router_worker'],
                {'operation': 'time_reachability', 'tiles': str(Path(tiles).resolve()),
                 'origin': origin.model_dump(), 'vehicle': vehicle.model_dump(), 'seconds': seconds},
                timeout_seconds=timeout_seconds, expected_schema='vehicle-time-reachability-4.2.0-1',
                cancel_event=cancel_event)


def run_matrix_process(tiles, sources, targets, vehicle, *, timeout_seconds=120, cancel_event=None):
    if not 1 <= len(sources) <= 10 or not 1 <= len(targets) <= 10:
        raise ValueError('road_matrix_size_invalid')
    return _run([sys.executable, '-m', 'app.services.road_router_worker'],
                {'operation': 'matrix', 'tiles': str(Path(tiles).resolve()),
                 'sources': [point.model_dump() for point in sources],
                 'targets': [point.model_dump() for point in targets], 'vehicle': vehicle.model_dump()},
                timeout_seconds=timeout_seconds, expected_schema='vehicle-matrix-4.2.0-1', cancel_event=cancel_event)


def run_distance_reachability_process(tiles, origin, vehicle, distance_m, *, timeout_seconds=120, cancel_event=None):
    if (type(distance_m) not in (int, float) or not math.isfinite(distance_m)
            or not 0 < distance_m <= 50000):
        raise ValueError('road_reachability_budget_invalid')
    return _run([sys.executable, '-m', 'app.services.road_router_worker'],
                {'operation': 'distance_reachability', 'tiles': str(Path(tiles).resolve()),
                 'origin': origin.model_dump(), 'vehicle': vehicle.model_dump(), 'distance_m': distance_m},
                timeout_seconds=timeout_seconds, expected_schema='vehicle-distance-reachability-4.2.0-2',
                cancel_event=cancel_event)
