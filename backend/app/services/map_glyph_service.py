"""Serve bounded, registered glyph bytes after checking snapshot scope."""
import hashlib
import os
import re
import stat

from sqlalchemy.orm import Session

from app.models.map_foundation import MapPackageArtifact, PublicMapBundle
from app.services.offline_map_service import OfflineMapService
from app.services.map_glyph_validation import inspect_glyph_range, parse_glyph_range
from app.services.map_font_profiles import font_profile
from app.services.map_bundle_inventory import registered_manifest


MAX_GLYPH_BYTES = 2 * 1024 * 1024


def read_glyph(db: Session, snapshot_ref: str, fontstack: str, range_name: str,
               *, area_id: int | None = None) -> bytes:
    """Return the exact checked bytes; never reopen a verified file for serving."""
    snapshot = OfflineMapService.resolve_snapshot(db, snapshot_ref, area_id=area_id)
    try:
        parse_glyph_range(range_name)
    except ValueError as exc:
        raise ValueError('invalid_glyph_range') from exc
    bundle = db.query(PublicMapBundle).filter(
        PublicMapBundle.id == snapshot.public_bundle_id,
        PublicMapBundle.status == 'accepted',
    ).first()
    if bundle is None or not re.fullmatch(r'[0-9a-f]{64}', bundle.package_hash):
        raise ValueError('glyph_unavailable')
    try:
        vector = isinstance(bundle.manifest, dict) and bundle.manifest.get('schema_version') == '2.0'
        manifest = registered_manifest(bundle) if vector else {}
        profile = font_profile(manifest)
    except (ValueError, TypeError, RecursionError):
        raise ValueError('glyph_unavailable') from None
    if fontstack != profile.fontstack:
        raise ValueError('glyph_not_found')
    expected_asset = None
    if vector:
        expected_asset = next((asset for asset in manifest['assets']
            if asset['role'] == 'glyphs' and asset['name'] == f'glyphs-{range_name}.pbf'), None)
        if expected_asset is None:
            raise ValueError('glyph_not_found')
    key = (f'bundles/{bundle.package_hash}/glyphs/'
           f'{profile.storage_slug}/{range_name}.pbf')
    artifact = db.query(MapPackageArtifact).filter(
        MapPackageArtifact.public_bundle_id == bundle.id,
        MapPackageArtifact.snapshot_id.is_(None),
        MapPackageArtifact.artifact_kind == 'glyphs',
        MapPackageArtifact.storage_key == key,
    ).first()
    if artifact is None:
        raise ValueError('glyph_not_found')
    if expected_asset is not None and (
            artifact.size_bytes != expected_asset['size_bytes']
            or artifact.sha256 != expected_asset['sha256']):
        raise ValueError('glyph_unavailable')
    try:
        if not 0 < artifact.size_bytes <= MAX_GLYPH_BYTES:
            raise ValueError('invalid_size')
        path = OfflineMapService._storage_path(key)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != artifact.size_bytes:
                raise ValueError('invalid_file')
            content = source.read(artifact.size_bytes + 1)
        if (len(content) != artifact.size_bytes
                or hashlib.sha256(content).hexdigest() != artifact.sha256):
            raise ValueError('invalid_checksum')
        if vector:
            inspect_glyph_range(content, range_name, fontstack=profile.fontstack)
    except (OSError, ValueError) as exc:
        raise ValueError('glyph_unavailable') from exc
    return content
