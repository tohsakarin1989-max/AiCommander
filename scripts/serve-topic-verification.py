#!/usr/bin/env python3
"""Full authenticated API, disposable synthetic data, local topic worker only.

This is a UI integration fixture, not Redis/Celery or production acceptance.
Never points at the user's database or inherits model credentials.
"""
import os
from pathlib import Path
import sys
import tempfile


def main():
    if os.environ.get('AIC_DISPOSABLE_TOPICS') != '1':
        raise RuntimeError('explicit_disposable_test_required')
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository / 'backend'))
    with tempfile.TemporaryDirectory(prefix='aic-topics-http-') as directory:
        os.chdir(directory)
        retained = {key: os.environ[key] for key in ('PATH', 'LANG', 'TMPDIR') if key in os.environ}
        os.environ.clear()
        os.environ.update(retained)
        os.environ.update(DATABASE_URL=f'sqlite:///{directory}/synthetic.sqlite',
            MAP_PACKAGE_ROOT=f'{directory}/maps', SECRET_KEY='disposable-topic-test-only',
            ENVIRONMENT='test', AUTH_REQUIRED='true', AUTO_CREATE_TABLES='false',
            ENABLE_VECTOR_DB='false', ENABLE_AGENT_LAB='true', AGENT_MODE='shadow',
            AGENT_USE_EXTERNAL_MODEL='false', AGENT_PROVIDER='deterministic',
            REDIS_URL=f'unix://{directory}/disabled.sock', CELERY_BROKER_URL='memory://',
            CELERY_RESULT_BACKEND='cache+memory://', SESSION_COOKIE_SECURE='false',
            SESSION_COOKIE_NAME='aic_topic_verification', FRONTEND_URL='http://127.0.0.1:13053',
            CORS_ORIGINS='http://127.0.0.1:13053', ALLOWED_HOSTS='127.0.0.1,localhost')
        from datetime import datetime, timezone
        from threading import Event, Thread
        from uuid import uuid4
        import app.models  # noqa: F401
        from app.database import Base, engine, SessionLocal
        from app.models.case import Case
        from app.models.case_pipeline import CaseAnalysisProfile
        from app.models.map_foundation import OperationalArea, UserAreaScope
        from app.services.auth_service import AuthService
        from app.services.case_pipeline_service import CasePipelineService
        from app.services.analysis_topic_service import process_next_topic
        from app.services import analysis_topic_service as topics
        from app.services.offline_map_service import OfflineMapService
        from tests.test_offline_maps import _bundle_bytes
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            db.add_all([OperationalArea(id=1, code='topic-1', name='合成专题一区', is_default=True,
                boundary={'type': 'Polygon', 'coordinates': [[[124.5, 46.2], [125.5, 46.2],
                    [125.5, 46.8], [124.5, 46.8], [124.5, 46.2]]]}),
                        OperationalArea(id=2, code='topic-2', name='不可访问合成区')])
            db.flush()
            user = AuthService.create_user(db, username='topic-check', display_name='专题隔离验证',
                                          password='Disposable-Topics-0921!', role='analyst')
            db.flush()
            db.query(UserAreaScope).filter_by(user_id=user.id, operational_area_id=1).update({'access_level': 'read'})
            for index, (area, description) in enumerate([(1, '井场发现软管。'), (1, '未发现软管。'),
                    (1, '资料尚待补充。'), (2, '隐藏区井场发现软管。')], 1):
                case = Case(case_number=f'SYNTHETIC-TOPIC-{index}', operational_area_id=area,
                    description=description, location='合成地点', case_type='盗油', status='pending',
                    occurred_time=datetime(2026, 9, 10, tzinfo=timezone.utc),
                    latitude=46.5 if index == 1 else None, longitude=125.1 if index == 1 else None)
                db.add(case)
                db.flush()
                payload = CasePipelineService.build_profile_payload(db, case)
                db.add(CaseAnalysisProfile(id=str(uuid4()), case_id=case.id, profile_version=1,
                    source_hash=payload['source_hash'], schema_version=payload['schema_version'],
                    dictionary_version=payload['dictionary_version'], payload=payload,
                    quality_score=50, analysis_readiness='partial', is_current=True))
            db.commit()
            bundle, _ = OfflineMapService.import_bundle(db, filename='synthetic-map.zip',
                content=_bundle_bytes(Path(directory), bundle_id='synthetic-topic-map',
                    attribution='合成离线地图验证，不代表两市真实覆盖'), imported_by=user.id)
            snapshot, _ = OfflineMapService.build_snapshot(db, operational_area_id=1,
                public_bundle_id=bundle.id, built_by=user.id)
            OfflineMapService.publish_snapshot(db, snapshot.id)
            db.commit()
            db.info['principal_user_id'] = user.id
            historic = topics.create_topic(db, '跨版本合成专题', {})
            topics.refresh_topic(db, historic['id'])
            # Seed a second frozen version via the same services; preserve v1.
            case = Case(case_number='SYNTHETIC-LATER', operational_area_id=1,
                description='井场发现油桶。', location='合成地点', case_type='盗油',
                occurred_time=datetime(2026, 9, 11, tzinfo=timezone.utc), latitude=46.51, longitude=125.11)
            db.add(case)
            db.flush()
            payload = CasePipelineService.build_profile_payload(db, case)
            db.add(CaseAnalysisProfile(id=str(uuid4()), case_id=case.id, profile_version=1,
                source_hash=payload['source_hash'], schema_version=payload['schema_version'],
                dictionary_version=payload['dictionary_version'], payload=payload,
                quality_score=50, analysis_readiness='partial', is_current=True))
            db.commit()
            topics.request_refresh(db, historic['id'])
            topics.refresh_topic(db, historic['id'])
            # Deterministic planning fixture only, not real-model acceptance.
            import asyncio
            from app.services import intelligent_query_tasks as queries
            from tests.test_query_followup import model_for, call, FINISH
            query = queries.create_query(db, '合成查询：统计原文否定软管的案件')
            asyncio.run(queries.execute_query(db, query['id'], model=model_for(call('aggregate_case_profiles', {
                'conditions': [{'category': 'tool', 'value': '软管', 'kind': 'negated'}]}), FINISH)))
            print(f"SYNTHETIC topic={historic['id']} query={query['id']} map={snapshot.id}", flush=True)
        stop = Event()
        def worker():
            while not stop.wait(1):
                with SessionLocal() as db:
                    process_next_topic(db)
        thread = Thread(target=worker, daemon=True)
        thread.start()
        import uvicorn
        from app.main import app
        try:
            uvicorn.run(app, host='127.0.0.1', port=18073, access_log=False)
        finally:
            stop.set()
            thread.join(timeout=5)
            engine.dispose()


if __name__ == '__main__':
    main()
