"""Bounded runtime transport for accepted vector MBTiles, without GIS dependencies."""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
from threading import Lock
import time
import zlib

from app.config import settings
from app.models.map_foundation import MapPackageArtifact
from app.services.map_bundle_inventory import _open_file, _storage_key, registered_manifest


MAX_COMPRESSED = 2 * 1024 * 1024
MAX_DECODED = 8 * 1024 * 1024


@dataclass
class _VerifiedCopy:
    directory: tempfile.TemporaryDirectory
    path: Path
    stamp: tuple[int, ...]


_verified: OrderedDict[tuple, _VerifiedCopy] = OrderedDict()
_verification_lock = Lock()


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _verified_copy(fd: int, expected: str, size: int) -> _VerifiedCopy:
    """Use private checked copies: SQLite VFS may resolve /dev/fd back to a path.

    At most two copies are cached per worker. Local references keep evicted copies
    alive until their queries close. Authorization and source identity are checked
    before cache access; no permissions or tile responses are cached.
    """
    info = os.fstat(fd)
    stamp = _stamp(info)
    if not stat.S_ISREG(info.st_mode) or info.st_size != size:
        raise ValueError('invalid_vector_store')
    key = (stamp, expected)
    with _verification_lock:
        if key in _verified:
            cached = _verified[key]
            try:
                cache_valid = _stamp(cached.path.stat(follow_symlinks=False)) == cached.stamp
            except FileNotFoundError:
                cache_valid = False
            if cache_valid:
                _verified.move_to_end(key)
                return cached
            del _verified[key]
        # Serialize cache fills so concurrent first tiles do not copy the same
        # large database repeatedly. Other queries run outside this lock.
        directory = tempfile.TemporaryDirectory(prefix='aic-vector-read-')
        target = Path(directory.name) / 'map.sqlite'
        try:
            digest = hashlib.sha256()
            remaining = size
            with target.open('xb') as destination:
                while remaining:
                    data = os.read(fd, min(1024 * 1024, remaining))
                    if not data:
                        raise ValueError('truncated_vector_store')
                    destination.write(data)
                    digest.update(data)
                    remaining -= len(data)
            if os.read(fd, 1) or digest.hexdigest() != expected or _stamp(os.fstat(fd)) != stamp:
                raise ValueError('corrupt_vector_store')
            target.chmod(0o400)
            result = _VerifiedCopy(directory, target, _stamp(target.stat()))
            _verified[key] = result
            while len(_verified) > 2:
                _verified.popitem(last=False)
            return result
        except BaseException:
            directory.cleanup()
            raise


def read_vector_tile(db, bundle, z: int, x: int, y: int) -> tuple[bytes, str]:
    """Caller must first resolve an authorized snapshot; no unscoped public endpoint."""
    root_fd = fd = None
    connection = None
    try:
        manifest = registered_manifest(bundle)
        if not manifest['min_zoom'] <= z <= manifest['max_zoom']:
            raise ValueError('vector_tile_not_found')
        assets = [a for a in manifest['assets'] if a['role'] == 'vector']
        if len(assets) != 1:
            raise ValueError('ambiguous_vector_store')
        asset = assets[0]
        key = _storage_key(bundle.package_hash, asset)
        record = db.query(MapPackageArtifact).filter(
            MapPackageArtifact.public_bundle_id == bundle.id,
            MapPackageArtifact.snapshot_id.is_(None),
            MapPackageArtifact.storage_key == key,
            MapPackageArtifact.artifact_kind == 'mbtiles',
        ).first()
        if record is None or record.sha256 != asset['sha256'] or record.size_bytes != asset['size_bytes']:
            raise ValueError('unregistered_vector_store')
        root_fd = os.open(Path(settings.MAP_PACKAGE_ROOT), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = _open_file(root_fd, key)
        verified = _verified_copy(fd, asset['sha256'], asset['size_bytes'])
        connection = sqlite3.connect(f'{verified.path.as_uri()}?mode=ro&immutable=1', uri=True)
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA trusted_schema=OFF')
        deadline = time.monotonic() + 2
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        rows = connection.execute(
            "SELECT CASE WHEN typeof(tile_data)='blob' AND length(tile_data)<=? THEN tile_data END "
            'FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=? LIMIT 2',
            (MAX_COMPRESSED, z, x, (1 << z) - 1 - y),
        ).fetchall()
        if _stamp(verified.path.stat(follow_symlinks=False)) != verified.stamp:
            raise ValueError('vector_store_changed')
        if not rows:
            raise ValueError('vector_tile_not_found')
        if len(rows) != 1 or not rows[0][0]:
            raise ValueError('invalid_vector_tile')
        tile = bytes(rows[0][0])
        if tile.startswith(b'\x1f\x8b'):
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            tile = decoder.decompress(tile, MAX_DECODED + 1)
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError('invalid_vector_compression')
        if len(tile) > MAX_DECODED:
            raise ValueError('vector_tile_too_large')
        return tile, 'application/vnd.mapbox-vector-tile'
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError, zlib.error) as exc:
        if str(exc) == 'vector_tile_not_found':
            raise
        raise ValueError('tile_store_unavailable') from exc
    finally:
        if connection is not None:
            connection.close()
        if fd is not None:
            os.close(fd)
        if root_fd is not None:
            os.close(root_fd)
