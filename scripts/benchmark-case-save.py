#!/usr/bin/env python3
"""Compare authenticated case-save requests against the frozen v3.6 tag.

Only temporary synthetic SQLite databases are used. This is an in-process API
benchmark, not a target-server/PostgreSQL/concurrency certification.
"""
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time


def percentile(values, p):
    return sorted(values)[math.ceil(len(values) * p) - 1]


def worker(backend, output):
    backend = Path(backend).resolve()
    output = Path(output).resolve()
    with tempfile.TemporaryDirectory(prefix='aic-save-db-') as directory:
        os.chdir(directory)
        retained = {k: os.environ[k] for k in ('PATH', 'LANG', 'TMPDIR') if k in os.environ}
        os.environ.clear()
        os.environ.update(retained)
        os.environ.update(
            DATABASE_URL=f'sqlite:///{directory}/synthetic.sqlite',
            SECRET_KEY='synthetic-case-save-benchmark-only', AUTH_REQUIRED='true',
            SESSION_COOKIE_SECURE='false', AUTO_CREATE_TABLES='false',
            ENABLE_VECTOR_DB='false', ENABLE_AGENT_LAB='false', AGENT_MODE='off',
            ALLOWED_HOSTS='testserver', FRONTEND_URL='http://testserver',
            CORS_ORIGINS='http://testserver',
            REDIS_URL=f'unix://{directory}/absent.sock',
            CELERY_BROKER_URL='memory://', CELERY_RESULT_BACKEND='cache+memory://',
        )

        def deny_network(event, args):
            if event == 'socket.connect':
                raise RuntimeError('benchmark_network_access_forbidden')

        sys.addaudithook(deny_network)
        sys.path.insert(0, str(backend))
        from fastapi.testclient import TestClient
        from app.main import app
        from app.database import Base, SessionLocal, engine
        from app.models.case import Case
        from app.models.case_pipeline import OutboxEvent
        from app.models.map_foundation import OperationalArea, UserAreaScope
        from app.models.user import User
        from app.services.auth_service import AuthService
        from datetime import datetime, timedelta

        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            db.add(OperationalArea(id=1, code='synthetic', name='合成测试区', is_default=True))
            db.add(User(id=1, username='save-benchmark', display_name='合成分析员',
                        role='analyst', password_hash=AuthService.hash_password('Synthetic-save-123!')))
            db.flush()
            db.add(UserAreaScope(user_id=1, operational_area_id=1, access_level='write'))
            for index in range(1000):
                db.add(Case(case_number=f'SYNTHETIC-HISTORY-{index:04}',
                            operational_area_id=1, status='pending', case_type='涉油盗窃',
                            occurred_time=datetime(2026, 9, 1) - timedelta(hours=index),
                            description='合成历史案件：车辆转运线索待核验。',
                            oil_type='原油', facility_type='井口', modus_operandi='车辆转运',
                            latitude=46.0 + (index % 100) * .01,
                            longitude=124.0 + (index % 100) * .01))
            db.commit()
        payload = dict(occurred_time='2026-09-10T01:00:00', operational_area_id=1,
                       location='合成测试地点', case_type='涉油盗窃',
                       description='合成测试案件：发现井口损失，车辆转运，来源去向待核验。',
                       oil_type='原油', facility_type='井口', modus_operandi='车辆转运',
                       latitude=46.6, longitude=125.1)
        samples = []
        with TestClient(app) as client:
            login = client.post('/api/auth/login', json={
                'username': 'save-benchmark', 'password': 'Synthetic-save-123!'},
                headers={'Origin': 'http://testserver'})
            assert login.status_code == 200, login.text
            for index in range(110):
                start = time.perf_counter_ns()
                response = client.post('/api/cases/', json=payload,
                                       headers={'Origin': 'http://testserver'})
                elapsed = (time.perf_counter_ns() - start) / 1_000_000
                assert response.status_code == 200, response.text
                assert response.json()['description'] == payload['description']
                if index >= 10:
                    samples.append(elapsed)
        with SessionLocal() as db:
            assert db.query(Case).count() == 1110
            assert db.query(OutboxEvent).filter_by(event_type='case.analysis.requested').count() == 110
            assert db.query(Case.case_number).distinct().count() == 1110
        report = dict(samples_ms=samples, p95_ms=percentile(samples, .95),
                      median_ms=statistics.median(samples), saved=110, warmup=10,
                      seed_cases=1000, automatic_number=True, authenticated_role='analyst',
                      database='temporary-file-sqlite', transport='TestClient-ASGI',
                      network_connections_allowed=False, outbox_events=110)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker-backend')
    parser.add_argument('--output')
    args = parser.parse_args()
    if args.worker_backend:
        if not args.output:
            parser.error('--output required for worker')
        worker(args.worker_backend, args.output)
        return
    root = Path(__file__).resolve().parents[1]
    result_root = root / 'output/validation/case-save-performance'
    result_root.mkdir(parents=True, exist_ok=True)
    results = Path(tempfile.mkdtemp(prefix='run-', dir=result_root))
    baseline = subprocess.check_output(
        ['git', 'rev-parse', 'v3.6.0-stable^{commit}'], cwd=root, text=True).strip()
    with tempfile.TemporaryDirectory(prefix='aic-save-baseline-') as directory:
        # Freeze both sides; ongoing workspace edits must not mix code versions.
        frozen_current = Path(directory) / 'current'
        shutil.copytree(root / 'backend/app', frozen_current / 'backend/app',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copy2(root / 'VERSION', frozen_current / 'VERSION')
        digest = hashlib.sha256()
        for path in sorted((frozen_current / 'backend/app').rglob('*.py')):
            digest.update(str(path.relative_to(frozen_current)).encode() + b'\0' + path.read_bytes())
        archive = subprocess.check_output(['git', 'archive', baseline, 'backend', 'VERSION'], cwd=root)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(directory, filter='data')
        records = []
        # Reverse the middle pair to limit systematic order bias; never discard a run.
        for index, label in enumerate(('baseline', 'current', 'current', 'baseline', 'baseline', 'current')):
            backend = Path(directory) / 'backend' if label == 'baseline' else frozen_current / 'backend'
            target = results / f'{index}-{label}.json'
            with (results / f'{index}-{label}.log').open('w') as log:
                completed = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                    '--worker-backend', str(backend), '--output', str(target)],
                    cwd=directory, stdout=log, stderr=subprocess.STDOUT, timeout=300)
            if completed.returncode:
                raise RuntimeError(f'{label} failed: inspect {results / f"{index}-{label}.log"}')
            record = json.loads(target.read_text())
            records.append(dict(label=label, **record))
            print(json.dumps({'run': index, 'label': label, 'p95_ms': record['p95_ms']}), flush=True)
    pooled = {label: [v for row in records if row['label'] == label for v in row['samples_ms']]
              for label in ('baseline', 'current')}
    p95 = {label: percentile(values, .95) for label, values in pooled.items()}
    change = p95['current'] / p95['baseline'] - 1
    report = dict(baseline_commit=baseline, current_app_sha256=digest.hexdigest(),
                  platform=platform.platform(), python=sys.version, records=records,
                  pooled_p95_ms=p95, change_ratio=change, local_gate_passed=change <= .05,
                  target_server_verified=False, postgresql_verified=False,
                  concurrent_workload_verified=False)
    from importlib.metadata import version
    report['shared_dependency_versions'] = {
        name: version(name) for name in ('fastapi', 'sqlalchemy', 'pydantic', 'httpx')}
    (results / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'report': str(results / 'report.json'), 'p95_ms': p95,
                      'change_ratio': change, 'local_gate_passed': change <= .05}))
    if change > .05:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
