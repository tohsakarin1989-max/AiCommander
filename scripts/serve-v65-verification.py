#!/usr/bin/env python3
"""Full application and durable workers over disposable synthetic data only.

Explicit opt-in; never reads a local .env, production database, or model config.
The one-pixel test basemap exercises offline rendering, not geographic coverage.
"""
import os
from pathlib import Path
import sys
import tempfile


def main():
    if os.environ.get('AIC_V65_SYNTHETIC_ONLY') != '1':
        raise RuntimeError('explicit_disposable_verification_required')
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository / 'backend'))
    with tempfile.TemporaryDirectory(prefix='aic-v65-browser-') as directory:
        os.chdir(directory)
        retained = {key: os.environ[key] for key in ('PATH', 'LANG', 'TMPDIR') if key in os.environ}
        os.environ.clear()
        os.environ.update(retained)
        os.environ.update(
            DATABASE_URL=f'sqlite:///{directory}/synthetic.sqlite',
            MAP_PACKAGE_ROOT=f'{directory}/maps', SECRET_KEY='isolated-v65-browser-only',
            ENVIRONMENT='test', AUTH_REQUIRED='true', AUTO_CREATE_TABLES='false',
            ENABLE_VECTOR_DB='false', ENABLE_LEGACY_OPERATIONS_MODULES='false',
            ENABLE_BONUS_ACCOUNTING='true', ENABLE_AGENT_LAB='false', ENABLE_SHOWCASE='true',
            ENABLE_INTELLIGENT_QUERY='true', AGENT_MODE='off', AGENT_USE_EXTERNAL_MODEL='false',
            AGENT_PROVIDER='deterministic', REDIS_URL=f'unix://{directory}/disabled.sock',
            CELERY_BROKER_URL='memory://', CELERY_RESULT_BACKEND='cache+memory://',
            SESSION_COOKIE_SECURE='false', SESSION_COOKIE_NAME='aic_v65_verification',
            FRONTEND_URL='http://127.0.0.1:13065', CORS_ORIGINS='http://127.0.0.1:13065',
            ALLOWED_HOSTS='127.0.0.1,localhost',
        )
        from datetime import datetime, timedelta, timezone
        import app.models  # noqa: F401
        from app.database import Base, engine, SessionLocal
        from app.models.map_foundation import OperationalArea
        from app.models.jurisdiction import JurisdictionAsset
        from app.services.auth_service import AuthService
        from app.services.case_service import CaseService
        from app.services.case_pipeline_service import CasePipelineService
        from app.services.offline_map_service import OfflineMapService
        from tests.test_offline_maps import _bundle_bytes
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            db.add(OperationalArea(id=1, code='v65-synthetic', name='合成验证厂区', is_default=True,
                boundary={'type': 'Polygon', 'coordinates': [[[124.5, 46.2], [125.5, 46.2], [125.5, 46.8], [124.5, 46.8], [124.5, 46.2]]]}))
            db.flush()
            for role in ('admin', 'analyst', 'viewer'):
                AuthService.create_user(db, username=f'v65-{role}', display_name=f'合成验证{role}',
                    password='Disposable-V65-Only!', role=role)
            db.commit()
            for index in range(6):
                CaseService.create_case(db, f'V65-SYNTHETIC-{index+1}',
                    description='合成验证材料，非真实案件。夜间在井场发现胶管，未发现车辆。查获原油120升，去向不详。',
                    occurred_time=datetime.now(timezone.utc)-timedelta(days=index+1),
                    location='合成验证井场', latitude=46.5+index/1000, longitude=125.1+index/1000,
                    case_type='涉油盗窃', oil_type='原油', operational_area_id=1)
            db.add(JurisdictionAsset(name='合成验证井', asset_type='well', operational_area_id=1,
                latitude=46.5, longitude=125.1, verified=True, attributes={'oil_type': '原油'}))
            db.commit()
            bundle, _ = OfflineMapService.import_bundle(db, filename='synthetic-map.zip',
                content=_bundle_bytes(Path(directory), attribution='合成一像素验包底图，不代表真实地图覆盖'), imported_by=1)
            snapshot, _ = OfflineMapService.build_snapshot(db, operational_area_id=1, public_bundle_id=bundle.id, built_by=1)
            OfflineMapService.publish_snapshot(db, snapshot.id)
            CasePipelineService.process_pending(db, limit=50)

        from app.main import app
        from app.services.intelligent_query_worker import process_next
        from app.services.analysis_topic_service import process_next_topic
        from threading import Event, Thread
        import asyncio
        import uvicorn
        stopped = Event()

        def worker():
            while not stopped.wait(0.5):
                try:
                    with SessionLocal() as db:
                        asyncio.run(process_next(db))
                    with SessionLocal() as db:
                        process_next_topic(db)
                    with SessionLocal() as db:
                        CasePipelineService.process_pending(db, limit=5)
                except Exception as error:
                    print(f'Synthetic worker error: {type(error).__name__}: {error}', flush=True)

        thread = Thread(target=worker, daemon=True)
        thread.start()
        try:
            uvicorn.run(app, host='127.0.0.1', port=18065, access_log=False)
        finally:
            stopped.set()
            thread.join(timeout=5)
            engine.dispose()


if __name__ == '__main__':
    main()
