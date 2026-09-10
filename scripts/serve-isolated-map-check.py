#!/usr/bin/env python3
"""Disposable authenticated full API with public maps, for browser verification."""
import json
import argparse
import os
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true', help='验证自动发布后退出，不启动HTTP')
    args = parser.parse_args()
    if os.environ.get('AIC_DISPOSABLE_MAP_SMOKE') != '1':
        raise RuntimeError('explicit_disposable_test_required')
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository / 'backend'))
    source = repository / 'backups/map-foundation/v4-source/20260908/complete-candidate-v2/transport'
    with tempfile.TemporaryDirectory(prefix='aic-map-http-') as directory:
        # Do not load the operator's .env or inherit outbound credentials/broker.
        os.chdir(directory)
        retained = {key: os.environ[key] for key in ('PATH', 'LANG', 'TMPDIR', 'PYTHONPATH')
                    if key in os.environ}
        os.environ.clear()
        os.environ.update(retained)
        # Override before app imports; never use a caller's configured database.
        os.environ.update(DATABASE_URL=f'sqlite:///{directory}/test.sqlite',
            MAP_PACKAGE_ROOT=f'{directory}/maps', SECRET_KEY='isolated-map-http-test-only',
            ENVIRONMENT='development', AUTH_REQUIRED='true', AUTO_CREATE_TABLES='false',
            REDIS_URL=f'unix://{directory}/disabled-redis.sock',
            CELERY_BROKER_URL='memory://', CELERY_RESULT_BACKEND='cache+memory://',
            ENABLE_AGENT_LAB='false', AGENT_MODE='off', AGENT_MUTATIONS_ENABLED='false',
            SESSION_COOKIE_NAME='aic_isolated_map_check',
            SESSION_COOKIE_SECURE='false', FRONTEND_URL='http://127.0.0.1:13042',
            CORS_ORIGINS='http://127.0.0.1:13042', ALLOWED_HOSTS='127.0.0.1,localhost')
        from app.database import Base, engine, SessionLocal
        import app.models  # noqa: F401
        from app.models.map_foundation import OperationalArea, MapSnapshot
        from app.config import settings
        from app.services.auth_service import AuthService
        from app.services.map_package_set import read_manifest
        from app.services.map_package_import_service import create_import, put_chunk, submit_import
        from app.services.map_package_import_worker import process_next
        from app.services.map_auto_publication import publish_next

        Base.metadata.create_all(engine)
        manifest = read_manifest(source)
        with SessionLocal() as db:
            w, s, e, n = manifest['bounds']
            area = OperationalArea(code='public-test', name='隔离公共地图', is_default=True,
                boundary={'type': 'Polygon', 'coordinates': [[[w,s],[e,s],[e,n],[w,n],[w,s]]]})
            db.add(area)
            db.commit()
            user = AuthService.create_user(db, username='map-check', display_name='隔离验证',
                password='Disposable-map-check-0910!', role='admin')
            db.commit()
            run = create_import(db, json.dumps(manifest).encode(), user_id=user.id)
            for asset in manifest['assets']:
                for chunk in asset['chunks']:
                    put_chunk(db, run.id, chunk['file'], (source / chunk['file']).read_bytes())
            submit_import(db, run.id)
            assert process_next(db)['status'] == 'render_validated'
            settings.MAP_AUTO_PUBLISH_AREA_IDS = str(area.id)
            publication = publish_next(db)
            assert publication['recorded'] is True
            assert publication['areas'][0]['status'] == 'published', publication
            snapshot = db.get(MapSnapshot, publication['areas'][0]['snapshot_id'])
            assert snapshot.status == 'current'
            assert publish_next(db) is None
            print(json.dumps({'status': 'isolated_map_ready', 'area_id': area.id,
                              'snapshot_id': snapshot.id, 'automatic_publication': True}), flush=True)
        if args.check_only:
            engine.dispose()
            return
        import uvicorn
        from app.main import app
        try:
            uvicorn.run(app, host='127.0.0.1', port=18049)
        finally:
            engine.dispose()


if __name__ == '__main__':
    main()
