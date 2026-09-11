import json
import os
from pathlib import Path
import sys
import time
import threading

import pytest

from app.services import road_worker_process as worker
from app.services.road_access_policy import VehicleAssumption
from app.services.vehicle_router import RoadCalculationError, RoadLocation


def command(response):
    return [sys.executable, '-c', f'print({json.dumps(response)!r})']


def test_real_child_protocol():
    expected = {'schema_version': 'vehicle-route-4.2.0-1', 'distance_m': 20}
    assert worker._run(command({'result': expected}), {}, timeout_seconds=5) == expected


@pytest.mark.parametrize('cancel_polling', [False, True])
def test_timeout_reaps_real_child(monkeypatch, cancel_polling):
    processes = []
    original = worker.subprocess.Popen

    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(worker.subprocess, 'Popen', capture)
    start = time.monotonic()
    with pytest.raises(RoadCalculationError, match='road_calculation_timeout'):
        worker._run([sys.executable, '-c', 'import time; time.sleep(60)'], {}, timeout_seconds=.1,
                    cancel_event=threading.Event() if cancel_polling else None)
    assert time.monotonic() - start < 5
    assert processes[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.kill(processes[0].pid, 0)


@pytest.mark.parametrize('response, code', [
    ({'error': 'road_engine_unavailable'}, 'road_engine_unavailable'),
    ({'error': 'private path and coordinates'}, 'road_engine_calculation_failed'),
    ({'result': {}}, 'road_engine_response_invalid'),
    ([], 'road_engine_response_invalid'),
])
def test_failure_or_bad_protocol_has_no_route(response, code):
    with pytest.raises(RoadCalculationError, match=f'^{code}$'):
        worker._run(command(response), {}, timeout_seconds=5)


def test_native_exit_cannot_be_read_as_success():
    with pytest.raises(RoadCalculationError, match='road_engine_calculation_failed'):
        worker._run([sys.executable, '-c', 'raise SystemExit(1)'], {}, timeout_seconds=5)


def test_cancelled_before_start_never_spawns(monkeypatch):
    event = threading.Event()
    event.set()
    def forbidden(*args, **kwargs):
        pytest.fail('cancelled work must not spawn')
    monkeypatch.setattr(worker.subprocess, 'Popen', forbidden)
    with pytest.raises(RoadCalculationError, match='road_calculation_cancelled'):
        worker._run(command({}), {}, timeout_seconds=5, cancel_event=event)


def test_running_cancellation_reaps_real_process(monkeypatch):
    processes = []
    event = threading.Event()
    original = worker.subprocess.Popen
    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(worker.subprocess, 'Popen', capture)
    timer = threading.Timer(.15, event.set)
    timer.start()
    try:
        with pytest.raises(RoadCalculationError, match='road_calculation_cancelled'):
            worker._run([sys.executable, '-c', 'import time; time.sleep(60)'], {},
                        timeout_seconds=5, cancel_event=event)
    finally:
        timer.cancel()
        timer.join()
    assert len(processes) == 1 and processes[0].poll() is not None
    with pytest.raises(ProcessLookupError):
        os.kill(processes[0].pid, 0)


def test_cancel_polling_does_not_duplicate_request_input():
    code = ('import json,sys,time; time.sleep(.25); x=json.load(sys.stdin); '
            'print(json.dumps({"result":{"schema_version":"vehicle-route-4.2.0-1","received":x}}))')
    payload = {'data': 'a' * 30000}
    result = worker._run([sys.executable, '-c', code], payload, timeout_seconds=5, cancel_event=threading.Event())
    assert result['received'] == payload


@pytest.mark.skipif(not os.environ.get('AIC_REAL_ROAD_GRAPH'), reason='requires real frozen graph and engine')
def test_real_engine_route_through_isolated_worker():
    result = worker.run_route_process(Path(os.environ['AIC_REAL_ROAD_GRAPH']),
        RoadLocation(longitude=125.1852727, latitude=46.54446175),
        RoadLocation(longitude=125.18509545, latitude=46.5444392),
        VehicleAssumption(kind='auto', source='explicit_reference_assumption'), timeout_seconds=30)
    assert result['distance_m'] > 100
    ways = result['way_ids']
    assert ways[0] == 1550481791 and ways[-1] == 1550481790
    assert (1550481791, 1550481790) not in list(zip(ways, ways[1:]))
