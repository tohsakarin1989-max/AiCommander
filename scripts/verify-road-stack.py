"""Owned Compose stack: real PostgreSQL/Redis, authenticated HTTP, automatic profile.

Synthetic input only. Does not claim map publication or road-report acceptance.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import uuid

import httpx


def main():
    if os.environ.get('AIC_DISPOSABLE_ROAD_STACK') != '1':
        raise RuntimeError('explicit_isolated_stack_opt_in_required')
    root = Path(__file__).resolve().parents[1]
    project = 'aic-road-stack-' + uuid.uuid4().hex[:12]
    with_maps = os.environ.get('AIC_STACK_WITH_MAPS') == '1'
    output = Path(tempfile.mkdtemp(prefix=project + '-', dir=root / 'output'))
    output.chmod(0o700)
    secret_dir = output / 'secrets'
    secret_dir.mkdir(mode=0o700)
    values = {name: secrets.token_hex(32) for name in ('db_password', 'redis_password', 'secret_key', 'bootstrap_token')}
    for name, value in values.items():
        file = secret_dir / name
        file.write_text(value)
        file.chmod(0o600)
    image = os.environ.get('AIC_STACK_IMAGE', 'aicommander-backend-roads:4.2-integrated-candidate')
    image_id = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image],
                              check=True, capture_output=True, text=True, timeout=15).stdout.strip()
    assert image_id.startswith('sha256:') and len(image_id) == 71
    runtime = 'nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236'
    env_file = output / 'stack.env'
    env_file.write_text(f'APP_DOMAIN=localhost\nAPP_PORT=0\nAPP_VERSION=isolated-integration-test\n'
                        f'SECRETS_DIR={secret_dir}\nENABLE_ROAD_ANALYSIS=true\nENABLE_AGENT_LAB=false\n'
                        f'DB_NAME={project.replace("-", "_")}\nAGENT_MODE=off\nCELERY_CONCURRENCY=1\n')
    env_file.chmod(0o600)
    override = output / 'override.json'
    services = {role: {'image': image_id} for role in ('backend', 'celery', 'celery-beat', 'road-worker')}
    if with_maps:
        services['backend'].update(environment={'AIC_DISPOSABLE_STACK_PROJECT': project}, volumes=[
            f'{root / "scripts/seed-road-stack.py"}:/checks/seed-road-stack.py:ro',
            f'{root / "backups/map-foundation/v4-source/20260908/complete-candidate-v2/map-assembly-muyp0orr"}:/fixtures/assembly:ro',
            f'{root / "output/validation/two-city-governed-seq44eg3/catalog.sqlite"}:/fixtures/catalog.sqlite:ro',
            f'{root / "output/validation/node-access-9yuyxfup/compiled/tiles"}:/fixtures/graph:ro'])
    services['frontend'] = {'image': runtime, 'volumes': [
        f'{root / "frontend/dist"}:/usr/share/nginx/html:ro',
        f'{root / "frontend/nginx.conf"}:/etc/nginx/conf.d/default.conf:ro']}
    override.write_text(json.dumps({'services': services}))
    base = ['docker', 'compose', '-p', project, '--env-file', str(env_file),
            '-f', str(root / 'docker-compose.production.yml'), '-f', str(root / 'docker-compose.road-runtime.yml'),
            '-f', str(override), '--profile', 'road-analysis']
    report = {'passed': False, 'project': project, 'synthetic_only': True,
              'image': image, 'image_id': image_id, 'frontend_dist_mounted': True, 'map_road_report_tested': False}

    def run(*args, timeout=180):
        result = subprocess.run([*base, *args], capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            text = result.stderr[-5000:]
            for value in values.values():
                text = text.replace(value, '[redacted]')
            raise RuntimeError(text)
        return result.stdout

    try:
        report['stage'] = 'database_start'
        print(f'isolated_project={project}; evidence={output}', flush=True)
        run('up', '-d', '--no-build', '--pull', 'never', '--wait', 'postgres', 'redis')
        report['stage'] = 'migration'
        print('PostgreSQL and Redis ready; applying isolated migrations', flush=True)
        run('run', '--rm', '--no-deps', '--pull', 'never', 'backend', 'alembic', 'upgrade', 'head')
        report['stage'] = 'application_start'
        run('up', '-d', '--no-build', '--pull', 'never', '--wait', 'backend', 'celery', 'celery-beat', 'road-worker', 'frontend')
        endpoint = run('port', 'frontend', '80').strip()
        assert endpoint.startswith('127.0.0.1:')
        report['stage'] = 'authenticated_case_pipeline'
        print('Application roles ready; checking real HTTP and automatic profile', flush=True)
        with httpx.Client(base_url='http://' + endpoint, timeout=15,
                          headers={'Origin': 'https://localhost'}) as client:
            ready = client.get('/health/ready')
            assert ready.status_code == 200, ready.text
            assert client.get('/api/cases/').status_code == 401
            bootstrap = client.post('/api/auth/bootstrap', headers={'X-Bootstrap-Token': values['bootstrap_token']},
                json={'username': 'synthetic-stack-admin', 'display_name': '合成部署管理员',
                      'password': secrets.token_urlsafe(24)})
            assert bootstrap.status_code == 201, bootstrap.text
            # The fixture uses loopback HTTP, not a production TLS terminator.
            # Keep server Secure cookies intact; send this synthetic session explicitly.
            cookie = '; '.join(f'{item.name}={item.value}' for item in client.cookies.jar)
            assert cookie
            client.headers['Cookie'] = cookie
            area = {}
            if with_maps:
                report['stage'] = 'public_map_fixture'
                seeded = run('exec', '-T', 'backend', '/app/docker-entrypoint.sh', 'python', '/checks/seed-road-stack.py')
                report['map_fixture'] = json.loads(seeded.strip().splitlines()[-1])
                area = {'operational_area_id': report['map_fixture']['area_id']}
                print('Public map and graph installed; recording case through HTTP', flush=True)
            response = client.post('/api/cases/', json={'case_number': 'SYNTHETIC-STACK-001',
                'occurred_time': '2026-09-11T01:00:00', 'location': '合成公开位置',
                'latitude': 46.54446175, 'longitude': 125.1852727,
                'case_type': '涉油盗窃', 'oil_type': '原油', 'facility_type': '井口', 'modus_operandi': '车辆转运',
                'description': '合成验收：井口原油损失，存在车辆转运线索，具体来源待核。', **area})
            assert response.status_code == 200, response.text
            identifier = response.json()['id']
            deadline = time.monotonic() + 75
            while True:
                profile = client.get(f'/api/cases/{identifier}/analysis-profile/latest')
                if profile.status_code == 200:
                    break
                assert profile.status_code == 404, profile.text
                assert time.monotonic() < deadline, 'automatic_profile_not_ready'
                time.sleep(1)
            assert client.get(f'/api/cases/{identifier}').json()['description'] == '合成验收：井口原油损失，存在车辆转运线索，具体来源待核。'
            if with_maps:
                report['stage'] = 'automatic_road_and_http_report'
                deadline = time.monotonic() + 110
                while True:
                    latest = client.get(f'/api/cases/{identifier}/results/latest')
                    if latest.status_code == 200:
                        saved = latest.json()
                        road = client.get(f'/api/road-analysis/case-results/{saved["id"]}/automatic-comparison')
                        if road.status_code == 200 and road.json()['status'] == 'completed':
                            break
                    assert time.monotonic() < deadline, 'automatic_road_result_not_ready'
                    time.sleep(1)
                artifact = road.json()['artifact']
                matrix = artifact['content']['matrix']
                assert 600 < matrix['cells'][0]['distance_m'] < 800
                for extension in ('docx', 'pdf'):
                    document = client.get(f'/api/case-results/{saved["id"]}/document.{extension}',
                        params={'road_artifact_id': artifact['id']}, timeout=90)
                    assert document.status_code == 200, document.text[:500]
                    assert document.headers['x-road-artifact-sha256'] == artifact['content_sha256']
                    assert document.content.startswith(b'PK' if extension == 'docx' else b'%PDF-')
                    (output / f'road-report.{extension}').write_bytes(document.content)
                report.update(map_road_report_tested=True, real_case_to_road_queue=True,
                              source_result_hash=saved['content_sha256'], road_artifact_hash=artifact['content_sha256'])
            report.update(passed=True, http_bootstrap=True, postgres_case_write_read=True,
                          redis_beat_automatic_profile=True, production_tls_tested=False,
                          profile_schema=profile.json().get('schema_version'))
        report['passed'] = False
        report['stage'] = 'backup_restore'
        print('Core HTTP flow passed; restoring a backup into a separate temporary database', flush=True)
        database = project.replace('-', '_')
        restored = database + '_restore'
        run('exec', '-T', 'postgres', 'pg_dump', '-U', 'aicommander', '-Fc',
            '-f', '/tmp/isolated-stack.dump', database)
        run('exec', '-T', 'postgres', 'createdb', '-U', 'aicommander', restored)
        run('exec', '-T', 'postgres', 'pg_restore', '-U', 'aicommander', '--exit-on-error',
            '--no-owner', '--no-privileges', '-d', restored, '/tmp/isolated-stack.dump')
        for statement in (
            'SELECT version_num FROM alembic_version',
            'SELECT count(*) FROM cases',
            'SELECT case_number, description FROM cases ORDER BY id',
            'SELECT count(*) FROM case_analysis_profiles',
        ):
            original = run('exec', '-T', 'postgres', 'psql', '-U', 'aicommander', '-d', database, '-Atc', statement)
            recovered = run('exec', '-T', 'postgres', 'psql', '-U', 'aicommander', '-d', restored, '-Atc', statement)
            assert original == recovered, 'backup_restore_content_mismatch'
        report.update(passed=True, backup_restored=True, original_case_preserved=True)
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        try:
            run('down', '--volumes', '--remove-orphans', timeout=120)
            report['owned_stack_removed'] = True
        finally:
            (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
