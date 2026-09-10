"""Recoverable map render-validation stage; no accepted bundle or current writes."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from uuid import uuid4

from sqlalchemy import and_, or_, update

from app.config import settings
from app.models.map_package_import import MapPackageImport
from app.services.map_package_import_service import _manifest, _row
from app.services.map_package_materialize import materialize_package
from app.services.map_package_install import install_assets


def _validate(directory):
    # GIS build dependencies are deliberately absent from the core API import path.
    from app.services.map_render_bundle_validation import validate_render_bundle
    return validate_render_bundle(directory)


def process_next(db):
    now = datetime.now(timezone.utc)
    eligible = or_(MapPackageImport.status == 'queued', and_(
        MapPackageImport.status == 'validating', MapPackageImport.lease_expires_at < now))
    candidate = db.query(MapPackageImport.id).filter(eligible).order_by(
        MapPackageImport.created_at, MapPackageImport.id).first()
    if candidate is None:
        return None
    run_id, token = candidate[0], str(uuid4())
    claimed = db.execute(update(MapPackageImport).where(MapPackageImport.id == run_id, eligible)
        .values(status='validating', lease_token=token,
                lease_expires_at=now + timedelta(minutes=35), updated_at=now))
    db.commit()
    if claimed.rowcount != 1:
        return None
    report, error = None, None
    try:
        row = _row(db, run_id)
        manifest = _manifest(row)
        db.rollback()  # Do not keep a core database transaction during decoding.
        source = Path(settings.MAP_PACKAGE_ROOT) / 'imports' / run_id / 'chunks'
        with tempfile.TemporaryDirectory(prefix='aic-map-import-') as staging:
            assembly = materialize_package(source, manifest, Path(staging))
            report = _validate(assembly)
            if report.get('status') != 'render_content_validated' or report.get('publish_ready') is not False:
                raise ValueError('invalid_render_validation_report')
            # Content-addressed storage is durable before the temporary assembly
            # disappears. This is not acceptance and never switches current.
            installation = install_assets(assembly, Path(settings.MAP_PACKAGE_ROOT))
            report = {**report, 'installation': {
                key: installation[key] for key in (
                    'status', 'publish_ready', 'package_hash', 'assets', 'reused')}}
        status = 'render_validated'
    except (OSError, ValueError, ImportError):
        report, error, status = None, 'map_content_validation_failed', 'failed'
    # An expired/reclaimed worker can never overwrite the new owner's result.
    finished = db.execute(update(MapPackageImport).where(MapPackageImport.id == run_id,
        MapPackageImport.status == 'validating', MapPackageImport.lease_token == token,
        MapPackageImport.lease_expires_at > datetime.now(timezone.utc))
        .values(status=status, report=report, error_code=error, lease_token=None,
                lease_expires_at=None, updated_at=datetime.now(timezone.utc)))
    db.commit()
    return {'id': run_id, 'status': status if finished.rowcount == 1 else 'lease_lost',
            'publish_ready': False}
