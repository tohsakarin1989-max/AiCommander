"""Create and remove only an owned isolated PostGIS database for publication tests."""
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import uuid


def main():
    if os.environ.get('AIC_DISPOSABLE_ROAD_PG') != '1':
        raise RuntimeError('explicit_disposable_drill_opt_in_required')
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('road_pg_runner', root / 'scripts/verify-road-postgres-container.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    run = runner.run
    evidence = Path(tempfile.mkdtemp(prefix='road-publish-pg-', dir=root / 'output/validation'))
    (evidence / 'report.json').write_text(json.dumps({'passed': False, 'status': 'started'}))
    marker = str(uuid.uuid4())
    image = run('docker', 'image', 'inspect', '--format', '{{.Id}}', 'postgis/postgis:16-3.4-alpine')
    container = run('docker', 'run', '--rm', '-d', '--label', f'aic.publish-drill={marker}',
        '-e', 'POSTGRES_PASSWORD=disposable-publish-only', '-e', 'POSTGRES_DB=aic_publish_test',
        '-p', '127.0.0.1::5432', image)
    if not re.fullmatch('[a-f0-9]{64}', container):
        raise RuntimeError('unexpected_container_identifier')
    try:
        import subprocess
        for _ in range(40):
            try:
                run('docker', 'exec', container, 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres', timeout=5)
                break
            except subprocess.CalledProcessError:
                time.sleep(0.5)
        else:
            raise RuntimeError('temporary_database_not_ready')
        endpoint = run('docker', 'port', container, '5432')
        if not re.fullmatch(r'127\.0\.0\.1:\d+', endpoint):
            raise RuntimeError('database_not_loopback_only')
        env = dict(os.environ, AIC_ROAD_PUBLISH_PG='1',
            AIC_ROAD_PUBLISH_PG_URL=f'postgresql://postgres:disposable-publish-only@{endpoint}/aic_publish_test')
        log = run(sys.executable, '-m', 'pytest', 'tests/test_road_publication_postgres.py', '-q',
                  cwd=root / 'backend', env=env, timeout=180)
        (evidence / 'pytest.txt').write_text(log)
        print(log, flush=True)
        if '1 passed' not in log or 'skipped' in log:
            raise RuntimeError('publication_gate_not_executed')
    finally:
        label = run('docker', 'inspect', '--format', '{{ index .Config.Labels "aic.publish-drill" }}', container)
        if label != marker:
            raise RuntimeError('refusing_cleanup_of_unowned_container')
        run('docker', 'stop', container)
        print('owned_disposable_publication_database_removed', flush=True)
    (evidence / 'report.json').write_text(json.dumps({'passed': True, 'publishers': 4,
        'created_publications': 1, 'native_installed_graph_route': True, 'container_removed': True,
        'image_id': image, 'scope': 'synthetic native graph and real PostgreSQL publication race; not production topology'}, indent=2))
    print(f'evidence={evidence}', flush=True)


if __name__ == '__main__':
    main()
