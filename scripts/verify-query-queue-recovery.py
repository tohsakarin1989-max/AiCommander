#!/usr/bin/env python3
"""Disposable Docker/Redis/prefork query probe; never loads host business config."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import uuid4


def inside(action, pipeline=False):
    if not Path('/probe-script').is_file() or not Path('/snapshot/app').is_dir():
        raise RuntimeError('isolated_container_required')
    os.chdir('/tmp')
    os.environ.clear()
    os.environ.update({
        'PATH': '/usr/local/bin:/usr/bin:/bin', 'PYTHONPATH': '/snapshot',
        'DATABASE_URL': 'sqlite:////tmp/query-probe.sqlite',
        'REDIS_URL': 'redis://probe-redis:6379/0',
        'CELERY_BROKER_URL': 'redis://probe-redis:6379/0',
        'CELERY_RESULT_BACKEND': 'redis://probe-redis:6379/1',
        'SECRET_KEY': 'isolated-query-probe-not-a-business-secret',
        'ENABLE_AGENT_LAB': 'true', 'AGENT_MODE': 'shadow',
        'AGENT_REDIS_QUEUE': 'query_probe', 'ENABLE_VECTOR_INDEX': 'false',
        'AUTO_CREATE_TABLES': 'false', 'ENVIRONMENT': 'development',
    })
    sys.path.insert(0, '/snapshot')
    import app.models  # noqa: F401
    from app.database import Base, engine, SessionLocal
    from app.models.agent_run import AgentRun, AgentEvent
    from app.services.intelligent_query_tasks import create_query
    from app.tasks.celery_app import celery_app

    if pipeline:
        return pipeline_inside(action, Base, engine, SessionLocal, celery_app)

    if action == 'beat':
        # Keep the production query entry unchanged; omit unrelated schedules
        # from this isolated query-only experiment.
        celery_app.conf.beat_schedule = {
            'process-intelligent-query': celery_app.conf.beat_schedule['process-intelligent-query']}
        celery_app.Beat(loglevel='INFO', schedule='/tmp/query-probe-beat').run()
        return
    if action == 'worker':
        import asyncio
        from types import SimpleNamespace
        from app.services import intelligent_query_loop

        class ProbeModel:
            def __init__(self):
                self.called = False

            async def ainvoke(self, prompt):
                if json.loads(prompt)['question'] == 'SYNTHETIC-HARD-BLOCK':
                    import signal
                    # Simulate a non-cooperative native/model call: ignore the
                    # soft signal, so only the unchanged hard task limit wins.
                    signal.signal(signal.SIGUSR1, signal.SIG_IGN)
                    Path('/tmp/blocked-child.json').write_text(json.dumps({'pid': os.getpid()}))
                    time.sleep(300)
                await asyncio.sleep(1)
                response = ({'action': 'finish', 'reason': 'completed'} if self.called else
                            {'action': 'call', 'tool': 'count_cases', 'arguments': {}})
                self.called = True
                return SimpleNamespace(content=json.dumps(response))

        intelligent_query_loop.create_query_model = lambda db: ProbeModel()
        celery_app.worker_main(['worker', '--pool=prefork', '--concurrency=2',
                               '--queues=query_probe', '--loglevel=INFO',
                               '--without-gossip', '--without-mingle'])
        return
    if action == 'init':
        from app.models.user import User
        from app.models.map_foundation import OperationalArea, UserAreaScope
        from app.models.case import Case
        from datetime import datetime
        if Path('/tmp/query-probe.sqlite').exists():
            raise RuntimeError('refuse_existing_database')
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            db.add(OperationalArea(id=1, code='probe', name='合成区'))
            db.add(User(id=1, username='probe', display_name='合成账号',
                        password_hash='not-a-login', role='analyst', is_active=True))
            db.commit()
            db.add(UserAreaScope(user_id=1, operational_area_id=1, access_level='read'))
            db.add(Case(case_number='SYNTHETIC-QUEUE-001', operational_area_id=1,
                        occurred_time=datetime(2026, 9, 9), status='pending',
                        case_type='盗油', oil_type='原油'))
            db.commit()
        log = open('/tmp/worker.log', 'w')
        subprocess.Popen([sys.executable, '/probe-script', '--inside', 'worker'],
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        log.close()
        result = {'initialized': True}
    elif action in {'enqueue', 'enqueue-block'}:
        with SessionLocal() as db:
            db.info['principal_user_id'] = 1
            result = create_query(db, 'SYNTHETIC-HARD-BLOCK' if action == 'enqueue-block'
                                  else '统计合成案件数量')
            result = {'id': result['id'], 'status': result['status']}
    elif action in {'dispatch', 'dispatch-one'}:
        count = 1 if action == 'dispatch-one' else 8
        for _ in range(count):
            celery_app.send_task('aicommander.queries.process_next', queue='query_probe',
                                 args=[], kwargs={}, retry=False)
        result = {'empty_wakeups_sent': count}
    elif action == 'start-beat':
        with open('/tmp/beat.log', 'w') as log:
            subprocess.Popen([sys.executable, '/probe-script', '--inside', 'beat'],
                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        result = {'beat_started': True}
    elif action == 'state':
        with SessionLocal() as db:
            result = {'runs': [{'id': r.id, 'status': r.status, 'attempts': r.attempt_count,
                               'result': r.result_summary,
                               'started_events': db.query(AgentEvent).filter_by(
                                   run_id=r.id, event_type='query_started').count()}
                              for r in db.query(AgentRun).all()]}
        log = Path('/tmp/worker.log').read_text()
        result['hard_timeout_seen'] = 'Hard time limit (135s)' in log
        marker = Path('/tmp/blocked-child.json')
        result['blocked_child_gone'] = (marker.exists() and
            not Path('/proc', str(json.loads(marker.read_text())['pid'])).exists())
    else:
        raise ValueError('unknown_probe_action')
    print(json.dumps(result, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inside', choices=['init', 'worker', 'beat', 'start-beat',
                        'enqueue', 'enqueue-block', 'dispatch', 'dispatch-one', 'state'])
    parser.add_argument('--hard-timeout', action='store_true')
    parser.add_argument('--pipeline', action='store_true', help='Test actual case governance, without model doubles')
    args = parser.parse_args()
    if args.inside:
        inside(args.inside, args.pipeline)
        return
    root = Path(__file__).resolve().parents[1]
    docker = shutil.which('docker') or '/opt/homebrew/bin/docker'
    name = 'aic-query-probe-' + uuid4().hex[:10]
    network, redis, runner = name + '-net', name + '-redis', name + '-runner'
    output = root / 'output/validation/query-queue-recovery'
    output.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix='run-', dir=output))
    created = []

    def command(*parts, timeout=40):
        run = subprocess.run([docker, *parts], capture_output=True, text=True, timeout=timeout)
        with (evidence / 'commands.log').open('a') as stream:
            stream.write(json.dumps({'args': list(parts), 'exit_code': run.returncode,
                                     'stdout': run.stdout, 'stderr': run.stderr}) + '\n')
        if run.returncode:
            raise RuntimeError(f'docker_command_failed:{parts[0]}:{run.returncode}')
        return run.stdout.strip()

    def action(value):
        result = command('exec', runner, 'python', '/probe-script', '--inside', value,
                         *(['--pipeline'] if args.pipeline else []))
        return json.loads(result.splitlines()[-1])

    def await_completed(count):
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            state = action('state')
            if len(state['runs']) == count and all(r['status'] == 'completed' for r in state['runs']):
                for run in state['runs']:
                    assert run['attempts'] == run['started_events'] == 1
                    assert run['result']['cards'][0]['data']['count'] == 1
                return state
            time.sleep(1)
        raise RuntimeError('query_completion_timeout')

    with tempfile.TemporaryDirectory(prefix='aic-query-probe-source-') as temp:
        source = Path(temp)
        shutil.copytree(root / 'backend/app', source / 'app',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copyfile(root / 'VERSION', source / 'VERSION')
        shutil.copyfile(__file__, source / 'probe.py')
        source_hash = hashlib.sha256()
        for path in sorted(source.rglob('*')):
            if path.is_file():
                source_hash.update(str(path.relative_to(source)).encode())
                source_hash.update(path.read_bytes())
        try:
            # Resolve existing local images to immutable IDs; do not pull a tag.
            image = command('image', 'inspect', 'aicommander-map-worker:v4-dashboard-candidate',
                            '--format', '{{.Id}}')
            redis_image = command('image', 'inspect', 'redis:7-alpine', '--format', '{{.Id}}')
            command('network', 'create', '--internal', network)
            created.append(('network', network))
            command('run', '-d', '--name', redis, '--network', network,
                    '--network-alias', 'probe-redis', redis_image,
                    'redis-server', '--save', '', '--appendonly', 'no')
            created.append(('container', redis))
            command('run', '-d', '--name', runner, '--network', network,
                    '--mount', f'type=bind,src={source},dst=/snapshot,readonly',
                    '--mount', f'type=bind,src={source / "probe.py"},dst=/probe-script,readonly',
                    '--entrypoint', 'sleep', image, '600')
            created.append(('container', runner))
            action('init')
            if args.pipeline:
                pipeline_experiment(action, command, redis, evidence, image, source_hash.hexdigest())
                return
            first = action('enqueue')
            action('dispatch')
            initial = await_completed(1)
            command('stop', '--time', '2', redis)
            queued = action('enqueue')
            during_outage = action('state')
            assert queued['status'] == 'queued'
            assert next(r for r in during_outage['runs'] if r['id'] == queued['id'])['attempts'] == 0
            command('start', redis)
            action('dispatch')
            recovered = await_completed(2)
            timeout_result = None
            if args.hard_timeout:
                blocked = action('enqueue-block')
                action('dispatch-one')
                start = time.monotonic()
                while time.monotonic() - start < 165:
                    state = action('state')
                    if state['hard_timeout_seen'] and state['blocked_child_gone']:
                        break
                    print(json.dumps({'phase': 'await_actual_135_second_limit',
                                      'elapsed_seconds': round(time.monotonic() - start)}), flush=True)
                    time.sleep(10)
                else:
                    raise RuntimeError('hard_timeout_not_observed')
                # Nothing manually expires the row. The actual Beat entry wakes
                # the real worker to reclaim it using wall-clock age.
                action('start-beat')
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    state = action('state')
                    expired = next(r for r in state['runs'] if r['id'] == blocked['id'])
                    if expired['status'] == 'expired':
                        assert expired['result'] == {} and expired['attempts'] == 1
                        break
                    time.sleep(2)
                else:
                    raise RuntimeError('beat_did_not_reclaim_expired_query')
                healthy = action('enqueue')
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    state = action('state')
                    next_run = next(r for r in state['runs'] if r['id'] == healthy['id'])
                    if next_run['status'] == 'completed':
                        assert next_run['attempts'] == next_run['started_events'] == 1
                        assert next_run['result']['cards'][0]['data']['count'] == 1
                        timeout_result = state
                        break
                    time.sleep(2)
                else:
                    raise RuntimeError('worker_not_healthy_after_hard_limit')
            report = {'status': 'passed', 'source_sha256': source_hash.hexdigest(),
                      'runtime_image': image, 'redis_image': redis_image,
                      'initial': initial, 'during_outage': during_outage, 'recovered': recovered,
                      'real_prefork_concurrency': 2, 'model': 'deterministic_test_double',
                      'beat_tested': args.hard_timeout, 'hard_timeout_tested': args.hard_timeout,
                      'after_hard_timeout': timeout_result,
                      'postgresql_tested': False, 'target_server_tested': False}
            (evidence / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps({'status': 'passed', 'evidence': str(evidence)}), flush=True)
        finally:
            if ('container', runner) in created:
                log = subprocess.run([docker, 'exec', runner, 'cat', '/tmp/worker.log'],
                                     capture_output=True, text=True, timeout=15)
                (evidence / 'worker.log').write_text(log.stdout + log.stderr)
                if args.hard_timeout:
                    log = subprocess.run([docker, 'exec', runner, 'cat', '/tmp/beat.log'],
                                         capture_output=True, text=True, timeout=15)
                    (evidence / 'beat.log').write_text(log.stdout + log.stderr)
            for kind, target in reversed(created):
                command('rm', '-f', '-v', target) if kind == 'container' else command('network', 'rm', target)


def pipeline_inside(action, Base, engine, SessionLocal, celery_app):
    from datetime import datetime
    from app.models.case import Case
    from app.models.case_pipeline import CaseAnalysisProfile, OutboxEvent
    from app.models.case_result import CaseResultSnapshot
    from app.services.case_service import CaseService

    if action == 'worker':
        celery_app.worker_main(['worker', '--pool=prefork', '--concurrency=1',
            '--queues=celery', '--loglevel=INFO', '--without-gossip', '--without-mingle'])
        return
    if action == 'beat':
        celery_app.conf.beat_schedule = {'process-case-pipeline': celery_app.conf.beat_schedule['process-case-pipeline']}
        celery_app.Beat(loglevel='INFO', schedule='/tmp/pipeline-beat').run()
        return
    if action == 'init':
        assert not Path('/tmp/query-probe.sqlite').exists()
        Base.metadata.create_all(engine)
        result = {'initialized': True}
        for component in ('worker', 'beat'):
            with open(f'/tmp/{component}.log', 'w') as log:
                subprocess.Popen([sys.executable, '/probe-script', '--pipeline', '--inside', component],
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    elif action == 'enqueue':
        with SessionLocal() as db:
            count = db.query(Case).count()
            case = CaseService.create_case(db, case_number=f'SYNTHETIC-PIPELINE-{count + 1}',
                occurred_time=datetime(2026, 9, 10), location='合成区域',
                description='未发现罐车，但是发现货车。夜里查获胶管。', case_type='涉油测试')
            db.commit()
            assert db.query(OutboxEvent).filter_by(aggregate_id=str(case.id), event_type='case.analysis.requested').count() == 1
            result = {'case_id': case.id, 'saved': True}
    elif action == 'state':
        with SessionLocal() as db:
            result = {'cases': db.query(Case).count(), 'profiles': [],
                'results': db.query(CaseResultSnapshot).count(),
                'events': [{'type': e.event_type, 'status': e.status} for e in db.query(OutboxEvent).all()]}
            for profile in db.query(CaseAnalysisProfile).all():
                semantics = profile.payload['semantics']
                result['profiles'].append({'case_id': profile.case_id, 'version': profile.profile_version,
                    'schema': profile.schema_version, 'semantics': semantics,
                    'original_unchanged': db.get(Case, profile.case_id).description == '未发现罐车，但是发现货车。夜里查获胶管。'})
    elif action == 'dispatch':
        for _ in range(3):
            celery_app.send_task('aicommander.case_pipeline.process_pending', retry=False)
        result = {'wakeups': 3}
    else:
        raise ValueError('unsupported_pipeline_action')
    print(json.dumps(result, ensure_ascii=False), flush=True)


def pipeline_experiment(action, command, redis, evidence, image, source_hash):
    def await_profiles(count):
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            state = action('state')
            if len(state['profiles']) == count and state['results'] == count:
                assert all(p['version'] == 1 and p['original_unchanged'] for p in state['profiles'])
                expected = {('罐车', 'negated'), ('货车', 'stated'), ('夜间', 'stated'), ('软管', 'stated')}
                assert all(p['schema'] == '4.1.0' and expected <= {
                    (a['value'], a['kind']) for a in p['semantics']['assertions']} for p in state['profiles'])
                return state
            time.sleep(1)
        raise RuntimeError('pipeline_completion_timeout')

    action('enqueue')
    initial = await_profiles(1)
    command('stop', '--time', '2', redis)
    action('enqueue')
    outage = action('state')
    assert outage['cases'] == 2 and len(outage['profiles']) == 1
    command('start', redis)
    recovered = await_profiles(2)  # Actual unchanged five-second Beat schedule, no manual dispatch.
    action('dispatch')
    time.sleep(2)
    repeated = action('state')
    assert len(repeated['profiles']) == repeated['results'] == 2
    report = {'status': 'passed', 'source_sha256': source_hash, 'runtime_image': image,
        'real_redis_prefork_beat': True, 'model_used': False,
        'initial': initial, 'outage': outage, 'recovered': recovered, 'repeated': repeated,
        'scope': 'synthetic SQLite; Redis outage/recovery, not worker mid-transaction crash'}
    (evidence / 'pipeline-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'status': 'passed', 'evidence': str(evidence)}), flush=True)


if __name__ == '__main__':
    main()
