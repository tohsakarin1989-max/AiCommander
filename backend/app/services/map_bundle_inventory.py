"""Bind registered schema-2 assets to a single immutable manifest identity.

Inventory verification does not establish content acceptance. Registration
requires the server-owned worker report; display acceptance does not grant routing.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from sqlalchemy.orm import Session

from app.models.map_foundation import MapPackageArtifact, PublicMapBundle
from app.services.map_package_set import _open_file, parse_manifest
from app.services.map_asset_layout import storage_key as _storage_key


def registered_manifest(bundle: PublicMapBundle) -> dict:
    """Validate schema and database identity before using any registered asset."""
    manifest = parse_manifest(json.dumps(bundle.manifest, ensure_ascii=False).encode())
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                           separators=(',', ':')).encode()
    if (bundle.status != 'accepted'
            or hashlib.sha256(canonical).hexdigest() != bundle.package_hash
            or bundle.bundle_id != manifest['bundle_id']
            or bundle.source_version != manifest['source_version']
            or bundle.provider != manifest['provider']
            or bundle.license_record != manifest['license']
            or bundle.bounds != manifest['bounds']):
        raise ValueError('invalid_registered_manifest')
    return manifest


def verify_bundle_inventory(db: Session, bundle: PublicMapBundle, root: Path,
                            *, verify_hash: bool) -> bool:
    """Check every manifest asset, not just the first MBTiles registration.

With verify_hash=False this is only a registration/type/size probe. Publishing
and rollback must use True. The root is server-owned, never a request path.
"""
    root_fd = None
    try:
        manifest = registered_manifest(bundle)
        expected = {_storage_key(bundle.package_hash, asset, manifest): asset for asset in manifest['assets']}
        artifacts = db.query(MapPackageArtifact).filter(
            MapPackageArtifact.public_bundle_id == bundle.id,
            MapPackageArtifact.snapshot_id.is_(None),
        ).limit(len(expected) + 1).all()
        if len(artifacts) != len(expected) or {a.storage_key for a in artifacts} != set(expected):
            return False
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for artifact in artifacts:
            asset = expected[artifact.storage_key]
            kind = 'mbtiles' if asset['role'] == 'vector' else asset['role']
            if (artifact.artifact_kind != kind or artifact.sha256 != asset['sha256']
                    or artifact.size_bytes != asset['size_bytes']):
                return False
            fd = _open_file(root_fd, artifact.storage_key)
            with os.fdopen(fd, 'rb') as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size != asset['size_bytes']:
                    return False
                if verify_hash:
                    digest = hashlib.sha256()
                    remaining = asset['size_bytes']
                    while remaining:
                        content = source.read(min(1024 * 1024, remaining))
                        if not content:
                            return False
                        remaining -= len(content)
                        digest.update(content)
                    if source.read(1) or digest.hexdigest() != asset['sha256']:
                        return False
        return True
    except (OSError, ValueError, TypeError, RecursionError):
        return False
    finally:
        if root_fd is not None:
            os.close(root_fd)
