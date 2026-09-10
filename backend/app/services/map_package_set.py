"""Schema 2 public map transport integrity; NOT semantic or release approval.

No network, extraction, application DB or publishing occurs here. Paths belong
to a server-controlled staging directory. Callers must separately validate MVT,
gazetteer, style dependencies, fonts, licenses and road-reference completeness.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any
from app.services.map_font_profiles import font_profile


MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_CHUNK_BYTES = 16 * 1024 * 1024
MAX_SET_BYTES = 8 * 1024 * 1024 * 1024
MAX_CHUNKS = 8192
ROLES = {'vector', 'gazetteer', 'style', 'glyphs', 'sprite', 'road_source', 'boundaries'}
OPTIONAL_ROLES = {'license'}
MANIFEST_FIELDS = {'schema_version', 'bundle_id', 'source_version', 'provider',
                   'license', 'attribution', 'contains_internal_data', 'bounds',
                   'min_zoom', 'max_zoom', 'display_max_zoom', 'assets'}


def _open_file(root_fd: int, key: str) -> int:
    """Walk canonical components without following directory or file symlinks."""
    parts = key.split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise ValueError('invalid_asset_storage_key')
    parent = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=parent)
            os.close(parent)
            parent = child
        return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_manifest_key')
        result[key] = value
    return result


def _keys(value: Any, expected: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError('invalid_package_fields')


def _text(value: Any, maximum: int) -> None:
    if (not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum
            or any(ord(char) < 32 for char in value)):
        raise ValueError('invalid_package_text')


def _digest(value: Any) -> None:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('invalid_package_digest')


def parse_manifest(content: bytes) -> dict[str, Any]:
    """Parse a bounded exact contract, rejecting duplicates and remote paths."""
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_MANIFEST_BYTES:
        raise ValueError('invalid_manifest_size')
    try:
        manifest = json.loads(content, object_pairs_hook=_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('invalid_package_json') from exc
    _validate_manifest(manifest)
    return manifest


def read_manifest(directory: Path) -> dict[str, Any]:
    """Read only a regular, bounded manifest without following symbolic links."""
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open('manifest.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=descriptor)
        with os.fdopen(fd, 'rb') as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_MANIFEST_BYTES:
                raise ValueError('invalid_manifest_size_or_type')
            return parse_manifest(source.read(MAX_MANIFEST_BYTES + 1))
    finally:
        os.close(descriptor)


def _validate_manifest(manifest: dict[str, Any]) -> None:
    _keys(manifest, MANIFEST_FIELDS | ({'font_profile'} if isinstance(manifest, dict) and 'font_profile' in manifest else set()))
    font_profile(manifest)
    if manifest['schema_version'] != '2.0' or manifest['contains_internal_data'] is not False:
        raise ValueError('invalid_public_package_declaration')
    for key in ('bundle_id', 'source_version', 'provider', 'license', 'attribution'):
        _text(manifest[key], 512)
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}', manifest['bundle_id']):
        raise ValueError('invalid_bundle_id')
    bounds = manifest['bounds']
    if (not isinstance(bounds, list) or len(bounds) != 4
            or any(type(v) not in (int, float)
                   or (isinstance(v, float) and not math.isfinite(v)) for v in bounds)
            or not -180 <= bounds[0] < bounds[2] <= 180
            or not -85.051129 <= bounds[1] < bounds[3] <= 85.051129):
        raise ValueError('invalid_package_bounds')
    low, high, display = (manifest[key] for key in ('min_zoom', 'max_zoom', 'display_max_zoom'))
    if (any(type(v) is not int for v in (low, high, display))
            or not 0 <= low <= high <= display <= 19):
        raise ValueError('invalid_package_zoom')
    assets = manifest['assets']
    if not isinstance(assets, list) or not 7 <= len(assets) <= 1024:
        raise ValueError('invalid_package_assets')
    names, files, roles = set(), set(), set()
    total = 0
    for asset in assets:
        _keys(asset, {'name', 'role', 'size_bytes', 'sha256', 'chunks', 'license', 'attribution'})
        _text(asset['license'], 512)
        _text(asset['attribution'], 512)
        name, role = asset['name'], asset['role']
        if (not isinstance(name, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,99}', name)
                or name in names or not isinstance(role, str) or role not in ROLES | OPTIONAL_ROLES):
            raise ValueError('invalid_package_asset')
        names.add(name)
        roles.add(role)
        _digest(asset['sha256'])
        if type(asset['size_bytes']) is not int or not 0 < asset['size_bytes'] <= MAX_SET_BYTES:
            raise ValueError('invalid_asset_size')
        chunks = asset['chunks']
        if not isinstance(chunks, list) or not 1 <= len(chunks) <= MAX_CHUNKS:
            raise ValueError('invalid_package_chunks')
        size = 0
        for chunk in chunks:
            _keys(chunk, {'file', 'size_bytes', 'sha256'})
            filename = chunk['file']
            if (not isinstance(filename, str)
                    or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}\.part', filename)
                    or filename in files):
                raise ValueError('invalid_chunk_filename')
            files.add(filename)
            if len(files) > MAX_CHUNKS:
                raise ValueError('too_many_package_chunks')
            _digest(chunk['sha256'])
            if type(chunk['size_bytes']) is not int or not 0 < chunk['size_bytes'] <= MAX_CHUNK_BYTES:
                raise ValueError('invalid_chunk_size')
            size += chunk['size_bytes']
        if size != asset['size_bytes']:
            raise ValueError('asset_size_mismatch')
        total += size
        if total > MAX_SET_BYTES:
            raise ValueError('package_size_limit')
    if not ROLES <= roles:
        raise ValueError('missing_package_role')


def verify_directory(directory: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Rescan all bytes on resume; never trust an old progress marker.

Uses directory-relative, no-follow opens and hashes each asset in chunk order.
The report is not an authorization to publish or reopen mutable staged files.
"""
    _validate_manifest(manifest)
    errors, verified_chunks, assets = [], [], []
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for asset in manifest['assets']:
            digest = hashlib.sha256()
            valid = True
            for chunk in asset['chunks']:
                filename = chunk['file']
                try:
                    fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=descriptor)
                    with os.fdopen(fd, 'rb') as source:
                        metadata = os.fstat(source.fileno())
                        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != chunk['size_bytes']:
                            raise ValueError('chunk_size_or_type')
                        content = source.read(chunk['size_bytes'] + 1)
                    if (len(content) != chunk['size_bytes']
                            or hashlib.sha256(content).hexdigest() != chunk['sha256']):
                        raise ValueError('chunk_checksum')
                    digest.update(content)
                    verified_chunks.append(filename)
                except (OSError, ValueError):
                    valid = False
                    errors.append({'asset': asset['name'], 'chunk': filename,
                                   'code': 'chunk_missing_or_invalid'})
            if valid and digest.hexdigest() != asset['sha256']:
                valid = False
                errors.append({'asset': asset['name'], 'code': 'asset_checksum_mismatch'})
            if valid:
                assets.append({'name': asset['name'], 'role': asset['role'],
                               'sha256': asset['sha256'], 'size_bytes': asset['size_bytes']})
    finally:
        os.close(descriptor)
    return {'status': 'incomplete_or_invalid' if errors else 'integrity_verified',
            'bundle_id': manifest['bundle_id'], 'publish_ready': False,
            'verified_chunks': verified_chunks, 'assets': assets, 'errors': errors}
