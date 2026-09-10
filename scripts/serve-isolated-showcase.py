#!/usr/bin/env python3
"""Start the full authenticated API with disposable synthetic-only storage."""
import os
from pathlib import Path
import sys
import tempfile


def main():
    if os.environ.get('AIC_DISPOSABLE_SHOWCASE') != '1':
        raise RuntimeError('explicit_disposable_test_required')
    semantic_fixture = os.environ.get('AIC_SEMANTIC_FIXTURE') == '1'
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
    with tempfile.TemporaryDirectory(prefix='aic-showcase-http-') as directory:
        os.chdir(directory)
        retained = {key: os.environ[key] for key in ('PATH', 'LANG', 'TMPDIR', 'FONTCONFIG_FILE') if key in os.environ}
        os.environ.clear()
        os.environ.update(retained)
        os.environ.update(DATABASE_URL=f'sqlite:///{directory}/test.sqlite',
            MAP_PACKAGE_ROOT=f'{directory}/maps', SECRET_KEY='isolated-showcase-test-only',
            ENVIRONMENT='development', AUTH_REQUIRED='true', AUTO_CREATE_TABLES='false',
            ENABLE_SHOWCASE='true', ENABLE_VECTOR_DB='false',
            REDIS_URL=f'unix://{directory}/disabled.sock', CELERY_BROKER_URL='memory://',
            CELERY_RESULT_BACKEND='cache+memory://', ENABLE_AGENT_LAB='false', AGENT_MODE='off',
            SESSION_COOKIE_NAME='aic_isolated_showcase', SESSION_COOKIE_SECURE='false',
            FRONTEND_URL='http://127.0.0.1:13043', CORS_ORIGINS='http://127.0.0.1:13043',
            ALLOWED_HOSTS='127.0.0.1,localhost')
        import app.models  # noqa: F401
        from app.database import Base, engine, SessionLocal
        from app.services.auth_service import AuthService
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            AuthService.create_user(db, username='showcase-check', display_name='隔离展示验证',
                password='Disposable-showcase-0910!', role='admin')
            db.commit()
            if semantic_fixture:
                from datetime import datetime, timezone
                from app.services.case_service import CaseService
                from app.services.case_pipeline_service import CasePipelineService
                from app.models.case_pipeline import CaseAnalysisProfile
                case = CaseService.create_case(
                    db=db, case_number='SYNTHETIC-SEMANTIC-001',
                    occurred_time=datetime(2026, 9, 10, 14, tzinfo=timezone.utc),
                    location='合成测试区域，无真实坐标', case_type='涉油测试',
                    description='未发现罐车，但是发现货车。夜里查获胶管。2026年9月10日22时至2026年9月11日2时。',
                    vehicle_info=[{'type': '货车', '套牌': False}],
                    involved_items={'名称': '胶管', '数量': 2},
                    upstream_source='合成区域测试井', downstream_destination='可能去往合成测试区域',
                )
                CasePipelineService.process_pending(db)
                profile = db.query(CaseAnalysisProfile).filter(CaseAnalysisProfile.case_id == case.id).one()
                assert profile.payload['semantics']['time_intervals']
                assert profile.payload['semantics']['structured_sources']['entries']
        import uvicorn
        from app.main import app
        try:
            uvicorn.run(app, host='127.0.0.1', port=18050)
        finally:
            engine.dispose()


if __name__ == '__main__':
    main()
