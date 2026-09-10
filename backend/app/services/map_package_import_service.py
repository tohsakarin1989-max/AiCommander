"""Durable chunk reception, independent of Redis and semantic acceptance.

Only admin endpoints invoke these operations. Each mutator owns its transaction.
Files are immutable by declared digest; receipts are not publication evidence.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models.map_package_import import MapPackageImport, MapPackageImportChunk
from app.services.map_package_set import parse_manifest


def _row(db, run_id, *, lock=False):
    try:
        if str(UUID(run_id)) != run_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('map_import_not_found') from None
    if lock:
        # A real UPDATE serializes this run on SQLite as well as PostgreSQL.
        db.execute(update(MapPackageImport).where(MapPackageImport.id == run_id)
                   .values(updated_at=datetime.now(timezone.utc)))
    row = db.query(MapPackageImport).filter_by(id=run_id).populate_existing().first()
    if row is None:
        raise ValueError('map_import_not_found')
    return row


def _manifest(row):
    manifest = parse_manifest(json.dumps(row.manifest, ensure_ascii=False).encode())
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    if hashlib.sha256(canonical).hexdigest() != row.manifest_hash:
        raise ValueError('map_import_manifest_changed')
    return manifest


def create_import(db, content: bytes, *, user_id):
    manifest = parse_manifest(content)
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    existing = db.query(MapPackageImport).filter_by(manifest_hash=digest).first()
    if existing is not None:
        return existing
    row = MapPackageImport(id=str(uuid4()), manifest_hash=digest, manifest=manifest,
                           status='receiving', created_by=user_id)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(MapPackageImport).filter_by(manifest_hash=digest).first()
        if existing is None:
            raise
        return existing
    return row


def _chunk_directory(run_id):
    root = Path(settings.MAP_PACKAGE_ROOT)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in ('imports', run_id, 'chunks'):
            try:
                os.mkdir(component, mode=0o700, dir_fd=parent)
            except FileExistsError:
                pass
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        return os.dup(parent)
    finally:
        os.close(parent)


def put_chunk(db, run_id: str, name: str, content: bytes):
    row = _row(db, run_id, lock=True)
    if row.status not in ('receiving', 'failed'):
        raise ValueError('map_import_not_receiving')
    manifest = _manifest(row)
    expected = {c['file']: c for a in manifest['assets'] for c in a['chunks']}.get(name)
    if expected is None:
        raise ValueError('map_import_unknown_chunk')
    if (not isinstance(content, bytes) or len(content) != expected['size_bytes']
            or hashlib.sha256(content).hexdigest() != expected['sha256']):
        raise ValueError('map_import_chunk_mismatch')
    parent = _chunk_directory(run_id)
    temporary = f'.upload-{uuid4().hex}'
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
            os.fchmod(target.fileno(), 0o400)
        os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
        receipt = db.get(MapPackageImportChunk, (run_id, name))
        if receipt is None:
            db.add(MapPackageImportChunk(import_id=run_id, name=name,
                sha256=expected['sha256'], size_bytes=expected['size_bytes']))
        else:
            receipt.sha256, receipt.size_bytes = expected['sha256'], expected['size_bytes']
        row.status, row.error_code, row.report = 'receiving', None, None
        db.commit()
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass
        os.close(parent)
    return {'name': name, 'size_bytes': expected['size_bytes'], 'sha256': expected['sha256']}


def get_import(db, run_id: str):
    row = _row(db, run_id)
    manifest = _manifest(row)
    expected = {c['file']: c for a in manifest['assets'] for c in a['chunks']}
    receipts = db.query(MapPackageImportChunk).filter_by(import_id=run_id).all()
    received = {r.name for r in receipts if r.name in expected
                and r.sha256 == expected[r.name]['sha256'] and r.size_bytes == expected[r.name]['size_bytes']}
    return {'id': row.id, 'bundle_id': manifest['bundle_id'], 'status': row.status,
            'manifest_hash': row.manifest_hash, 'total_chunks': len(expected),
            'received_chunks': len(received), 'missing_chunks': sorted(set(expected) - received),
            'error_code': row.error_code, 'publish_ready': False,
            'registration': (row.report or {}).get('registration'),
            'auto_publication': (row.report or {}).get('auto_publication'),
            'progress_basis': 'durable_receipts_not_current_content_verification'}


def submit_import(db, run_id: str):
    row = _row(db, run_id, lock=True)
    if row.status == 'queued':
        db.commit()
        return get_import(db, run_id)
    if row.status != 'receiving':
        raise ValueError('map_import_not_receiving')
    progress = get_import(db, run_id)
    if progress['missing_chunks']:
        raise ValueError('map_import_incomplete')
    # The durable row is the queue source of truth. A later worker rechecks
    # all files; never send a success claim based only on upload receipts.
    row.status = 'queued'
    db.commit()
    return get_import(db, run_id)
