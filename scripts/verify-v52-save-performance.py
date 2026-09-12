"""Fixed synthetic SQLite save benchmark against the retained v4.5 source.

Measures the complete synchronous CaseService.create_case call, including its
post-commit hooks. Not an HTTP, PostgreSQL or target-server latency claim.
"""
import io
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time


def worker(backend):
    from datetime import datetime
    import secrets
    sys.path.insert(0, str(backend))
    os.environ.update(DATABASE_URL='sqlite://', ENVIRONMENT='test', SECRET_KEY=secrets.token_hex(32),
        ENABLE_VECTOR_DB='false', ENABLE_AGENT_LAB='false', AGENT_MODE='off',
        CELERY_BROKER_URL='memory://', CELERY_RESULT_BACKEND='cache+memory://')
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import app.models  # noqa: F401
    from app.database import Base
    from app.models.case import Case
    from app.models.user import User
    from app.models.map_foundation import OperationalArea
    from app.services.case_service import CaseService
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    elapsed = []
    with Session(engine) as db:
        db.add(OperationalArea(id=1, code='performance', name='合成辖区'))
        db.add(User(id=1, username='performance', display_name='合成性能账号', password_hash='not-a-login', role='admin'))
        db.flush()
        db.add_all([Case(case_number=f'FIXED-{i}', operational_area_id=1,
            occurred_time=datetime(2020, 1, 1), description='固定合成历史案件。') for i in range(500)])
        db.commit()
        db.info.update(authorized_area_ids=(1,), area_access_levels={1: 'manage'}, principal_user_id=1)
        for i in range(110):
            start = time.perf_counter()
            CaseService.create_case(db, case_number=f'BENCH-{i}', operational_area_id=1,
                occurred_time=datetime(2026, 9, 1), location='合成井场',
                description='夜间在井场发现胶管转运原油的合成记录，实际来源待核。',
                oil_type='原油', facility_type='井口')
            if i >= 10:
                elapsed.append((time.perf_counter() - start) * 1000)
        assert db.query(Case).count() == 610
    engine.dispose()
    print(json.dumps({'p95_ms': sorted(elapsed)[94], 'median_ms': statistics.median(elapsed),
                      'samples': len(elapsed), 'seed_cases': 500}))


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='v52-save-check-') as folder:
        baseline = Path(folder)
        archive = subprocess.run(['git', 'archive', 'v4.5.0-stable', 'backend/app'],
            cwd=root, check=True, capture_output=True).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(baseline, filter='data')
        result = {'baseline': [], 'candidate': []}
        # Alternate the order, identical interpreter and generated inputs.
        for sequence in (('baseline', 'candidate'), ('candidate', 'baseline'), ('baseline', 'candidate')):
            for name in sequence:
                backend = baseline / 'backend' if name == 'baseline' else root / 'backend'
                env = {key: os.environ[key] for key in ('PATH', 'LANG', 'TMPDIR') if key in os.environ}
                run = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', str(backend)],
                    cwd=folder, env=env, capture_output=True, text=True, timeout=60)
                if run.returncode:
                    raise RuntimeError(f'{name} synthetic worker failed: {run.stderr[-2500:]}')
                result[name].append(json.loads(run.stdout.splitlines()[-1]))
        old = statistics.median(row['p95_ms'] for row in result['baseline'])
        new = statistics.median(row['p95_ms'] for row in result['candidate'])
        print(json.dumps({**result, 'median_p95_change_percent': (new / old - 1) * 100,
            'within_five_percent_target': new <= old * 1.05, 'environment': 'local Python / SQLite in memory',
            'real_model': False, 'http_latency_measured': False, 'target_server_verified': False}))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        worker(Path(sys.argv[2]))
    else:
        main()
