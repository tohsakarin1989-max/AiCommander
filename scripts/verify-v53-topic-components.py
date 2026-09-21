#!/usr/bin/env python3
"""Disposable PostgreSQL/Redis/Celery proof; never connects to demo or production.

Uses already installed images, random loopback ports and tmpfs. The exact created
container IDs are removed at exit. Model and target-server acceptance are separate.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from threading import Barrier, Event
import time
from unittest.mock import patch
from uuid import uuid4


def main():
    if os.environ.get('AIC_DISPOSABLE_TOPICS') != '1':
        raise RuntimeError('explicit_disposable_test_required')
    root = Path(__file__).resolve().parents[1]
    image = 'aicommander-postgis-vector:16-0.8.6'
    containers, worker = [], None
    secret = secrets.token_hex(24)
    env = {key: os.environ[key] for key in ('PATH', 'LANG', 'TMPDIR') if key in os.environ}
    env.update(PYTHONPATH=str(root / 'backend'), ENVIRONMENT='test', SECRET_KEY=secrets.token_hex(32),
               ENABLE_VECTOR_DB='false', ENABLE_AGENT_LAB='false', AGENT_MODE='off',
               AGENT_USE_EXTERNAL_MODEL='false', AGENT_PROVIDER='deterministic', AUTO_CREATE_TABLES='false')

    def docker(*args, **kwargs):
        return subprocess.run(['docker', *args], check=True, capture_output=True,
                              env={**env, 'POSTGRES_PASSWORD': secret}, timeout=60, **kwargs)

    def container(image_name, port, *args):
        identity = 'aic-topic-check-' + uuid4().hex[:12]
        identifier = docker('run', '-d', '--pull=never', '--name', identity,
            '--label', 'aicommander.disposable=topic-verification', '-p', f'127.0.0.1::{port}',
            *args, image_name).stdout.decode().strip()
        containers.append(identifier)
        public_port = int(docker('port', identifier, str(port)).stdout.decode().strip().rsplit(':', 1)[1])
        return identifier, public_port

    def wait_until(predicate, message, seconds=45):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.25)
        raise RuntimeError(message)

    def stop_worker():
        nonlocal worker
        if worker is not None:
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
            worker = None

    try:
        pg, pg_port = container(image, 5432, '--tmpfs', '/var/lib/postgresql/data',
            '-e', 'POSTGRES_USER=aic_topic_test', '-e', 'POSTGRES_DB=aic_topic_test', '-e', 'POSTGRES_PASSWORD')
        redis_container, redis_port = container('redis:7-alpine', 6379, '--tmpfs', '/data')
        wait_until(lambda: subprocess.run(['docker', 'exec', pg, 'pg_isready', '-h', '127.0.0.1',
            '-U', 'aic_topic_test'], capture_output=True).returncode == 0, 'database_not_ready')
        url = f'postgresql://aic_topic_test:{secret}@127.0.0.1:{pg_port}/aic_topic_test'
        broker = f'redis://127.0.0.1:{redis_port}/0'
        queue = 'topic-check-' + uuid4().hex[:12]
        env.update(DATABASE_URL=url, REDIS_URL=broker, CELERY_BROKER_URL=broker,
                   CELERY_RESULT_BACKEND=broker, AGENT_REDIS_QUEUE=queue)
        with tempfile.TemporaryDirectory(prefix='aic-topics-components-') as temporary:
            os.chdir(temporary)  # Do not load the workspace .env.
            os.environ.clear()
            os.environ.update(env)
            sys.path.insert(0, str(root / 'backend'))
            from alembic import command
            from alembic.config import Config
            from sqlalchemy import create_engine, text
            from sqlalchemy.engine import make_url
            from sqlalchemy.orm import sessionmaker
            import app.models  # noqa: F401
            from app.models.case import Case
            from app.models.case_pipeline import CaseAnalysisProfile
            from app.models.analysis_topic import AnalysisTopic, TopicSnapshot
            from app.models.map_foundation import OperationalArea
            from app.services.auth_service import AuthService
            from app.services.case_pipeline_service import CasePipelineService
            from app.services import analysis_topic_service as topics
            from app.tasks.celery_app import celery_app
            config = Config(str(root / 'backend/alembic.ini'))
            config.set_main_option('script_location', str(root / 'backend/alembic'))
            command.upgrade(config, 'd72e31b86fa2')
            engine = create_engine(url)
            sessions = sessionmaker(bind=engine, autoflush=False)
            with sessions() as db:
                assert db.query(Case).count() == 0
                area = db.query(OperationalArea).filter_by(is_default=True).one()
                user = AuthService.create_user(db, username='synthetic-topics', display_name='合成组件验收',
                                              password=secrets.token_urlsafe(24), role='analyst')
                db.flush()
                uid, area_id = user.id, area.id
                case = Case(case_number='SYNTHETIC-BEFORE-UPGRADE', operational_area_id=area_id,
                            occurred_time=datetime(2026, 9, 9), description='井场发现软管。')
                db.add(case)
                db.commit()
                case_id = case.id
            before_dump = docker('exec', pg, 'pg_dump', '-U', 'aic_topic_test', '-Fc', 'aic_topic_test').stdout
            command.upgrade(config, 'head')
            with sessions() as db:
                db.info['principal_user_id'] = uid
                case = db.get(Case, case_id)
                assert case.description == '井场发现软管。'
                payload = CasePipelineService.build_profile_payload(db, case)
                db.add(CaseAnalysisProfile(id=str(uuid4()), case_id=case.id, profile_version=1,
                    source_hash=payload['source_hash'], schema_version=payload['schema_version'],
                    dictionary_version=payload['dictionary_version'], payload=payload,
                    quality_score=50, analysis_readiness='partial', is_current=True))
                db.commit()
                topic_id = topics.create_topic(db, '合成并发专题', {})['id']
            barrier = Barrier(2)
            def concurrent_refresh():
                with sessions() as db:
                    db.info['principal_user_id'] = uid
                    barrier.wait(timeout=10)
                    return topics.refresh_topic(db, topic_id)['status']
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = list(pool.map(lambda _: concurrent_refresh(), range(2)))
            assert 'updated' in statuses and set(statuses) <= {'updated', 'not_claimed', 'unchanged'}
            with sessions() as db:
                assert db.query(TopicSnapshot).count() == 1
                db.info['principal_user_id'] = uid
                topics.request_refresh(db, topic_id)
            entered, resume = Event(), Event()
            original = topics.build_aggregate
            def wait_in_scan(*args, **kwargs):
                entered.set()
                assert resume.wait(10)
                return original(*args, **kwargs)
            def refresh():
                with sessions() as db:
                    db.info['principal_user_id'] = uid
                    return topics.refresh_topic(db, topic_id)
            with patch.object(topics, 'build_aggregate', side_effect=wait_in_scan), ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(refresh)
                assert entered.wait(10)
                with sessions() as db:
                    db.info['principal_user_id'] = uid
                    topics.update_topic(db, topic_id, paused=True)
                resume.set()
                assert pending.result(timeout=15)['status'] == 'superseded'
            print('PostgreSQL upgrade, concurrent claim and pause race passed', flush=True)

            log = open(Path(temporary) / 'worker.log', 'w+')
            def launch_worker():
                return subprocess.Popen([sys.executable, '-m', 'celery', '-A', 'app.tasks.celery_app:celery_app',
                    'worker', '--pool=solo', '--concurrency=1', '-Q', queue,
                    '--without-gossip', '--without-mingle', '--without-heartbeat', '--loglevel=WARNING'],
                    cwd=temporary, env=env, stdout=log, stderr=subprocess.STDOUT)
            def revision(identifier):
                with sessions() as db:
                    return db.query(TopicSnapshot).filter_by(topic_id=identifier).count()
            with sessions() as db:
                db.info['principal_user_id'] = uid
                task_topic = topics.create_topic(db, '真实队列专题', {})['id']
            worker = launch_worker()
            celery_app.send_task('aicommander.topics.process_next', queue=queue)
            wait_until(lambda: revision(task_topic) == 1, 'real_worker_did_not_publish')
            stop_worker()
            # Redis outage does not lose the DB admission; no publish needed to save a topic.
            # Freeze Redis without reallocating Docker's random host port on
            # restart. A timed-out real PING proves the broker is unavailable.
            docker('pause', redis_container)
            from redis import Redis
            from redis.exceptions import TimeoutError as RedisTimeout
            probe = Redis.from_url(broker, socket_connect_timeout=0.2, socket_timeout=0.2,
                                   retry_on_timeout=False)
            try:
                probe.ping()
                raise AssertionError('broker_outage_not_observed')
            except RedisTimeout:
                pass
            finally:
                probe.close()
            with sessions() as db:
                db.info['principal_user_id'] = uid
                outage_topic = topics.create_topic(db, '断队列仍可保存', {})['id']
                assert db.get(AnalysisTopic, outage_topic).refresh_state == 'queued'
                # Expired persisted lease represents a previously interrupted worker.
                row = db.get(AnalysisTopic, task_topic)
                row.refresh_state, row.lease_token = 'running', 'synthetic-expired-worker'
                row.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
                db.commit()
            docker('unpause', redis_container)
            worker = launch_worker()
            celery_app.send_task('aicommander.topics.process_next', queue=queue)
            wait_until(lambda: revision(outage_topic) == 1, 'outage_queue_not_recovered')
            celery_app.send_task('aicommander.topics.process_next', queue=queue)
            def recovered():
                with sessions() as db:
                    return db.get(AnalysisTopic, task_topic).refresh_state == 'ready'
            wait_until(recovered, 'expired_lease_not_recovered')
            assert revision(task_topic) == 1  # recovery is idempotent
            stop_worker()
            log.close()
            print('Real Redis/Celery, broker interruption and expired lease recovery passed', flush=True)
            with sessions() as db:
                db.add(Case(case_number='SYNTHETIC-AFTER-UPGRADE', operational_area_id=area_id,
                    occurred_time=datetime(2026, 9, 21), description='升级后新增原始数据'))
                db.commit()
                expected = list(db.execute(text('SELECT row_to_json(cases)::text FROM cases ORDER BY id')).scalars())
                revision_id = db.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
            after_dump = docker('exec', pg, 'pg_dump', '-U', 'aic_topic_test', '-Fc', 'aic_topic_test').stdout
            for name, dump, version in [('aic_topics_restored', after_dump, revision_id),
                                       ('aic_topics_previous', before_dump, 'd72e31b86fa2')]:
                docker('exec', pg, 'createdb', '-U', 'aic_topic_test', name)
                docker('exec', '-i', pg, 'pg_restore', '-U', 'aic_topic_test', '--exit-on-error',
                       '--no-owner', '-d', name, input=dump)
                restored = create_engine(make_url(url).set(database=name))
                with restored.connect() as conn:
                    assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == version
                    if name == 'aic_topics_restored':
                        assert list(conn.execute(text('SELECT row_to_json(cases)::text FROM cases ORDER BY id')).scalars()) == expected
                        assert conn.execute(text('SELECT count(*) FROM topic_snapshots')).scalar_one() == 3
                    else:
                        assert conn.execute(text('SELECT count(*) FROM cases')).scalar_one() == 1
                        assert conn.execute(text("SELECT to_regclass('analysis_topics')")).scalar_one() is None
                restored.dispose()
            engine.dispose()
            print(json.dumps({'status': 'passed', 'synthetic_only': True, 'revision': revision_id,
                'postgres_image': image, 'concurrent_statuses': statuses, 'pause_race': 'passed',
                'redis_celery': 'passed', 'broker_recovery': 'passed', 'expired_lease_recovery': 'passed',
                'backup_restore': 'passed', 'previous_schema_restored_separately': True,
                'new_raw_rows_preserved': True, 'backup_sha256': hashlib.sha256(after_dump).hexdigest(),
                'target_server_verified': False, 'real_model_verified': False}, ensure_ascii=False), flush=True)
    finally:
        stop_worker()
        for identifier in reversed(containers):
            label = docker('inspect', '-f', '{{index .Config.Labels "aicommander.disposable"}}', identifier).stdout.decode().strip()
            if label != 'topic-verification':
                raise RuntimeError('refuse_cleanup_unowned_container')
            docker('rm', '-f', '-v', identifier)
        print('Only newly created disposable containers removed; demo services untouched', flush=True)


if __name__ == '__main__':
    main()
