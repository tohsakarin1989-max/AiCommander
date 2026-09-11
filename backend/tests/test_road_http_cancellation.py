import json
import os
import sys
from threading import Event

import anyio
import pytest
from starlette.requests import Request

from app.api import road_analysis as api
from app.services.vehicle_router import RoadCalculationError


def query():
    return api.RouteRequest.model_validate({'vehicle': {'kind': 'auto'},
        'start': {'longitude': 125., 'latitude': 46.},
        'end': {'longitude': 125.01, 'latitude': 46.}})


class Disconnected:
    async def is_disconnected(self):
        return True


@pytest.mark.asyncio
async def test_disconnect_signals_worker_and_releases_admission_slots():
    stopped = Event()
    def calculate(db, *, cancel_event, **kwargs):
        assert cancel_event.wait(2), 'disconnect was not delivered'
        stopped.set()
        raise RoadCalculationError('road_calculation_cancelled')
    with anyio.fail_after(3):
        response = await api._request_calculation(Disconnected(), calculate, None, query())
    assert stopped.is_set()
    assert response.status_code == 409
    assert json.loads(response.body)['detail']['code'] == 'road_calculation_cancelled'
    assert api._slots.acquire(blocking=False)
    assert api._slots.acquire(blocking=False)
    api._slots.release()
    api._slots.release()


@pytest.mark.asyncio
async def test_cancelled_asgi_scope_waits_for_worker_before_dependency_can_close():
    started, stopped = Event(), Event()
    class Connected:
        async def is_disconnected(self):
            return False
    def calculate(db, *, cancel_event, **kwargs):
        started.set()
        assert cancel_event.wait(2)
        stopped.set()
        raise RoadCalculationError('road_calculation_cancelled')
    with anyio.fail_after(3):
        async with anyio.create_task_group() as group:
            group.start_soon(api._request_calculation, Connected(), calculate, None, query())
            while not started.is_set():
                await anyio.sleep(.01)
            group.cancel_scope.cancel()
    assert stopped.is_set(), 'request returned while its database session was still in use'


@pytest.mark.asyncio
async def test_late_success_after_disconnect_is_not_delivered():
    def calculate(db, *, cancel_event, **kwargs):
        assert cancel_event.wait(2)
        return {'distance_m': 100, 'late_result': True}
    response = await api._request_calculation(Disconnected(), calculate, None, query())
    assert response.status_code == 409
    assert b'late_result' not in response.body


@pytest.mark.asyncio
async def test_disconnect_reaps_real_owned_subprocess_before_return(tmp_path):
    from app.services.road_worker_process import _run
    pid_file = tmp_path / 'owned-worker.pid'
    async def receive():
        if pid_file.exists():
            return {'type': 'http.disconnect'}
        await anyio.sleep_forever()
    def calculate(db, *, cancel_event, **kwargs):
        command = [sys.executable, '-c',
            'import os,sys,time; from pathlib import Path; '
            'Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(20)', str(pid_file)]
        return _run(command, {}, timeout_seconds=2, cancel_event=cancel_event)
    with anyio.fail_after(4):
        response = await api._request_calculation(Request({'type': 'http'}, receive), calculate, None, query())
    assert response.status_code == 409
    assert pid_file.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)
