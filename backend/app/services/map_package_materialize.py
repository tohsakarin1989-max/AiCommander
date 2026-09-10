"""Reassemble public assets for subsequent content validation, never publish."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any

from app.services.map_package_set import parse_manifest


def materialize_package(source_directory: Path, manifest: dict[str, Any],
                        staging_root: Path) -> Path:
    """Return a new private completed directory; clean only our partial output.

Both directories are controlled by the server, never supplied by a web client.
Read-only modes guard accidental edits, not privileged filesystem mutation.
Consumers must still verify asset hashes before registering immutable storage.
"""
    # Validate AND freeze a private copy before allocating output or opening files.
    frozen = parse_manifest(json.dumps(manifest, ensure_ascii=False).encode('utf-8'))
    source_fd = os.open(source_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    destination: Path | None = None
    try:
        destination = Path(tempfile.mkdtemp(prefix='map-assembly-', dir=staging_root))
        records = []
        for index, asset in enumerate(frozen['assets']):
            filename = f'asset-{index:04d}.bin'
            target = destination / filename
            digest = hashlib.sha256()
            with target.open('xb') as output:
                for chunk in asset['chunks']:
                    fd = os.open(chunk['file'], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=source_fd)
                    with os.fdopen(fd, 'rb') as source:
                        metadata = os.fstat(source.fileno())
                        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != chunk['size_bytes']:
                            raise ValueError('invalid_assembly_chunk')
                        content = source.read(chunk['size_bytes'] + 1)
                    if (len(content) != chunk['size_bytes']
                            or hashlib.sha256(content).hexdigest() != chunk['sha256']):
                        raise ValueError('assembly_chunk_checksum_mismatch')
                    # Write the same bytes we hashed; do not reopen the source.
                    output.write(content)
                    digest.update(content)
                if digest.hexdigest() != asset['sha256']:
                    raise ValueError('assembly_asset_checksum_mismatch')
                output.flush()
                os.fsync(output.fileno())
                os.fchmod(output.fileno(), 0o400)
            records.append({'name': asset['name'], 'role': asset['role'], 'file': filename,
                            'size_bytes': asset['size_bytes'], 'sha256': asset['sha256'],
                            'license': asset['license'], 'attribution': asset['attribution']})
        manifest_bytes = json.dumps(frozen, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')
        _write_final(destination / 'manifest.json', manifest_bytes)
        receipt = {'status': 'assembled_integrity_verified', 'publish_ready': False,
                   'bundle_id': frozen['bundle_id'],
                   'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
                   'assets': records}
        _write_final(destination / 'assembled.json', json.dumps(receipt).encode('utf-8'))
        directory_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return destination
    except BaseException:
        # Only the exact new mkdtemp directory belongs to this operation. Old
        # packages and incoming files are never cleanup targets.
        if destination is not None:
            shutil.rmtree(destination)
        raise
    finally:
        os.close(source_fd)


def _write_final(path: Path, content: bytes) -> None:
    with path.open('xb') as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
        os.fchmod(output.fileno(), 0o400)
