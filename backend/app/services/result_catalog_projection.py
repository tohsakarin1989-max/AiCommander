"""Worker-only bounded reconciliation, with current-authorized read fallback.

The catalog never repairs this index. Source rows are still the candidate
universe, so missing/failed/stale projections cannot hide old materials.
"""
from datetime import datetime, timezone
import heapq

from sqlalchemy import String, and_, cast, func, update
from sqlalchemy.exc import IntegrityError

from app.models.result_catalog import ResultCatalogProjection as Projection, ResultCatalogReference as Reference
from app.services.intelligent_query_context import result_hash
from app.services.result_catalog_references import extract_references
from app.services.result_catalog_sources import MODELS, metadata, source_query, source_state
from app.utils.datetimes import utc_datetime

VERSION = 'result-catalog-7.4-1'


def projection_status(db, kind, identifier, authorized):
    """Call only after typed authorization; no positive permission cache here."""
    row = db.query(Projection).filter_by(material_kind=kind, material_id=str(identifier)).populate_existing().first()
    fallback = {'state': 'legacy_fallback', 'schema_version': VERSION}
    if row is None:
        return fallback
    stale = {**fallback, 'state': 'stale_fallback'}
    if row.algorithm_version != VERSION or row.state != 'ready':
        return stale
    try:
        _, current = source_state(db, kind, identifier)
    except (LookupError, ValueError, TypeError):
        return stale
    if (row.source_sha256 != result_hash(current) or row.title != authorized['title']
            or row.subject_kind != authorized['subject']['kind']
            or row.subject_id != str(authorized['subject']['id'])
            or utc_datetime(row.material_created_at) != utc_datetime(authorized['created_at'])
            or row.schema_version != authorized['schema_version']
            or row.content_sha256 is not None and row.content_sha256 != authorized['content_sha256']):
        return stale
    return {'state': 'ready', 'schema_version': VERSION}


def _candidates(db, limit):
    """At most 8 * limit small rows; merge before the global batch limit."""
    streams = []
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    for kind, model in MODELS.items():
        query = source_query(db, kind).with_entities(model.id, Projection.checked_at)
        query = query.outerjoin(Projection, and_(Projection.material_kind == kind,
                                                Projection.material_id == cast(model.id, String)))
        rows = query.order_by(func.coalesce(Projection.checked_at, epoch), model.id).limit(limit).all()
        stream = []
        for identifier, checked in rows:
            if checked is not None and checked.tzinfo is None:
                checked = checked.replace(tzinfo=timezone.utc)
            stream.append(((checked or epoch).timestamp(), kind, str(identifier)))
        # Lexical identity order is also the cross-kind deterministic tie-breaker.
        streams.append(sorted(stream))
    return list(heapq.merge(*streams))[:limit]


def _write_projection(db, kind, identifier, values, refs, now):
    row = db.query(Projection).filter_by(material_kind=kind, material_id=identifier).populate_existing().first()
    same = row is not None and all(
        utc_datetime(getattr(row, key)) == utc_datetime(value) if key == 'material_created_at'
        else getattr(row, key) == value for key, value in values.items())
    if same:
        keys = ('reference_kind', 'reference_id', 'expected_version', 'relation')
        existing = {tuple(getattr(ref, key) for key in keys) for ref in db.query(Reference)
                    .filter_by(material_kind=kind, material_id=identifier)}
        same = existing == {tuple(ref[key] for key in keys) for ref in refs}
    if same:
        db.execute(update(Projection).where(Projection.material_kind == kind, Projection.material_id == identifier,
                                           Projection.checked_at == row.checked_at).values(checked_at=now))
        return False
    if row is None:
        row = Projection(material_kind=kind, material_id=identifier, **values, checked_at=now, updated_at=now)
        db.add(row)
        db.flush()
    else:
        # Fence replacement of the reference set against another bounded worker.
        changed = db.execute(update(Projection).where(Projection.material_kind == kind,
            Projection.material_id == identifier, Projection.checked_at == row.checked_at)
            .values(**values, checked_at=now, updated_at=now)).rowcount
        if not changed:
            return False
    db.query(Reference).filter_by(material_kind=kind, material_id=identifier).delete(synchronize_session=False)
    db.add_all([Reference(material_kind=kind, material_id=identifier, **ref) for ref in refs])
    db.flush()
    return True


def reconcile_catalog(db, *, limit=25):
    """Independent service transaction only; never called from a save or GET."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('invalid_result_catalog_batch')
    if ('principal_user_id' in db.info or 'authorized_area_ids' in db.info
            or db.in_transaction() or db.new or db.dirty or db.deleted):
        raise PermissionError('result_catalog_requires_clean_service_session')
    candidates = _candidates(db, limit)
    updated = unchanged = failed = 0
    for _, kind, identifier in candidates:
        now = datetime.now(timezone.utc)
        try:
            row, state = source_state(db, kind, identifier)
            values = {**metadata(kind, row), 'source_sha256': result_hash(state),
                      'algorithm_version': VERSION, 'state': 'ready'}
            refs = extract_references(kind, row, state)
        except (KeyError, ValueError, TypeError, AttributeError, RecursionError):
            # A malformed historical row gets a checked marker, so it cannot
            # monopolize every batch. No exception text or source body is stored.
            values = {'title': None, 'material_created_at': None, 'subject_kind': None, 'subject_id': None,
                      'content_sha256': None, 'schema_version': None, 'source_sha256': None,
                      'algorithm_version': VERSION, 'state': 'failed'}
            refs = []
            failed += 1
        except LookupError:
            # Deleted during this sweep. Public reads use original rows anyway.
            failed += 1
            continue
        try:
            with db.begin_nested():
                changed = _write_projection(db, kind, identifier, values, refs, now)
            if values['state'] != 'failed':
                updated += int(changed)
                unchanged += int(not changed)
        except IntegrityError:
            # An insertion won by another worker is harmless; retry on a later sweep.
            failed += 1
    db.commit()
    return {'checked': len(candidates), 'updated': updated, 'unchanged': unchanged, 'failed': failed,
            'strategy': 'bounded_source_sweep', 'schema_version': VERSION}
