"""Opt-in background display publication using existing snapshot services."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, or_, update
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.models.map_package_import import MapPackageImport
from app.models.map_foundation import UserAreaScope
from app.models.user import User
from app.services.map_package_registration import register_display_bundle
from app.services.offline_map_service import OfflineMapService


def publish_next(db):
    if not settings.MAP_AUTO_PUBLISH_AREA_IDS:
        return None
    areas = [int(value) for value in settings.MAP_AUTO_PUBLISH_AREA_IDS.split(',')]
    now = datetime.now(timezone.utc)
    eligible = and_(MapPackageImport.status == 'render_validated',
        MapPackageImport.report['auto_publication'].as_string().is_(None),
        or_(MapPackageImport.lease_token.is_(None), MapPackageImport.lease_expires_at < now))
    candidate = db.query(MapPackageImport.id).filter(eligible).order_by(
        MapPackageImport.created_at, MapPackageImport.id).first()
    if candidate is None:
        return None
    run_id, token = candidate[0], str(uuid4())
    claimed = db.execute(update(MapPackageImport).execution_options(synchronize_session=False)
        .where(MapPackageImport.id == run_id, eligible)
        .values(lease_token=token, lease_expires_at=now + timedelta(minutes=35)))
    db.commit()
    if claimed.rowcount != 1:
        return None
    results = []
    for area_id in areas:
        try:
            if db.query(MapPackageImport.id).filter(MapPackageImport.id == run_id,
                    MapPackageImport.lease_token == token,
                    MapPackageImport.lease_expires_at > datetime.now(timezone.utc)).first() is None:
                raise ValueError('map_publication_lease_lost')
            row = db.get(MapPackageImport, run_id)
            user = db.get(User, row.created_by) if row.created_by else None
            scope = db.query(UserAreaScope).filter_by(user_id=row.created_by,
                operational_area_id=area_id, access_level='manage').first()
            if user is None or not user.is_active or user.role != 'admin' or scope is None:
                raise ValueError('map_publish_permission_revoked')
            registration = register_display_bundle(db, run_id, user_id=user.id)
            snapshot, _ = OfflineMapService.build_snapshot(db, operational_area_id=area_id,
                public_bundle_id=registration['public_bundle_id'], built_by=user.id)
            if snapshot.status != 'current':
                OfflineMapService.publish_snapshot(db, snapshot.id, automatic=True, authorized_user_id=user.id,
                                                  publication_lease=(run_id, token))
            results.append({'area_id': area_id, 'status': 'published', 'snapshot_id': snapshot.id})
        except (ValueError, OSError, SQLAlchemyError) as exc:
            db.rollback()
            known = {'map_publish_permission_revoked', 'map_source_not_newer', 'map_publication_lease_lost',
                     'map_conflicts_pending', 'map_bundle_outside_operational_area',
                     'map_coverage_unverifiable', 'bundle_artifact_missing',
                     'map_import_not_validated', 'operational_area_not_found'}
            code = str(exc) if isinstance(exc, ValueError) and str(exc) in known else 'map_publication_failed'
            results.append({'area_id': area_id, 'status': 'attention_required', 'code': code})
            if code == 'map_publication_lease_lost':
                break
    db.expire_all()
    row = db.get(MapPackageImport, run_id)
    report = {**(row.report or {}), 'auto_publication': {'areas': results,
        'finished_at': datetime.now(timezone.utc).isoformat()}}
    finished = db.execute(update(MapPackageImport).execution_options(synchronize_session=False)
        .where(MapPackageImport.id == run_id,
        MapPackageImport.lease_token == token,
        MapPackageImport.lease_expires_at > datetime.now(timezone.utc))
        .values(report=report, lease_token=None, lease_expires_at=None))
    db.commit()
    return {'id': run_id, 'areas': results, 'recorded': finished.rowcount == 1}
