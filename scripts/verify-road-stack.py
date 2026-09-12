"""Owned Compose stack: real PostgreSQL/Redis, authenticated HTTP, automatic profile.

Synthetic input only. Does not claim map publication or road-report acceptance.
"""
import json
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone

import httpx


def isolated_networks(cidr):
    """Optional explicit private subnets for hosts with exhausted default pools."""
    if not cidr:
        return {}
    network = ipaddress.ip_network(cidr)
    private_ranges = [ipaddress.ip_network(value) for value in
                      ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
    if (network.version != 4 or network.prefixlen != 22
            or not any(network.subnet_of(private) for private in private_ranges)):
        raise ValueError('isolated_network_requires_private_ipv4_slash22')
    return {name: {'ipam': {'config': [{'subnet': str(subnet)}]}}
            for name, subnet in zip(('data', 'app', 'edge'), network.subnets(new_prefix=24))}


def remove_owned_stack(project, run):
    """Remove every profile in this disposable project and verify Docker state."""
    if not re.fullmatch(r'aic-road-stack-[0-9a-f]{12}', project):
        raise ValueError('invalid_disposable_stack_project')
    run('--profile', '*', 'down', '--volumes', '--remove-orphans', timeout=120)
    remaining = {}
    for resource, command in (
        ('containers', ['docker', 'ps', '--all', '--quiet']),
        ('volumes', ['docker', 'volume', 'ls', '--quiet']),
        ('networks', ['docker', 'network', 'ls', '--quiet']),
    ):
        result = subprocess.run(
            [*command, '--filter', f'label=com.docker.compose.project={project}'],
            check=True, capture_output=True, text=True, timeout=15,
        )
        identifiers = result.stdout.split()
        if identifiers:
            remaining[resource] = identifiers
    if remaining:
        raise RuntimeError('owned_stack_resources_remaining: ' + json.dumps(remaining))


def main():
    if os.environ.get('AIC_DISPOSABLE_ROAD_STACK') != '1':
        raise RuntimeError('explicit_isolated_stack_opt_in_required')
    root = Path(__file__).resolve().parents[1]
    project = 'aic-road-stack-' + uuid.uuid4().hex[:12]
    with_maps = os.environ.get('AIC_STACK_WITH_MAPS') == '1'
    coverage = os.environ.get('AIC_STACK_COVERAGE') == '1'
    road_evaluation = os.environ.get('AIC_STACK_ROAD_EVALUATION') == '1'
    road_refresh = os.environ.get('AIC_STACK_ROAD_REFRESH') == '1'
    extended_showcase = os.environ.get('AIC_STACK_EXTENDED_SHOWCASE') == '1'
    if os.environ.get('AIC_STACK_PERIOD_BRIEF') == '1' and (
            not extended_showcase or os.environ.get('AIC_STACK_INFORMATION_GAP') != '1'):
        raise ValueError('period_brief_requires_extended_and_gap_fixtures')
    worker_recovery = os.environ.get('AIC_STACK_WORKER_RECOVERY') == '1'
    redis_recovery = os.environ.get('AIC_STACK_REDIS_RECOVERY') == '1'
    if worker_recovery and redis_recovery:
        raise ValueError('test_worker_and_redis_outages_separately')
    if extended_showcase and (not with_maps or os.environ.get('AIC_STACK_CASE_JOURNEY') != '1'):
        raise ValueError('extended_showcase_requires_map_case_journey')
    source_overlay = (os.environ.get('AIC_STACK_SOURCE_OVERLAY') == '1'
                      or ((coverage or road_evaluation or road_refresh)
                          and os.environ.get('AIC_STACK_SOURCE_OVERLAY') != '0'))
    if (road_evaluation or road_refresh) and not with_maps:
        raise ValueError('road_evaluation_requires_map_fixture')
    if with_maps and coverage:
        raise ValueError('select_one_isolated_fixture_mode')
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
    if extended_showcase:
        services['agent-worker'] = {'image': image_id}
        for role in services:
            services[role]['environment'] = {'ENABLE_AGENT_LAB': 'true', 'AGENT_MODE': 'shadow'}
    if source_overlay:
        for role in services:
            services[role]['volumes'] = [f'{root / "backend/app"}:/app/app:ro',
                                       f'{root / "backend/alembic"}:/app/alembic:ro']
    if coverage:
        services['backend']['environment'] = {'AIC_DISPOSABLE_STACK_PROJECT': project, 'AIC_STACK_COVERAGE_ONLY': '1'}
        services['backend']['volumes'] = services['backend'].get('volumes', []) + [
            f'{root / "scripts/seed-road-stack.py"}:/checks/seed-road-stack.py:ro',
            f'{root / "scripts/seed-road-refresh.py"}:/checks/seed-road-refresh.py:ro',
            f'{root / "output/validation/two-city-governed-seq44eg3/catalog.sqlite"}:/fixtures/catalog.sqlite:ro',
            f'{root / "output/validation/node-access-9yuyxfup/compiled/tiles"}:/fixtures/graph:ro']
    if with_maps:
        services['backend'].setdefault('environment', {}).update({'AIC_DISPOSABLE_STACK_PROJECT': project,
            'AIC_STACK_EXTENDED_SHOWCASE': '1' if extended_showcase else '0'})
        services['backend']['volumes'] = services['backend'].get('volumes', []) + [
            f'{root / "scripts/seed-road-stack.py"}:/checks/seed-road-stack.py:ro',
            f'{root / "scripts/seed-road-refresh.py"}:/checks/seed-road-refresh.py:ro',
            f'{root / "backups/map-foundation/v4-source/20260908/complete-candidate-v2/map-assembly-muyp0orr"}:/fixtures/assembly:ro',
            f'{root / "output/validation/two-city-governed-seq44eg3/catalog.sqlite"}:/fixtures/catalog.sqlite:ro',
            f'{root / "output/validation/node-access-9yuyxfup/compiled/tiles"}:/fixtures/graph:ro']
    frontend_image = os.environ.get('AIC_STACK_FRONTEND_IMAGE')
    frontend_image_id = None
    if frontend_image:
        frontend_image_id = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', frontend_image],
            check=True, capture_output=True, text=True, timeout=15).stdout.strip()
        assert frontend_image_id.startswith('sha256:') and len(frontend_image_id) == 71
        services['frontend'] = {'image': frontend_image_id}
    else:
        services['frontend'] = {'image': runtime, 'volumes': [
            f'{root / "frontend/dist"}:/usr/share/nginx/html:ro',
            f'{root / "frontend/nginx.conf"}:/etc/nginx/conf.d/default.conf:ro']}
    override_config = {'services': services}
    network_cidr = os.environ.get('AIC_STACK_NETWORK_CIDR')
    networks = isolated_networks(network_cidr)
    if networks:
        override_config['networks'] = networks
    override.write_text(json.dumps(override_config))
    base = ['docker', 'compose', '-p', project, '--env-file', str(env_file),
            '-f', str(root / 'docker-compose.production.yml'), '-f', str(root / 'docker-compose.road-runtime.yml'),
            '-f', str(override), '--profile', 'road-analysis']
    report = {'passed': False, 'project': project, 'synthetic_only': True, 'source_overlay': source_overlay,
              'image': image, 'image_id': image_id, 'frontend_dist_mounted': not bool(frontend_image),
              'frontend_image_id': frontend_image_id, 'map_road_report_tested': False}
    if network_cidr:
        report['isolated_network_cidr'] = network_cidr
    if source_overlay:
        source_hash = hashlib.sha256()
        for folder in ('app', 'alembic'):
            for file in sorted((root / 'backend' / folder).rglob('*.py')):
                source_hash.update(str(file.relative_to(root)).encode())
                source_hash.update(file.read_bytes())
        report.update(source_overlay=True, source_overlay_sha256=source_hash.hexdigest(), coverage_queue_tested=False)

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
        if extended_showcase:
            run('up', '-d', '--no-build', '--pull', 'never', '--wait', 'agent-worker')
        endpoint = run('port', 'frontend', '80').strip()
        assert endpoint.startswith('127.0.0.1:')
        browser_base = 'http://' + endpoint
        if os.environ.get('AIC_STACK_CASE_JOURNEY') == '1':
            tls_dir = output / 'tls'
            tls_dir.mkdir(mode=0o700)
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                '-keyout', str(tls_dir / 'key.pem'), '-out', str(tls_dir / 'cert.pem'),
                '-days', '1', '-subj', '/CN=localhost'], check=True, capture_output=True, timeout=30)
            (tls_dir / 'key.pem').chmod(0o600)
            services['browser-tls'] = {'image': runtime, 'ports': ['127.0.0.1:0:443'],
                'networks': ['app', 'edge'], 'security_opt': ['no-new-privileges:true'],
                'volumes': [f'{tls_dir}:/fixtures/tls:ro',
                    f'{root / "scripts/fixtures/loopback-tls.conf"}:/etc/nginx/conf.d/default.conf:ro']}
            override.write_text(json.dumps(override_config))
            run('up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'browser-tls')
            tls_endpoint = run('port', 'browser-tls', '443').strip()
            assert tls_endpoint.startswith('127.0.0.1:')
            browser_base = 'https://' + tls_endpoint
            services['backend'].setdefault('environment', {})['CORS_ORIGINS'] = 'https://localhost,' + browser_base
            override.write_text(json.dumps(override_config))
            run('up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', 'backend')
            report['loopback_https_fixture'] = True
        report['stage'] = 'authenticated_case_pipeline'
        print('Application roles ready; checking real HTTP and automatic profile', flush=True)
        with httpx.Client(base_url='http://' + endpoint, timeout=15,
                          headers={'Origin': 'https://localhost'}) as client:
            ready = client.get('/health/ready')
            assert ready.status_code == 200, ready.text
            assert client.get('/api/cases/').status_code == 401
            browser_password = secrets.token_urlsafe(24)
            bootstrap = client.post('/api/auth/bootstrap', headers={'X-Bootstrap-Token': values['bootstrap_token']},
                json={'username': 'synthetic-stack-admin', 'display_name': '合成部署管理员',
                      'password': browser_password})
            assert bootstrap.status_code == 201, bootstrap.text
            # The fixture uses loopback HTTP, not a production TLS terminator.
            # Keep server Secure cookies intact; send this synthetic session explicitly.
            cookie = '; '.join(f'{item.name}={item.value}' for item in client.cookies.jar)
            assert cookie
            client.headers['Cookie'] = cookie
            area = {}
            if with_maps or coverage:
                report['stage'] = 'public_map_fixture'
                seeded = run('exec', '-T', 'backend', '/app/docker-entrypoint.sh', 'python', '/checks/seed-road-stack.py')
                report['map_fixture'] = json.loads(seeded.strip().splitlines()[-1])
                area = {'operational_area_id': report['map_fixture']['area_id']}
                print('Coverage graph fixture installed; recording case through HTTP' if coverage
                      else 'Public map and graph installed; recording case through HTTP', flush=True)
            stopped_workers = ['celery', 'road-worker'] + (['agent-worker'] if extended_showcase else [])
            if worker_recovery:
                report['stage'] = 'workers_stopped_case_save'
                run('stop', '--timeout', '10', *stopped_workers)
                states = run('ps', '--all', '--format', 'json', *stopped_workers)
                stopped = [json.loads(line) for line in states.splitlines() if line.strip()]
                assert len(stopped) == len(stopped_workers) and all(row['State'] == 'exited' for row in stopped)
                report['worker_recovery'] = {'stopped_services': stopped_workers, 'actual_process_stop': True}
            if redis_recovery:
                report['stage'] = 'redis_stopped_case_save'
                run('stop', '--timeout', '10', 'redis')
                stopped = json.loads(run('ps', '--all', '--format', 'json', 'redis').strip())
                assert stopped['State'] == 'exited'
                report['redis_recovery'] = {'actual_process_stop': True, 'workers_left_running': True}
            save_started = time.monotonic()
            fixture_occurred_at = datetime.now(timezone.utc).isoformat()
            report['fixture_case_occurred_at'] = fixture_occurred_at
            response = client.post('/api/cases/', json={'case_number': 'SYNTHETIC-STACK-001',
                'occurred_time': fixture_occurred_at, 'location': '合成公开位置',
                'latitude': 46.54446175, 'longitude': 125.1852727,
                'case_type': '涉油盗窃', 'oil_type': '原油', 'facility_type': '井口', 'modus_operandi': '车辆转运',
                'description': '合成验收：井口原油损失，存在车辆转运线索，具体来源待核。', **area})
            assert response.status_code == 200, response.text
            identifier = response.json()['id']
            if redis_recovery:
                assert type(identifier) is int
                report['redis_recovery']['save_during_stop_ms'] = round((time.monotonic() - save_started) * 1000, 2)
                assert client.get(f'/api/cases/{identifier}').status_code == 200
                retained = run('exec', '-T', 'postgres', 'psql', '-U', 'aicommander', '-d', project.replace('-', '_'),
                    '-Atc', f"SELECT count(*) FROM outbox_events WHERE event_type='case.analysis.requested' AND aggregate_id='{identifier}'")
                assert retained.strip() == '1', 'case_event_lost_during_redis_stop'
                run('start', '--wait', 'redis')
                report['stage'] = 'redis_resuming'
                print('Case saved with Redis stopped; event retained, Redis restarted without restarting workers', flush=True)
            if worker_recovery:
                assert type(identifier) is int
                report['worker_recovery']['save_during_stop_ms'] = round((time.monotonic() - save_started) * 1000, 2)
                assert client.get(f'/api/cases/{identifier}').status_code == 200
                assert client.get(f'/api/cases/{identifier}/analysis-profile/latest').status_code == 404
                pending = run('exec', '-T', 'postgres', 'psql', '-U', 'aicommander', '-d', project.replace('-', '_'),
                    '-Atc', f"SELECT count(*) FROM outbox_events WHERE event_type='case.analysis.requested' AND aggregate_id='{identifier}' AND status='pending'")
                assert pending.strip() == '1', 'case_event_not_retained_during_worker_stop'
                run('start', *stopped_workers)
                report['stage'] = 'workers_resuming'
                print('Case saved with workers stopped; retained event verified, workers restarted', flush=True)
            deadline = time.monotonic() + 75
            while True:
                profile = client.get(f'/api/cases/{identifier}/analysis-profile/latest')
                if profile.status_code == 200:
                    break
                assert profile.status_code == 404, profile.text
                assert time.monotonic() < deadline, 'automatic_profile_not_ready'
                time.sleep(1)
            assert client.get(f'/api/cases/{identifier}').json()['description'] == '合成验收：井口原油损失，存在车辆转运线索，具体来源待核。'
            if worker_recovery:
                report['worker_recovery']['automatic_profile_resumed'] = True
            if redis_recovery:
                report['redis_recovery']['automatic_profile_available_after_restore'] = True
            if coverage:
                report['stage'] = 'coverage_road_queue'
                response = client.post('/api/deployment-sandbox/spatial-compare', json=area)
                assert response.status_code == 200, response.text
                comparison = response.json()
                assert comparison['baseline']['covered_count'] == 1
                job = client.post(f'/api/deployment-sandbox/spatial-comparisons/{comparison["id"]}/road-jobs',
                    json={'vehicle': {'kind': 'auto'}, 'distance_budget_m': 1000})
                assert job.status_code == 202, job.text
                event_id = job.json()['event_id']
                deadline = time.monotonic() + 150
                while True:
                    state = client.get(f'/api/deployment-sandbox/road-jobs/{event_id}')
                    assert state.status_code == 200, state.text
                    if state.json()['status'] == 'completed':
                        break
                    assert state.json()['status'] in ('pending', 'processing', 'retry'), state.text
                    assert time.monotonic() < deadline, 'coverage_road_queue_timeout'
                    time.sleep(1)
                artifact = state.json()['artifact']
                assert artifact['state'] == 'calculated_reference', artifact
                distance = artifact['matrix_batches'][0]['cells'][0]['distance_m']
                assert 600 < distance < 800, distance
                assert len(artifact['targets'][0]['baseline_origin_ids_within_budget']) == 1
                report.update(coverage_queue_tested=True, coverage_input_digest=comparison['input_digest'],
                    coverage_graph_sha256=artifact['graph_sha256'], coverage_road_distance_m=distance)
                print('Real coverage queue and native matrix passed', flush=True)
            if with_maps and os.environ.get('AIC_STACK_BROWSER_ONLY') != '1':
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
                if road_refresh:
                    report['stage'] = 'published_network_automatic_refresh'
                    seeded_refresh = run('exec', '-T', 'backend', '/app/docker-entrypoint.sh',
                                         'python', '/checks/seed-road-refresh.py')
                    refreshed = json.loads(seeded_refresh.strip().splitlines()[-1])
                    deadline = time.monotonic() + 150
                    while True:
                        response = client.get(f'/api/road-analysis/case-results/{saved["id"]}/automatic-comparison')
                        assert response.status_code == 200, response.text
                        body = response.json()
                        new_artifact = body.get('artifact') or {}
                        new_matrix = (new_artifact.get('content') or {}).get('matrix') or {}
                        if body['status'] == 'completed' and new_matrix.get('network_id') == refreshed['network_id']:
                            break
                        assert time.monotonic() < deadline, 'published_network_refresh_timeout'
                        time.sleep(1)
                    assert new_artifact['id'] != artifact['id']
                    assert new_matrix['graph_sha256'] == refreshed['graph_sha256']
                    assert new_matrix['cells'] == matrix['cells']
                    unchanged = client.get(f'/api/case-results/{saved["id"]}')
                    assert unchanged.status_code == 200
                    assert unchanged.json()['content_sha256'] == saved['content_sha256']
                    report.update(real_publication_event_refresh=True,
                        refresh_network_id=refreshed['network_id'], refresh_event_id=refreshed['refresh_event_id'],
                        refreshed_road_artifact_hash=new_artifact['content_sha256'],
                        refresh_same_graph_new_catalog_version=True,
                        topology_change_benchmark=False)
                    print('New network version refreshed automatically through real worker/native engine', flush=True)
                if road_evaluation:
                    report['stage'] = 'frozen_road_evaluation'
                    frozen = client.post('/api/admin/evaluations/road-datasets', json={
                        'name': '合成真实路由固定输入', 'version': '1', 'artifact_ids': [artifact['id']]})
                    assert frozen.status_code == 201, frozen.text
                    dataset = frozen.json()
                    assert dataset['graph_verification'] == 'deferred_to_worker'
                    assert dataset['frozen_input_exported'] is False
                    results = []
                    for index in range(2):
                        payload = {'dataset_id': dataset['id'], 'request_id': f'isolated-replay-{index}'}
                        queued = client.post('/api/admin/evaluations/road-jobs', json=payload)
                        assert queued.status_code == 202, queued.text
                        duplicate = client.post('/api/admin/evaluations/road-jobs', json=payload)
                        assert duplicate.status_code == 202 and not duplicate.json()['created']
                        assert duplicate.json()['event_id'] == queued.json()['event_id']
                        deadline = time.monotonic() + 150
                        while True:
                            replayed = client.get('/api/admin/evaluations/road-jobs/' + queued.json()['event_id'])
                            assert replayed.status_code == 200, replayed.text
                            result = replayed.json()
                            if result['status'] == 'completed':
                                break
                            assert result['status'] in ('pending', 'processing'), replayed.text
                            assert time.monotonic() < deadline, 'road_evaluation_timeout'
                            time.sleep(1)
                        assert result['result_status'] == 'completed', result
                        assert result['metrics'] == {'sample_count': 1, 'failed_sample_count': 0,
                            'unlabeled_sample_count': 1, 'accuracy': None}, result
                        assert result['trace']['dataset_checksum'] == dataset['checksum']
                        results.append(result)
                    assert results[0]['trace']['records'] == results[1]['trace']['records']
                    report.update(real_frozen_road_evaluation=True, road_evaluation_dataset_checksum=dataset['checksum'],
                        road_evaluation_result_checksum=results[0]['trace']['records'][0]['result_checksum'],
                        road_evaluation_repeatability=True)
                    print('Frozen road dataset replayed twice through real Redis/worker/native engine', flush=True)
            report.update(passed=True, http_bootstrap=True, postgres_case_write_read=True,
                          redis_beat_automatic_profile=True, production_tls_tested=False,
                          profile_schema=profile.json().get('schema_version'))
            if os.environ.get('AIC_STACK_BROWSER') == '1':
                from road_stack_browser import observe_stack
                report['stage'] = 'real_browser_observation'
                if os.environ.get('AIC_STACK_INFORMATION_GAP') == '1':
                    from road_stack_showcase import prepare_information_gap
                    report['information_gap'] = prepare_information_gap(client, area, output)
                observed = observe_stack(browser_base, cookie, output,
                    credentials={'username': 'synthetic-stack-admin', 'password': browser_password})
                (output / 'browser.json').write_text(json.dumps(observed, ensure_ascii=False, indent=2))
                report['real_browser_observation'] = observed['observed']
            if worker_recovery or redis_recovery:
                profile_count = run('exec', '-T', 'postgres', 'psql', '-U', 'aicommander', '-d', project.replace('-', '_'),
                    '-Atc', f'SELECT count(*) FROM case_analysis_profiles WHERE case_id={identifier}')
                assert profile_count.strip() == '1', 'worker_resume_created_duplicate_profile'
                report['worker_recovery' if worker_recovery else 'redis_recovery']['profile_count_after_journey'] = 1
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
            *(['SELECT count(*) FROM spatial_coverage_comparisons',
               "SELECT count(*) FROM outbox_events WHERE event_type='coverage.roads.compare' AND status='completed'"] if coverage else []),
            *(['SELECT checksum FROM evaluation_datasets ORDER BY id',
               'SELECT id, metrics, trace_manifest FROM evaluation_runs ORDER BY id'] if road_evaluation else []),
            *(['SELECT id, graph_sha256, builder_version FROM road_network_versions ORDER BY id',
               'SELECT id, content_sha256 FROM case_road_artifacts ORDER BY id',
               "SELECT id, status, payload FROM outbox_events WHERE event_type='road.network.published' ORDER BY id"]
              if road_refresh else []),
        ):
            original = run('exec', '-T', 'postgres', 'psql', '-U', 'aicommander', '-d', database, '-Atc', statement)
            recovered = run('exec', '-T', 'postgres', 'psql', '-U', 'aicommander', '-d', restored, '-Atc', statement)
            assert original == recovered, 'backup_restore_content_mismatch'
        report.update(passed=True, backup_restored=True, original_case_preserved=True)
    except Exception as error:
        report['passed'] = False
        report['error'] = str(error)
        raise
    finally:
        report['owned_stack_removed'] = False
        try:
            remove_owned_stack(project, run)
            report['owned_stack_removed'] = True
        except Exception as error:
            report['passed'] = False
            report['cleanup_error'] = str(error)
            raise
        finally:
            (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
