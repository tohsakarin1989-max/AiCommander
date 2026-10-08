#!/usr/bin/env python3
"""Disposable browser integration: synthetic records, real rules, no model."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Event, Thread
from types import SimpleNamespace


def main():
    if os.environ.get('AIC_V8_SYNTHETIC_ONLY') != '1':
        raise RuntimeError('explicit_synthetic_verification_required')
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository / 'backend'))
    with tempfile.TemporaryDirectory(prefix='aic-v8-browser-') as directory:
        root = Path(directory)
        os.chdir(root)
        retained = {key: os.environ[key] for key in ('PATH', 'LANG', 'TMPDIR') if key in os.environ}
        os.environ.clear()
        os.environ.update(retained)
        os.environ.update(DATABASE_URL=f'sqlite:///{root}/synthetic.sqlite', MAP_PACKAGE_ROOT=f'{root}/maps',
            SECRET_KEY='isolated-v8-browser-only', ENVIRONMENT='test', AUTH_REQUIRED='true',
            AUTO_CREATE_TABLES='false', ENABLE_VECTOR_DB='false', ENABLE_INTELLIGENT_QUERY='true',
            ENABLE_AGENT_LAB='false', AGENT_MODE='off', AGENT_USE_EXTERNAL_MODEL='false',
            AGENT_PROVIDER='deterministic', REDIS_URL=f'unix://{root}/absent.sock',
            CELERY_BROKER_URL='memory://', CELERY_RESULT_BACKEND='cache+memory://',
            SESSION_COOKIE_SECURE='false', SESSION_COOKIE_NAME='aic_v8_verification',
            FRONTEND_URL='http://127.0.0.1:13084', CORS_ORIGINS='http://127.0.0.1:13084',
            ALLOWED_HOSTS='127.0.0.1,localhost')
        import app.models  # noqa: F401
        from app.database import Base, engine, SessionLocal, bind_principal_scope
        from app.models.map_foundation import OperationalArea
        from app.services.auth_service import AuthService
        from app.services.offline_map_service import OfflineMapService
        from app.services.case_service import CaseService
        from app.services.case_pipeline_service import CasePipelineService
        from app.services.intelligent_query_worker import process_next
        from tests.test_offline_maps import _bundle_bytes
        from tests.history_index_helpers import build_history_index
        Base.metadata.create_all(engine)
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            db.add(OperationalArea(id=1, code='v8-synthetic', name='8.x 合成验收厂区', is_default=True,
                boundary={'type': 'Polygon', 'coordinates': [[[124.5,46.2],[125.5,46.2],[125.5,46.8],[124.5,46.8],[124.5,46.2]]]}))
            db.flush()
            user = AuthService.create_user(db, username='v8-check', display_name='合成验证账号',
                password='Disposable-V8-Only!', role='admin')
            db.commit()
            bind_principal_scope(db, SimpleNamespace(user_id=user.id, role='admin'), method='POST')
            bundle, _ = OfflineMapService.import_bundle(db, filename='synthetic.zip',
                content=_bundle_bytes(root, attribution='合成一像素底图，只验证离线服务，不代表两市覆盖'), imported_by=user.id)
            snapshot, _ = OfflineMapService.build_snapshot(db, operational_area_id=1, public_bundle_id=bundle.id, built_by=user.id)
            OfflineMapService.publish_snapshot(db, snapshot.id)
            identifiers = []
            for index, (text, days) in enumerate([
                    ('夜间，现场发现软管。本单位已移交，来源去向未获反馈。', 2),
                    ('夜里发现胶管。来源仍待核。', 50), ('夜间，未发现软管，发现货车。', 70)]):
                case = CaseService.create_case(db, case_number=f'SYN-V8-{index+1}',
                    operational_area_id=1, description=text, location='合成现场地点',
                    discovered_at=now-timedelta(days=days), time_precision='unknown',
                    initial_locations=[{'role':'discovery', 'description':'合成发现地点', 'precision':'exact',
                        'geometry': {'type':'Point', 'coordinates':[125.1+index*.001,46.5]}, 'source_note':'合成验证'}])
                identifiers.append(case.id)
                # Both old observations were entered in the last completed day,
                # not today (the comparison ends at today's business midnight).
                case.created_at = now - timedelta(days=1)
                db.commit()
            CasePipelineService.process_pending(db)
            build_history_index(db)
            print(json.dumps({'synthetic_only':True, 'case_ids':identifiers, 'map_snapshot':snapshot.id,
                'fixture_directory':str(root)}, ensure_ascii=False), flush=True)
        stopped = Event()
        def worker():
            while not stopped.wait(.5):
                try:
                    with SessionLocal() as db:
                        CasePipelineService.process_pending(db)
                    with SessionLocal() as db:
                        asyncio.run(process_next(db))
                except Exception as error:
                    print('synthetic_worker_error:' + type(error).__name__, flush=True)
        thread = Thread(target=worker, daemon=True)
        thread.start()
        import uvicorn
        from app.main import app
        try:
            uvicorn.run(app, host='127.0.0.1', port=18084, access_log=False)
        finally:
            stopped.set(); thread.join(timeout=5); engine.dispose()


if __name__ == '__main__':
    main()
