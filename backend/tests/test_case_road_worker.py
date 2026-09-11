"""Opt-in real Redis and independent Celery worker integration, synthetic DB."""
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import uuid

import pytest
from celery import Celery
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.case_pipeline import OutboxEvent
from app.models.case_road_artifact import CaseRoadArtifact
from app.models.map_foundation import MapSnapshotFeature
from app.models.road_network import RoadNetworkVersion
from app.services.case_result_service import CaseResultService
from app.services.road_graph_artifact import graph_inventory_sha256, install_graph_artifact
from app.services.case_road_artifact_service import read_road_artifact
from test_road_network_service import ready  # noqa: F401
from test_case_results import db_session, result_data  # noqa: F401
from test_case_road_triggers import source_event


@pytest.mark.skipif(os.environ.get('AIC_DISPOSABLE_ROAD_REDIS') != '1', reason='owned Redis drill opt-in required')
@pytest.mark.parametrize('broker_loss', [False, True])
def test_real_broker_worker_restart_preserves_pending_native_comparison(ready, result_data, tmp_path, broker_loss):
    broker = os.environ['AIC_ROAD_TEST_REDIS_URL']
    assert re.fullmatch(r'redis://127\.0\.0\.1:\d+/0', broker)
    graph_path = Path(os.environ['AIC_ROAD_TEST_GRAPH']).resolve(strict=True)
    graph_hash = graph_inventory_sha256(graph_path)
    packages = tmp_path / 'packages'
    install_graph_artifact(graph_path, packages / 'road-graphs', expected_sha256=graph_hash)
    db = ready
    graph = db.get(RoadNetworkVersion, 'graph-1')
    graph.engine_version, graph.graph_sha256, graph.artifact_key = '3.8.3', graph_hash, graph_hash
    profile, run, _ = result_data
    profile.payload = {**profile.payload, 'analysis_facts': {
        'latitude': 46.54446175, 'longitude': 125.1852727}}
    feature = db.scalar(select(MapSnapshotFeature).where(MapSnapshotFeature.asset_id == 1))
    feature.latitude, feature.longitude = 46.5444392, 125.18509545
    db.commit()
    source_event(db, profile)
    result_id, _ = CaseResultService.freeze_completed_inputs(db, profile, run)
    db.commit()
    database = tmp_path / 'isolated.sqlite3'
    with sqlite3.connect(database) as destination:
        db.connection().connection.driver_connection.backup(destination)
    db.rollback()
    factory = sessionmaker(bind=create_engine(f'sqlite:///{database}'), autoflush=False)
    env = dict(os.environ, DATABASE_URL=f'sqlite:///{database}',
        CELERY_BROKER_URL=broker, CELERY_RESULT_BACKEND=broker, REDIS_URL=broker,
        MAP_PACKAGE_ROOT=str(packages), ENVIRONMENT='test', ENABLE_VECTOR_DB='false',
        SECRET_KEY='synthetic-independent-road-worker-not-production')
    root = Path(__file__).resolve().parents[1]
    sender = Celery('road_worker_test_sender', broker=broker, backend=broker)
    worker = None
    beat = None
    log_path = tmp_path / 'worker.log'
    def start_worker():
        with log_path.open('ab') as log:
            if os.environ.get('AIC_ROAD_WORKER_IMAGE'):
                name = f'aic-road-worker-{uuid.uuid4()}'
                marker = os.environ['AIC_ROAD_TEST_CONTAINER_MARKER']
                container_env = {
                    'DATABASE_URL': 'sqlite:////test/isolated.sqlite3',
                    'REDIS_URL': 'redis://road-test-redis:6379/0',
                    'MAP_PACKAGE_ROOT': '/test/packages', 'ENVIRONMENT': 'test',
                    'ENABLE_VECTOR_DB': 'false', 'SECRET_KEY': env['SECRET_KEY'],
                }
                options = [item for key, value in container_env.items() for item in ('-e', f'{key}={value}')]
                process = subprocess.Popen(['docker', 'run', '--rm', '--init', '--name', name,
                    '--label', f'aic.road-worker-child={marker}', '--network', os.environ['AIC_ROAD_TEST_NETWORK'],
                    '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                    '--user', f'{os.getuid()}:{os.getgid()}', '--tmpfs', '/tmp:rw,size=256m,mode=1777',
                    '--mount', f'type=bind,source={tmp_path},target=/test',
                    '--mount', f'type=bind,source={packages},target=/test/packages,readonly',
                    *options, os.environ['AIC_ROAD_WORKER_IMAGE'], 'python', '-m', 'celery',
                    '-A', 'app.tasks.celery_app:celery_app', 'worker', '--concurrency=1',
                    '--queues=road_analysis', '--without-gossip', '--without-mingle',
                    '--without-heartbeat', '--loglevel=WARNING'], stdout=log, stderr=subprocess.STDOUT)
                process.road_container_name = name
                return process
            return subprocess.Popen([sys.executable, '-m', 'celery', '-A', 'app.tasks.celery_app:celery_app',
                'worker', '--pool=solo', '--concurrency=1', '--queues=road_analysis',
                '--without-gossip', '--without-mingle', '--without-heartbeat', '--loglevel=WARNING'],
                cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
    def stop_worker(process):
        if getattr(process, 'road_container_name', None):
            subprocess.run(['docker', 'stop', '-t', '10', process.road_container_name],
                           capture_output=True, check=True, timeout=20)
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    def send():
        return sender.send_task('aicommander.case_roads.process_next', queue='road_analysis')
    try:
        first = send()  # Message is queued before a worker exists.
        worker = start_worker()
        handed_off = first.get(timeout=45)
        assert handed_off['status'] == 'completed'
        job_id = handed_off['job']['event_id']
        stop_worker(worker)
        worker = None
        with factory() as check:
            assert check.get(OutboxEvent, job_id).status == 'pending'
            assert check.query(CaseRoadArtifact).count() == 0
        second = send()  # Survives an actual independent worker replacement.
        if broker_loss:
            from redis import Redis
            connection = Redis.from_url(broker)
            assert connection.llen('road_analysis') > 0
            container = os.environ['AIC_ROAD_TEST_CONTAINER']
            marker = os.environ['AIC_ROAD_TEST_CONTAINER_MARKER']
            assert re.fullmatch('[a-f0-9]{64}', container)
            label = subprocess.run(['docker', 'inspect', '--format',
                '{{ index .Config.Labels "aic.road-worker-drill" }}', container],
                capture_output=True, text=True, check=True, timeout=10).stdout.strip()
            assert label == marker and marker
            subprocess.run(['docker', 'restart', container], capture_output=True, check=True, timeout=20)
            endpoint = subprocess.run(['docker', 'port', container, '6379'], capture_output=True,
                text=True, check=True, timeout=10).stdout.strip()
            assert broker == f'redis://{endpoint}/0', 'test_redis_endpoint_changed_during_restart'
            deadline = time.monotonic() + 10
            while True:
                try:
                    connection.ping()
                    break
                except Exception:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.2)
            assert connection.llen('road_analysis') == 0  # Confirm actual message loss.
            connection.close()
        worker = start_worker()
        if broker_loss:
            with log_path.open('ab') as log:
                beat = subprocess.Popen([sys.executable, '-m', 'celery', '-A', 'app.tasks.celery_app:celery_app',
                    'beat', '--schedule', str(tmp_path / 'beat-state'), '--loglevel=WARNING'],
                    cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 40
            while True:
                with factory() as check:
                    artifact_id = check.scalar(select(CaseRoadArtifact.id))
                    event = check.get(OutboxEvent, job_id)
                    if artifact_id and event.status == 'completed':
                        calculated = {'event_id': job_id, 'outcome': 'calculated', 'artifact': {'id': artifact_id}}
                        break
                assert worker.poll() is None and beat.poll() is None
                assert time.monotonic() < deadline, 'real_beat_did_not_recover_database_job'
                time.sleep(.2)
        else:
            calculated = second.get(timeout=45)
        assert calculated['event_id'] == job_id and calculated['outcome'] == 'calculated'
        assert send().get(timeout=30) == {'selected': 0}
        with factory() as check:
            check.info.update(principal_user_id=1, authorized_area_ids=(1,))
            artifact = read_road_artifact(check, calculated['artifact']['id'])
            assert artifact['content']['result_id'] == result_id
            matrix = artifact['content']['matrix']
            assert matrix['engine_version'] == '3.8.3' and matrix['graph_sha256'] == graph_hash
            assert 600 < matrix['cells'][0]['distance_m'] < 800
            assert check.query(CaseRoadArtifact).count() == 1
    finally:
        if beat is not None and beat.poll() is None:
            stop_worker(beat)
        if worker is not None and worker.poll() is None:
            stop_worker(worker)
        sender.close()
        factory.kw['bind'].dispose()
