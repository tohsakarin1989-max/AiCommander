"""Frozen local scale and v5.2 save comparison; not target-server acceptance."""
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


def topic_worker(root):
    from datetime import datetime
    from uuid import uuid4
    sys.path.insert(0, str(root / 'backend'))
    os.environ.update(DATABASE_URL='sqlite://', ENVIRONMENT='test', SECRET_KEY='synthetic-performance-only',
        ENABLE_VECTOR_DB='false', ENABLE_AGENT_LAB='false', AGENT_MODE='off',
        CELERY_BROKER_URL='memory://', CELERY_RESULT_BACKEND='cache+memory://')
    import app.models  # noqa: F401
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models.case import Case
    from app.models.case_pipeline import CaseAnalysisProfile
    from app.models.map_foundation import OperationalArea
    from app.models.user import User
    from app.services.case_pipeline_service import CasePipelineService
    from app.services import analysis_topic_service as topics
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as db:
        db.add(OperationalArea(id=1, code='topic-perf', name='合成性能辖区'))
        db.add(User(id=1, username='perf', display_name='合成账号', password_hash='no-login', role='admin'))
        db.flush()
        for index in range(2000):
            case = Case(case_number=f'SYNTHETIC-PERF-{index}', operational_area_id=1,
                occurred_time=datetime(2026, 9, 1), location='合成井场',
                description='井场发现软管。' if index % 2 else '井场未发现软管。')
            db.add(case)
            db.flush()
            payload = CasePipelineService.build_profile_payload(db, case)
            db.add(CaseAnalysisProfile(id=str(uuid4()), case_id=case.id, profile_version=1,
                source_hash=payload['source_hash'], schema_version=payload['schema_version'],
                dictionary_version=payload['dictionary_version'], payload=payload,
                quality_score=50, analysis_readiness='partial', is_current=True))
        db.commit()
        db.info['principal_user_id'] = 1
        identifier = topics.create_topic(db, '2000 条合成专题', {})['id']
        start = time.perf_counter()
        result = topics.refresh_topic(db, identifier)
        refresh_ms = (time.perf_counter() - start) * 1000
        assert result['status'] == 'updated'
        durations = []
        for page in range(1, 21):
            start = time.perf_counter()
            read = topics.read_topic(db, identifier, revision=1, page=page)
            durations.append((time.perf_counter() - start) * 1000)
            assert read['snapshot']['aggregate']['total'] == 2000
            assert read['snapshot']['aggregate']['coverage']['complete'] is True
        print(json.dumps({'cases': 2000, 'profiles': 2000, 'refresh_ms': refresh_ms,
            'read_p95_ms': sorted(durations)[18], 'pages': 20, 'full_count_each_page': 2000,
            'within_refresh_budget': refresh_ms < 90000, 'environment': 'local SQLite in memory',
            'raw_cases_unchanged': db.query(Case).count() == 2000}), flush=True)
    engine.dispose()


def main():
    root = Path(__file__).resolve().parents[1]
    clean = {key: os.environ[key] for key in ('PATH', 'LANG', 'TMPDIR') if key in os.environ}
    with tempfile.TemporaryDirectory(prefix='v53-performance-') as folder:
        baseline = Path(folder)
        archive = subprocess.run(['git', 'archive', 'v5.2.0-stable', 'backend/app'],
            cwd=root, check=True, capture_output=True).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(baseline, filter='data')
        result = {'baseline': [], 'candidate': []}
        for sequence in (('baseline', 'candidate'), ('candidate', 'baseline'), ('baseline', 'candidate')):
            for name in sequence:
                backend = baseline / 'backend' if name == 'baseline' else root / 'backend'
                run = subprocess.run([sys.executable, str(root / 'scripts/verify-v52-save-performance.py'),
                    '--worker', str(backend)], cwd=folder, env=clean, capture_output=True, text=True, timeout=60)
                if run.returncode:
                    raise RuntimeError(f'{name} save benchmark failed: {run.stderr[-2000:]}')
                result[name].append(json.loads(run.stdout.splitlines()[-1]))
        old = statistics.median(row['p95_ms'] for row in result['baseline'])
        new = statistics.median(row['p95_ms'] for row in result['candidate'])
        print(json.dumps({**result, 'baseline_ref': 'v5.2.0-stable',
            'median_p95_change_percent': (new / old - 1) * 100, 'within_five_percent_target': new <= old * 1.05,
            'environment': 'local Python / SQLite in memory', 'target_server_verified': False}), flush=True)
        run = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--topic-worker'],
            cwd=folder, env=clean, capture_output=True, text=True, timeout=120)
        if run.returncode:
            raise RuntimeError('topic benchmark failed: ' + run.stderr[-2000:])
        print(run.stdout.splitlines()[-1], flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['--topic-worker']:
        topic_worker(Path(__file__).resolve().parents[1])
    else:
        main()
