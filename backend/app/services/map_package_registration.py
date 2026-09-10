"""Register validated display assets, never enable routing or switch current.

The worker report is server-owned. Registration is display acceptance only;
road topology and regional coverage remain explicit release gates.
"""
from pathlib import Path

from app.config import settings
from app.models.map_foundation import MapPackageArtifact, PublicMapBundle
from app.services.map_asset_layout import storage_key
from app.services.map_bundle_inventory import verify_bundle_inventory
from app.services.map_package_import_service import _manifest, _row


def register_display_bundle(db, run_id: str, *, user_id: int | None) -> dict:
    """Own transaction; serialize retries and derive paths from frozen manifest."""
    try:
        row = _row(db, run_id, lock=True)
        manifest = _manifest(row)
        report = row.report or {}
        installation = report.get('installation') or {}
        if (row.status != 'render_validated'
                or report.get('status') != 'render_content_validated'
                or report.get('bundle_id') != manifest['bundle_id']
                or any(report.get(key) is not True for key in (
                    'style_syntax_verified', 'label_codepoint_coverage_verified',
                    'primary_place_font_coverage_verified'))
                or installation.get('status') != 'installed_integrity_verified'
                or installation.get('package_hash') != row.manifest_hash):
            raise ValueError('map_import_not_validated')
        bundle = db.query(PublicMapBundle).filter_by(bundle_id=manifest['bundle_id']).first()
        reused = bundle is not None
        if bundle is not None and bundle.package_hash != row.manifest_hash:
            raise ValueError('bundle_id_exists')
        if bundle is None:
            bundle = PublicMapBundle(
                bundle_id=manifest['bundle_id'], provider=manifest['provider'],
                source_version=manifest['source_version'], license_record=manifest['license'],
                bounds=manifest['bounds'], manifest=manifest, package_hash=row.manifest_hash,
                status='accepted', imported_by=user_id)
            db.add(bundle)
            db.flush()
            for asset in manifest['assets']:
                db.add(MapPackageArtifact(public_bundle_id=bundle.id,
                    artifact_kind='mbtiles' if asset['role'] == 'vector' else asset['role'],
                    storage_key=storage_key(row.manifest_hash, asset, manifest),
                    sha256=asset['sha256'], size_bytes=asset['size_bytes']))
            db.flush()
        if not verify_bundle_inventory(db, bundle, Path(settings.MAP_PACKAGE_ROOT), verify_hash=True):
            raise ValueError('bundle_artifact_missing')
        result = {'public_bundle_id': bundle.id, 'acceptance_scope': 'offline_display',
                  'routing_available': False, 'current_changed': False, 'reused': reused}
        row.report = {**report, 'registration': result}
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
