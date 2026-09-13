"""Coalesce history changes; metadata never grants access to the changed cases."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.models.case_pipeline import OutboxEvent

SOURCE_EVENT_TYPE = 'case.history.source.changed'
REFRESH_EVENT_TYPE = 'case.facilities.history.changed'
BATCH_SIZE = 1000


def record_change(db, *, case_id: int, area_ids: list[int | None]) -> None:
    """Caller commits with the index update or deletion; no business text retained."""
    identifier = str(uuid4())
    db.add(OutboxEvent(id=identifier, event_type=SOURCE_EVENT_TYPE,
        aggregate_type='case', aggregate_id=str(case_id), idempotency_key=identifier,
        status='pending', payload={'area_ids': list(dict.fromkeys(area_ids))}))


def coalesce_changes(db) -> str | None:
    """Called under the history index cursor lock, in its transaction.

    Only one active scan at a time. Later notifications stay durable and are
    combined by the next index pass, including changes arriving during a scan.
    """
    active = db.scalar(select(OutboxEvent.id).where(
        OutboxEvent.event_type == REFRESH_EVENT_TYPE,
        OutboxEvent.status.in_(('pending', 'processing', 'retry'))).limit(1))
    if active is not None:
        return None
    changes = list(db.scalars(select(OutboxEvent).where(
        OutboxEvent.event_type == SOURCE_EVENT_TYPE, OutboxEvent.status == 'pending')
        .order_by(OutboxEvent.created_at, OutboxEvent.id).limit(BATCH_SIZE)))
    if not changes:
        return None
    areas = set()
    for change in changes:
        areas.update(change.payload['area_ids'])
    identifier = str(uuid4())
    now = datetime.now(timezone.utc)
    db.add(OutboxEvent(id=identifier, event_type=REFRESH_EVENT_TYPE,
        aggregate_type='history_revision', aggregate_id=identifier,
        idempotency_key=identifier, status='pending', available_at=now,
        payload={'network_id': None, 'history_revision': identifier,
                 'area_ids': sorted(areas - {None}), 'unknown_area': None in areas,
                 'source_change_count': len(changes), 'cutoff': now.isoformat(),
                 'cursor': '', 'scanned': 0, 'created': 0, 'skipped': {},
                 'affected_region_policy': 'authorized_history_scope_conservative'}))
    for change in changes:
        change.status = 'completed'
        change.processed_at = now
        change.payload = {**change.payload, 'refresh_event_id': identifier}
    return identifier
