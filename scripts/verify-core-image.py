#!/usr/bin/env python3
"""Read-only-root, network-none Docker probe with temporary synthetic DB only.

Run via stdin using the actual backend Dockerfile image. No host data mounts.
"""
import json
import os
from pathlib import Path
import tempfile


def main():
    assert Path('/app/alembic.ini').is_file() and os.getuid() == 10001
    root = Path('/app')
    forbidden = [p for p in root.rglob('*') if p.is_file() and (
        p.suffix in {'.db', '.sqlite', '.sqlite3', '.mbtiles'}
        or p.name in {'.env', '.env.production', '.env.local'})]
    assert not forbidden, 'runtime_data_or_configuration_in_image'
    assert not any(p.is_file() for p in (root / 'data').rglob('*'))
    assert not any(p.is_file() for p in Path('/var/lib/aicommander/maps').rglob('*'))
    with tempfile.TemporaryDirectory(prefix='core-image-probe-') as tmp:
        os.environ.clear()
        os.environ.update({
            'DATABASE_URL': f'sqlite:///{tmp}/synthetic.sqlite',
            'SECRET_KEY': 'isolated-core-image-test-only', 'ENABLE_VECTOR_DB': 'false',
            'ENABLE_AGENT_LAB': 'false', 'AGENT_MODE': 'off', 'AUTH_REQUIRED': 'true',
            'AUTO_CREATE_TABLES': 'false', 'SESSION_COOKIE_SECURE': 'false',
            'ALLOWED_HOSTS': 'testserver', 'FRONTEND_URL': 'http://testserver',
            'CORS_ORIGINS': 'http://testserver', 'REDIS_URL': 'unix:///tmp/nonexistent-probe.sock',
            'CELERY_BROKER_URL': 'memory://', 'CELERY_RESULT_BACKEND': 'cache+memory://',
            'MAP_PACKAGE_ROOT': f'{tmp}/maps',
        })
        from alembic import command
        from alembic.config import Config
        command.upgrade(Config('/app/alembic.ini'), 'head')
        from sqlalchemy import text
        from app.database import SessionLocal, engine
        from app.models.user import User
        from app.models.map_foundation import OperationalArea
        from app.services.auth_service import AuthService
        from app.main import app
        from fastapi.testclient import TestClient
        with SessionLocal() as db:
            revision = db.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
            assert revision == 'f830b2152595'
            area_id = db.query(OperationalArea.id).order_by(OperationalArea.id).first()[0]
            db.add(User(username='core-image-probe', display_name='合成管理员', role='admin',
                        password_hash=AuthService.hash_password('Synthetic-core-123!')))
            db.commit()
        headers = {'Origin': 'http://testserver'}
        with TestClient(app) as client:
            assert client.get('/health/live').status_code == 200
            assert client.get('/api/cases/').status_code == 401
            assert client.post('/api/auth/login', json={'username': 'core-image-probe',
                'password': 'Synthetic-core-123!'}, headers=headers).status_code == 200
            response = client.post('/api/cases/', headers=headers, json={
                'case_number': 'SYNTHETIC-CORE-001', 'occurred_time': '2026-09-10T01:00:00',
                'description': '合成镜像验收原文', 'operational_area_id': area_id,
                'location': '合成位置', 'case_type': '涉油盗窃',
            })
            assert response.status_code == 200, response.text
            case_id = response.json()['id']
            assert client.get(f'/api/cases/{case_id}').status_code == 200
        engine.dispose()
    print(json.dumps({'status': 'passed', 'uid': os.getuid(), 'migration': revision,
                      'image_runtime_data_absent': True, 'authenticated_case_write_read': True,
                      'model_required': False, 'postgresql_tested': False}), flush=True)


if __name__ == '__main__':
    main()
