"""Seed/read a disposable persistent database; never execute the worker directly."""
import json
import os
import sys
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.database import Base, SessionLocal, engine
import app.models  # noqa: F401
from app.models.map_package_import import MapPackageImport
from app.models.map_foundation import OperationalArea, MapSnapshot
from app.services.auth_service import AuthService
from app.services.map_package_import_service import create_import, put_chunk, submit_import
from app.services.map_package_set import read_manifest


def main():
    expected = 'sqlite:////var/lib/aicommander/maps/queue-smoke.sqlite'
    if (os.getuid() != 10001
            or os.environ.get('AIC_DISPOSABLE_MAP_SMOKE') != '1'
            or settings.ENVIRONMENT == 'production'
            or settings.DATABASE_URL != expected
            or settings.MAP_PACKAGE_ROOT != '/var/lib/aicommander/maps/queue-store'):
        raise RuntimeError('disposable_queue_environment_required')
    command = sys.argv[1]
    if command not in {'seed', 'status'}:
        raise ValueError('unsupported_command')
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if command == 'seed':
            directory = Path('/tmp/public-package')
            manifest = read_manifest(directory)
            area = db.query(OperationalArea).filter_by(code='queue-map-test').first()
            if area is None:
                w, s, e, n = manifest['bounds']
                area = OperationalArea(code='queue-map-test', name='隔离公开地图', is_default=True,
                    boundary={'type': 'Polygon', 'coordinates': [[[w,s],[e,s],[e,n],[w,n],[w,s]]]})
                db.add(area)
                db.commit()
                user = AuthService.create_user(db, username='queue-map-test', display_name='隔离测试',
                    password='Isolated-queue-map-test-123!', role='admin')
            else:
                from app.models.user import User
                user = db.query(User).filter_by(username='queue-map-test').one()
            row = create_import(db, json.dumps(manifest).encode(), user_id=user.id)
            for asset in manifest['assets']:
                for chunk in asset['chunks']:
                    put_chunk(db, row.id, chunk['file'],
                              (directory / chunk['file']).read_bytes())
            assert submit_import(db, row.id)['status'] == 'queued'
        rows = db.scalars(select(MapPackageImport)).all()
        print(json.dumps([{
            'id': row.id, 'status': row.status, 'error_code': row.error_code,
            'installation': (row.report or {}).get('installation', {}).get('status'),
            'tiles': (row.report or {}).get('vector', {}).get('tile_count'),
            'publication': (row.report or {}).get('auto_publication'),
            'current_snapshots': db.query(MapSnapshot).filter_by(status='current').count(),
        } for row in rows]))


if __name__ == '__main__':
    main()
