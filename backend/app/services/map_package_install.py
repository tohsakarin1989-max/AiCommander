"""Atomically install immutable assets; never grant acceptance or publish a map.

Worker-owned directories only. A separate content acceptance step must register
the returned inventory in the database. The core API never calls this copier.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from uuid import uuid4

from app.services.map_asset_layout import storage_key
from app.services.map_package_set import MAX_MANIFEST_BYTES, _open_file, read_manifest


def _check(source_fd, expected, output_fd=None):
    with os.fdopen(source_fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != expected['size_bytes']:
            raise ValueError('installed_asset_size_mismatch')
        remaining, digest = expected['size_bytes'], hashlib.sha256()
        while remaining:
            content = source.read(min(1024 * 1024, remaining))
            if not content:
                raise ValueError('installed_asset_truncated')
            digest.update(content)
            remaining -= len(content)
            if output_fd is not None:
                view = memoryview(content)
                while view:
                    written = os.write(output_fd, view)
                    if written <= 0:
                        raise OSError('asset_write_failed')
                    view = view[written:]
        if source.read(1) or digest.hexdigest() != expected['sha256']:
            raise ValueError('installed_asset_checksum_mismatch')


def _directory(parent, name):
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent)
        os.fsync(parent)
    except FileExistsError:
        pass
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)


def _output(root, relative):
    parts = relative.split('/')
    parent = os.dup(root)
    try:
        for part in parts[:-1]:
            child = _directory(parent, part)
            os.close(parent)
            parent = child
        fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o400, dir_fd=parent)
        try:
            os.fsync(parent)
        except OSError:
            os.close(fd)
            raise
        return fd
    finally:
        os.close(parent)


def install_assets(assembly: Path, storage_root: Path) -> dict:
    manifest = read_manifest(assembly)
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    records = [{**{key: asset[key] for key in ('name', 'role', 'size_bytes', 'sha256')},
                'storage_key': storage_key(digest, asset, manifest)} for asset in manifest['assets']]
    relative = [item['storage_key'].removeprefix(f'bundles/{digest}/') for item in records]
    source = os.open(assembly, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root = bundles = lock = staging = None
    staging_name = None
    reused = False
    try:
        root = os.open(storage_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        bundles = _directory(root, 'bundles')
        # Persistent inode: never unlink this lock, avoiding split locks between
        # concurrent workers. A crashed worker's OS lock releases automatically.
        lock = os.open(f'.install-{digest}.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                       0o600, dir_fd=bundles)
        if not stat.S_ISREG(os.fstat(lock).st_mode):
            raise ValueError('invalid_install_lock')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('map_installation_busy') from None
        try:
            existing = os.open(digest, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=bundles)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            try:
                with os.fdopen(_open_file(existing, 'manifest.json'), 'rb') as content:
                    info = os.fstat(content.fileno())
                    if (not stat.S_ISREG(info.st_mode) or info.st_size != len(canonical)
                            or content.read(MAX_MANIFEST_BYTES + 1) != canonical):
                        raise ValueError('installed_manifest_mismatch')
                for name, record in zip(relative, records):
                    _check(_open_file(existing, name), record)
            finally:
                os.close(existing)
            reused = True
        else:
            staging_name = f'.install-{uuid4().hex}'
            os.mkdir(staging_name, mode=0o700, dir_fd=bundles)
            staging = os.open(staging_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=bundles)
            for index, (name, record) in enumerate(zip(relative, records)):
                output = _output(staging, name)
                try:
                    _check(_open_file(source, f'asset-{index:04d}.bin'), record, output)
                    os.fsync(output)
                finally:
                    os.close(output)
            output = _output(staging, 'manifest.json')
            with os.fdopen(output, 'wb') as target:
                target.write(canonical)
                target.flush()
                os.fsync(target.fileno())
            os.fsync(staging)
            os.rename(staging_name, digest, src_dir_fd=bundles, dst_dir_fd=bundles)
            staging_name = None
            os.fsync(bundles)
        return {'status': 'installed_integrity_verified', 'publish_ready': False,
                'package_hash': digest, 'manifest': manifest, 'assets': records, 'reused': reused}
    finally:
        if staging is not None:
            os.close(staging)
        try:
            if staging_name is not None:
                shutil.rmtree(staging_name, dir_fd=bundles)
        finally:
            for fd in (lock, bundles, root, source):
                if fd is not None:
                    os.close(fd)
