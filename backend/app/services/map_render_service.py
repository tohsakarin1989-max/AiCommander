"""Serve checked public render resources from an authorized immutable snapshot.

Runtime checks cover registration, bytes and URL closure. Semantic source-layer,
glyph, sprite layout and geographic validation remain import-worker duties.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

from sqlalchemy.orm import Session

from app.config import settings
from app.models.map_foundation import MapPackageArtifact, PublicMapBundle
from app.services.map_bundle_inventory import _open_file, _storage_key, registered_manifest
from app.services.map_style_dependencies import _load, bind_style_snapshot
from app.services.offline_map_service import OfflineMapService


def _context(db: Session, snapshot_ref: str, area_id: int | None):
    snapshot = OfflineMapService.resolve_snapshot(db, snapshot_ref, area_id=area_id)
    bundle = db.query(PublicMapBundle).filter(PublicMapBundle.id == snapshot.public_bundle_id).first()
    if bundle is None:
        raise ValueError('map_render_unavailable')
    if isinstance(bundle.manifest, dict) and bundle.manifest.get('schema_version') == '1.0':
        raise ValueError('map_render_not_configured')
    try:
        manifest = registered_manifest(bundle)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError('map_render_unavailable') from exc
    return snapshot, bundle, manifest


def _read(db: Session, bundle: PublicMapBundle, manifest: dict, role: str,
          *, name: str | None = None, limit: int = 1024 * 1024) -> bytes:
    """Read once via directory descriptors; hash the very bytes returned to clients."""
    root_fd = None
    try:
        assets = [a for a in manifest['assets'] if a['role'] == role and (name is None or a['name'] == name)]
        if len(assets) != 1 or not 0 < assets[0]['size_bytes'] <= limit:
            raise ValueError('invalid_render_asset')
        asset = assets[0]
        key = _storage_key(bundle.package_hash, asset)
        record = db.query(MapPackageArtifact).filter(
            MapPackageArtifact.public_bundle_id == bundle.id,
            MapPackageArtifact.snapshot_id.is_(None),
            MapPackageArtifact.storage_key == key,
            MapPackageArtifact.artifact_kind == role,
        ).first()
        if record is None or record.sha256 != asset['sha256'] or record.size_bytes != asset['size_bytes']:
            raise ValueError('unregistered_render_asset')
        root_fd = os.open(Path(settings.MAP_PACKAGE_ROOT), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = _open_file(root_fd, key)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != asset['size_bytes']:
                raise ValueError('invalid_render_file')
            content = source.read(asset['size_bytes'] + 1)
        if len(content) != asset['size_bytes'] or hashlib.sha256(content).hexdigest() != asset['sha256']:
            raise ValueError('corrupt_render_file')
        return content
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError('map_render_unavailable') from exc
    finally:
        if root_fd is not None:
            os.close(root_fd)


def read_style(db: Session, snapshot_ref: str, *, area_id: int | None = None) -> dict:
    snapshot, bundle, manifest = _context(db, snapshot_ref, area_id)
    try:
        content = _read(db, bundle, manifest, 'style')
        style = _load(content)
        # The accepted style already passed source-layer validation in the importer.
        # These names only allow repeating the runtime URL/font closure check; they
        # are not proof that a matching feature exists in a vector tile.
        layers = style.get('layers', [])
        source_layers = {item['source-layer'] for item in layers if isinstance(item, dict)
                         and isinstance(item.get('source-layer'), str)}
        sprites = set()
        if 'sprite' in style:
            sprites = set(_load(_read(db, bundle, manifest, 'sprite', name='sprite.json')))
        return bind_style_snapshot(content, manifest, snapshot.id,
                                   source_layers=source_layers, sprite_names=sprites)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError('map_render_unavailable') from exc


def read_sprite(db: Session, snapshot_ref: str, suffix: str,
                *, area_id: int | None = None) -> tuple[bytes, str]:
    _, bundle, manifest = _context(db, snapshot_ref, area_id)
    names = {'.json': 'sprite.json', '.png': 'sprite.png',
             '@2x.json': 'sprite-2x.json', '@2x.png': 'sprite-2x.png'}
    if suffix not in names:
        raise ValueError('map_render_not_configured')
    content = _read(db, bundle, manifest, 'sprite', name=names[suffix], limit=16 * 1024 * 1024)
    if suffix.endswith('.json'):
        try:
            _load(content)
        except (ValueError, TypeError, RecursionError) as exc:
            raise ValueError('map_render_unavailable') from exc
        return content, 'application/json'
    if not content.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('map_render_unavailable')
    return content, 'image/png'
