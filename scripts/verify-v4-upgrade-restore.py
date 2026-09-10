#!/usr/bin/env python3
"""Disposable PostgreSQL v3.6 -> current -> compatible restore rehearsal.

Never accepts a business DB URL or uses deployment credentials. Dumps contain
synthetic data only and are retained; only the container created here is removed.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

DOCKER = '/opt/homebrew/bin/docker'
IMAGE = 'postgis/postgis:16-3.4-alpine@sha256:681931a625df344215e9b8998bf34daf146b6a395ceacee4439eb9c85869239f'
DATABASES = ('aic_upgrade', 'aic_old_restore', 'aic_new_restore')


def dump_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str))


def worker(args):
    args.backend = str(Path(args.backend).resolve())
    args.output = str(Path(args.output).resolve())
    if args.expected:
        args.expected = str(Path(args.expected).resolve())
    with tempfile.TemporaryDirectory(prefix='aic-upgrade-worker-') as isolated:
        os.chdir(isolated)
        run_worker(args)


def run_worker(args):
    backend = Path(args.backend).resolve()
    output = Path(args.output).resolve()
    expected = json.loads(Path(args.expected).read_text()) if args.expected else None
    password = os.environ['AIC_REHEARSAL_PASSWORD']
    os.environ.clear()
    os.environ.update(DATABASE_URL=f'postgresql://aic_rehearsal:{password}@127.0.0.1:{args.port}/{args.database}',
                      SECRET_KEY='synthetic-upgrade-restore-only', ENABLE_VECTOR_DB='false',
                      ENABLE_AGENT_LAB='false', AGENT_MODE='off', AUTH_REQUIRED='true',
                      AUTO_CREATE_TABLES='false', SESSION_COOKIE_SECURE='false',
                      ALLOWED_HOSTS='testserver', FRONTEND_URL='http://testserver',
                      CORS_ORIGINS='http://testserver', REDIS_URL='unix:///nonexistent-aic-rehearsal.sock',
                      CELERY_BROKER_URL='memory://', CELERY_RESULT_BACKEND='cache+memory://')
    sys.path.insert(0, str(backend))
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect, text
    from app.database import engine, SessionLocal

    def migrate():
        config = Config(str(backend / 'alembic.ini'))
        config.set_main_option('script_location', str(backend / 'alembic'))
        command.upgrade(config, 'head')

    def inventory(columns=None):
        result = {}
        inspector = inspect(engine)
        names = sorted(columns) if columns else inspector.get_table_names()
        with engine.connect() as connection:
            for name in names:
                if name in ('alembic_version', 'spatial_ref_sys'):
                    continue
                fields = columns[name]['columns'] if columns else [c['name'] for c in inspector.get_columns(name)]
                quote = engine.dialect.identifier_preparer.quote
                rows = connection.execute(text(f'SELECT {", ".join(map(quote, fields))} FROM {quote(name)}')).all()
                serialized = sorted(json.dumps(list(row), default=str, ensure_ascii=False, sort_keys=True) for row in rows)
                result[name] = {'columns': fields, 'count': len(rows),
                                'sha256': hashlib.sha256('\n'.join(serialized).encode()).hexdigest()}
        return result

    if args.phase in ('seed', 'upgrade'):
        migrate()
    if expected:
        actual = inventory(expected['tables'])
        assert actual == expected['tables'], 'existing_table_data_changed'
    from app.main import app
    from app.models.case import Case
    from app.models.map_foundation import OperationalArea
    from app.models.jurisdiction import JurisdictionAsset
    from app.models.meeting import Meeting
    from app.models.report import Report
    from app.models.user import User
    from app.services.auth_service import AuthService
    from fastapi.testclient import TestClient

    if args.phase == 'seed':
        with SessionLocal() as db:
            assert db.query(Case).count() == 0
            area = db.query(OperationalArea).order_by(OperationalArea.id).first()
            assert area is not None
            db.add(User(username='upgrade-rehearsal', display_name='合成管理员', role='admin',
                        password_hash=AuthService.hash_password('Synthetic-upgrade-123!')))
            db.add(JurisdictionAsset(name='升级演练合成井', asset_type='well',
                        operational_area_id=area.id, latitude=46.6, longitude=125.1))
            db.commit()
    with TestClient(app) as client:
        assert client.post('/api/auth/login', json={'username': 'upgrade-rehearsal',
            'password': 'Synthetic-upgrade-123!'}, headers={'Origin': 'http://testserver'}).status_code == 200
        if args.phase in ('seed', 'upgrade'):
            with SessionLocal() as db:
                area_id = db.query(OperationalArea.id).order_by(OperationalArea.id).first()[0]
            number = 'SYNTHETIC-BEFORE' if args.phase == 'seed' else 'SYNTHETIC-AFTER'
            response = client.post('/api/cases/', json={
                'case_number': number, 'occurred_time': '2026-09-10T01:00:00',
                'description': number + ' 合成原文', 'operational_area_id': area_id,
                'location': '合成位置', 'case_type': '涉油盗窃', 'latitude': 46.6, 'longitude': 125.1,
            }, headers={'Origin': 'http://testserver'})
            assert response.status_code == 200, response.text
        if args.phase == 'seed':
            with SessionLocal() as db:
                meeting = Meeting(meeting_id='SYNTHETIC-MEETING', case_ids=[1],
                                  operational_area_id=area_id, status='completed')
                db.add(meeting)
                db.flush()
                report = Report(meeting_id=meeting.meeting_id, report_type='summary',
                                content={'summary': '合成历史报告，非实际研判'})
                db.add(report)
                db.flush()
                meeting.final_report_id = report.id
                db.commit()
        response = client.get('/api/cases/1')
        assert response.status_code == 200 and response.json()['description'] == 'SYNTHETIC-BEFORE 合成原文'
        response = client.get('/api/reports/1')
        assert response.status_code == 200, response.text
        assert response.json()['content']['summary'] == '合成历史报告，非实际研判'
    with engine.connect() as connection:
        revision = connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
        postgis = connection.execute(text('SELECT postgis_lib_version()')).scalar_one()
    dump_json(output, {'phase': args.phase, 'revision': revision, 'postgis': postgis,
                      'tables': inventory(), 'existing_rows_verified': bool(expected),
                      'authenticated_case_and_report_read': True})
    engine.dispose()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('seed', 'upgrade', 'verify'))
    parser.add_argument('--backend')
    parser.add_argument('--port', type=int)
    parser.add_argument('--database', choices=DATABASES)
    parser.add_argument('--output')
    parser.add_argument('--expected')
    args = parser.parse_args()
    if args.phase:
        if not all((args.backend, args.port, args.database, args.output)):
            parser.error('worker arguments missing')
        worker(args)
        return
    root = Path(__file__).resolve().parents[1]
    parent = root / 'output/validation/upgrade-restore'
    parent.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix='run-', dir=parent))
    password = secrets.token_hex(24)
    container = None

    def docker(*arguments, **kwargs):
        return subprocess.run([DOCKER, *arguments], check=True, **kwargs)

    with tempfile.TemporaryDirectory(prefix='aic-upgrade-code-') as temporary:
        temporary = Path(temporary)
        baseline = subprocess.check_output(['git', 'rev-parse', 'v3.6.0-stable^{commit}'], cwd=root, text=True).strip()
        archive = subprocess.check_output(['git', 'archive', baseline, 'backend', 'VERSION'], cwd=root)
        old = temporary / 'old'
        old.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(old, filter='data')
        current = temporary / 'current'
        for name in ('app', 'alembic'):
            shutil.copytree(root / 'backend' / name, current / 'backend' / name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copy2(root / 'backend/alembic.ini', current / 'backend/alembic.ini')
        shutil.copy2(root / 'VERSION', current / 'VERSION')
        source_hash = hashlib.sha256()
        for path in sorted(current.rglob('*')):
            if path.is_file():
                source_hash.update(str(path.relative_to(current)).encode() + b'\0' + path.read_bytes())
        try:
            container = docker('run', '-d', '--pull=never', '--platform=linux/amd64',
                '--name', 'aic-upgrade-' + evidence.name, '-e', 'POSTGRES_USER=aic_rehearsal',
                '-e', 'POSTGRES_PASSWORD', '-e', 'POSTGRES_DB=aic_upgrade',
                '-p', '127.0.0.1::5432', IMAGE, capture_output=True, text=True,
                env={**os.environ, 'POSTGRES_PASSWORD': password}).stdout.strip()
            for _ in range(60):
                ready = subprocess.run([DOCKER, 'exec', container, 'pg_isready',
                    '-h', '127.0.0.1', '-U', 'aic_rehearsal'], capture_output=True)
                if ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError('disposable_postgres_not_ready')
            port = int(docker('port', container, '5432', capture_output=True, text=True).stdout.strip().rsplit(':', 1)[1])

            def stage(name, source, phase, database, expected=None):
                target = evidence / f'{name}.json'
                command = [sys.executable, str(Path(__file__).resolve()), '--phase', phase,
                           '--backend', str(source / 'backend'), '--port', str(port),
                           '--database', database, '--output', str(target)]
                if expected:
                    command += ['--expected', str(expected)]
                with (evidence / f'{name}.log').open('w') as log:
                    subprocess.run(command, env={'PATH': os.environ.get('PATH', ''),
                        'AIC_REHEARSAL_PASSWORD': password}, cwd=temporary, stdout=log,
                        stderr=subprocess.STDOUT, check=True, timeout=180)
                print(f'{name}: passed', flush=True)
                return target

            def backup(name):
                target = evidence / f'{name}.dump'
                with target.open('wb') as output:
                    docker('exec', container, 'pg_dump', '-U', 'aic_rehearsal', '-Fc', 'aic_upgrade', stdout=output)
                return target

            def restore(source, database):
                docker('exec', container, 'createdb', '-U', 'aic_rehearsal', database)
                with source.open('rb') as source_file:
                    docker('exec', '-i', container, 'pg_restore', '-U', 'aic_rehearsal',
                           '--exit-on-error', '--no-owner', '--no-privileges', '-d', database, stdin=source_file)

            before = stage('before', old, 'seed', 'aic_upgrade')
            old_dump = backup('before')
            after = stage('after', current, 'upgrade', 'aic_upgrade', before)
            assert json.loads(before.read_text())['tables']['cases']['count'] == 1
            assert json.loads(after.read_text())['tables']['cases']['count'] == 2
            new_dump = backup('after')
            restore(old_dump, 'aic_old_restore')
            stage('old-restored', old, 'verify', 'aic_old_restore', before)
            restore(new_dump, 'aic_new_restore')
            stage('new-restored', current, 'verify', 'aic_new_restore', after)
            # Verify the still-existing upgraded DB before declaring rollback safe.
            stage('upgraded-preserved', current, 'verify', 'aic_upgrade', after)
            dump_json(evidence / 'report.json', {'baseline_commit': baseline, 'image': IMAGE,
                'current_source_sha256': source_hash.hexdigest(),
                'status': 'passed', 'synthetic_only': True, 'old_restore_overwrote_current': False,
                'before_dump_sha256': hashlib.sha256(old_dump.read_bytes()).hexdigest(),
                'after_dump_sha256': hashlib.sha256(new_dump.read_bytes()).hexdigest(),
                'target_server_verified': False, 'map_file_volume_verified': False})
            print(str(evidence / 'report.json'), flush=True)
        finally:
            if container:
                docker('rm', '-f', '-v', container, capture_output=True)


if __name__ == '__main__':
    main()
