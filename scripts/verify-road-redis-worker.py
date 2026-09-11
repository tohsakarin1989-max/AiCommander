"""Owned loopback Redis + independent worker drill; never use business Redis."""
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import uuid


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=kwargs.pop('timeout', 30),
                          **kwargs).stdout.strip()


def main():
    if os.environ.get('AIC_DISPOSABLE_ROAD_REDIS') != '1':
        raise RuntimeError('explicit_disposable_redis_opt_in_required')
    root = Path(__file__).resolve().parents[1]
    evidence = Path(tempfile.mkdtemp(prefix='road-redis-worker-', dir=root / 'output/validation'))
    (evidence / 'report.json').write_text(json.dumps({'passed': False, 'status': 'started'}))
    marker = str(uuid.uuid4())
    image = run('docker', 'image', 'inspect', '--format', '{{.Id}}', 'redis:7-alpine')
    worker_image = os.environ.get('AIC_ROAD_WORKER_IMAGE')
    network = None
    if worker_image:
        worker_image = run('docker', 'image', 'inspect', '--format', '{{.Id}}', worker_image)
        network = run('docker', 'network', 'create', '--internal', '--label',
                      f'aic.road-worker-drill={marker}', f'aic-road-drill-{marker}')
    # Select an unused port, then publish that explicit port. Docker's automatic
    # host-port assignment is not a stable service endpoint across restarts.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    container = run('docker', 'run', '--rm', '-d', '--label', f'aic.road-worker-drill={marker}',
                    '-p', f'127.0.0.1:{port}:6379', image,
                    'redis-server', '--save', '', '--appendonly', 'no')
    if not re.fullmatch('[a-f0-9]{64}', container):
        raise RuntimeError('unexpected_container_identifier')
    try:
        if network:
            # Host test sender uses loopback; worker only joins the internal net.
            run('docker', 'network', 'connect', '--alias', 'road-test-redis', network, container)
        endpoint = run('docker', 'port', container, '6379')
        if not re.fullmatch(r'127\.0\.0\.1:\d+', endpoint):
            raise RuntimeError('redis_not_loopback_only')
        assert run('docker', 'exec', container, 'redis-cli', 'ping') == 'PONG'
        env = dict(os.environ, AIC_ROAD_TEST_REDIS_URL=f'redis://{endpoint}/0',
            AIC_ROAD_TEST_CONTAINER=container, AIC_ROAD_TEST_CONTAINER_MARKER=marker,
            AIC_ROAD_TEST_GRAPH=str(root / 'output/validation/node-access-9yuyxfup/compiled/tiles'))
        if worker_image:
            env.update(AIC_ROAD_WORKER_IMAGE=worker_image, AIC_ROAD_TEST_NETWORK=network)
        tested = subprocess.Popen([sys.executable, '-m', 'pytest', 'tests/test_case_road_worker.py', '-q',
            '--basetemp', str(evidence / 'pytest-temp')], cwd=root / 'backend', env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            stdout, stderr = tested.communicate(timeout=160)
        except subprocess.TimeoutExpired:
            # Signal only this live, owned test process group, not matching
            # arbitrary Celery processes on the host.
            os.killpg(tested.pid, signal.SIGTERM)
            try:
                stdout, stderr = tested.communicate(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(tested.pid, signal.SIGKILL)
                stdout, stderr = tested.communicate(timeout=5)
            (evidence / 'pytest.txt').write_text(stdout + stderr)
            raise RuntimeError('road_worker_drill_timed_out')
        log = stdout + stderr
        (evidence / 'pytest.txt').write_text(log)
        print(log, flush=True)
        if tested.returncode != 0 or '2 passed' not in log or 'skipped' in log:
            raise RuntimeError('real_road_worker_gate_failed')
    except Exception as error:
        (evidence / 'report.json').write_text(json.dumps({'passed': False, 'status': 'failed',
            'error_type': type(error).__name__}))
        raise
    finally:
        if network:
            # Include workers left behind if the test process timed out.
            owned = run('docker', 'ps', '-q', '--filter', f'label=aic.road-worker-child={marker}')
            for identifier in owned.splitlines():
                if not re.fullmatch('[a-f0-9]{12,64}', identifier):
                    raise RuntimeError('unexpected_worker_container_identifier')
                run('docker', 'stop', '-t', '15', identifier)
        label = run('docker', 'inspect', '--format', '{{ index .Config.Labels "aic.road-worker-drill" }}', container)
        if label != marker:
            raise RuntimeError('refusing_cleanup_of_unowned_container')
        run('docker', 'stop', container)
        if network:
            run('docker', 'network', 'rm', network)
        print('owned_redis_removed', flush=True)
    (evidence / 'report.json').write_text(json.dumps({'passed': True, 'real_redis': True,
        'independent_celery_worker': True, 'worker_restarted_between_tasks': True,
        'redis_restart_lost_messages': True, 'real_beat_recovered_database_job': True,
        'native_road_matrix': True, 'duplicate_artifacts': 0, 'business_services_touched': False,
        'image_id': image, 'worker_image_id': worker_image,
        'container_worker': bool(worker_image),
        'scope': 'synthetic SQLite case + local public graph; not full deployment or abrupt in-flight crash'}, indent=2))
    print(f'evidence={evidence}', flush=True)


if __name__ == '__main__':
    main()
