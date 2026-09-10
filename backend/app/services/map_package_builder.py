"""Deterministic public-package builder for a trusted offline build operator.

Not an API: local paths are never accepted from an HTTP request. Expected input
hashes are required. A declaration of public data is not a data-loss detector.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

from app.services.map_package_materialize import _write_final
from app.services.map_package_set import MAX_CHUNK_BYTES, MAX_CHUNKS, _open_file, parse_manifest


def build_package(recipe: dict, destination: Path, *, chunk_bytes: int = MAX_CHUNK_BYTES) -> dict:
    """Write verified chunks, then manifest last; never touch an existing output."""
    if type(chunk_bytes) is not int or not 1 <= chunk_bytes <= MAX_CHUNK_BYTES:
        raise ValueError('invalid_build_chunk_size')
    frozen = json.loads(json.dumps(recipe, ensure_ascii=False))
    sources = []
    assets = frozen.get('assets')
    if not isinstance(assets, list) or not 7 <= len(assets) <= 1024:
        raise ValueError('invalid_build_assets')
    count = 0
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict) or 'chunks' in asset:
            raise ValueError('invalid_build_asset')
        path = asset.pop('path', None)
        if (not isinstance(path, str) or not path.startswith('/') or
                any(part in ('', '.', '..') for part in path[1:].split('/'))):
            raise ValueError('invalid_build_source_path')
        sources.append(path)
        size = asset.get('size_bytes')
        if type(size) is not int or size <= 0:
            raise ValueError('invalid_build_asset_size')
        pieces = (size + chunk_bytes - 1) // chunk_bytes
        count += pieces
        if count > MAX_CHUNKS:
            raise ValueError('too_many_build_chunks')
        asset['chunks'] = [dict(file=f'asset-{index:04d}-{part:04d}.part',
                               size_bytes=min(chunk_bytes, size - part * chunk_bytes),
                               sha256='0' * 64) for part in range(pieces)]
    # Validate the entire output contract before allocating files.
    manifest = parse_manifest(json.dumps(frozen, ensure_ascii=False).encode())
    destination.mkdir(mode=0o700)  # exclusive; outside cleanup try
    root_fd = None
    try:
        root_fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        for asset, path in zip(manifest['assets'], sources):
            fd = _open_file(root_fd, path[1:])
            with os.fdopen(fd, 'rb') as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size != asset['size_bytes']:
                    raise ValueError('invalid_build_source_file')
                digest = hashlib.sha256()
                for chunk in asset['chunks']:
                    content = source.read(chunk['size_bytes'])
                    if len(content) != chunk['size_bytes']:
                        raise ValueError('build_source_truncated')
                    digest.update(content)
                    chunk['sha256'] = hashlib.sha256(content).hexdigest()
                    _write_final(destination / chunk['file'], content)
                if source.read(1) or digest.hexdigest() != asset['sha256']:
                    raise ValueError('build_source_hash_mismatch')
        content = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode()
        parse_manifest(content)
        _write_final(destination / 'manifest.json', content)
        directory_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return {'status': 'transport_built', 'publish_ready': False,
                'manifest_sha256': hashlib.sha256(content).hexdigest(),
                'assets': len(assets), 'chunks': count}
    except BaseException:
        shutil.rmtree(destination)  # only the new directory owned by this call
        raise
    finally:
        if root_fd is not None:
            os.close(root_fd)
