"""Isolated container smoke: real public upload -> durable queue -> validation.

Only use in a disposable container with a new database and map volume. No
production credentials. This does not exercise the Redis/Celery transport.
"""
import json
import os
from pathlib import Path
import time
import tempfile

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.config import settings
import app.models  # noqa: F401
from app.models.map_package_import import MapPackageImport
from app.services.map_package_import_service import create_import, put_chunk, submit_import
from app.services.map_package_import_worker import process_next
from app.services.map_package_set import read_manifest


def main():
    if os.getuid() != 10001 or os.environ.get('AIC_DISPOSABLE_MAP_SMOKE') != '1':
        raise RuntimeError('expected_unprivileged_worker')
    if settings.ENVIRONMENT == 'production':
        raise RuntimeError('disposable_development_environment_required')
    with tempfile.TemporaryDirectory(prefix='runtime-smoke-', dir='/var/lib/aicommander/maps') as store:
        settings.MAP_PACKAGE_ROOT = store
        run()


def run():
    # Never use configured business engine, even if this script is misplaced.
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    directory = Path('/tmp/public-package')
    manifest = read_manifest(directory)
    started = time.monotonic()
    with Session(engine) as db:
        row = create_import(db, json.dumps(manifest).encode(), user_id=None)
        run_id = row.id
        for asset in manifest['assets']:
            for chunk in asset['chunks']:
                put_chunk(db, run_id, chunk['file'], (directory / chunk['file']).read_bytes())
        assert submit_import(db, run_id)['status'] == 'queued'
        result = process_next(db)
        assert result['status'] == 'render_validated', result
        report = db.get(MapPackageImport, run_id).report
        assert report['installation']['status'] == 'installed_integrity_verified'
        assert report['style_syntax_verified'] is True
        assert report['label_codepoint_coverage_verified'] is True
        assert process_next(db) is None
        print(json.dumps({'status': 'runtime_smoke_passed', 'uid': os.getuid(),
            'bundle_id': manifest['bundle_id'], 'assets': len(manifest['assets']),
            'tiles': report['vector']['tile_count'], 'publish_ready': False,
            'celery_transport_verified': False,
            'seconds': round(time.monotonic() - started, 2)}))
    engine.dispose()


if __name__ == '__main__':
    main()
