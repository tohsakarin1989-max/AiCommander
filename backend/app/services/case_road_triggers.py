"""Transactional handoff from completed case analysis to authorized road jobs.

Freezing a case result only records intent. Graph selection and permission reads
happen on the dedicated road worker, never in the case-save transaction.
"""
from datetime import datetime, timedelta, timezone
import hashlib
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.case_pipeline import CasePipelineState, OutboxEvent
from app.services.outbox_claim_service import OutboxClaimService

REQUEST_TYPE = 'case.roads.requested'


def capture_road_authority(db):
    """Copy server-bound scope only; never trust a client body or stale role."""
    actor = db.info.get('principal_user_id')
    if type(actor) is not int or actor <= 0 or 'authorized_area_ids' not in db.info:
        return None
    scope = db.info['authorized_area_ids']
    if scope is not None and (not isinstance(scope, (tuple, list))
            or any(type(value) is not int or value <= 0 for value in scope)):
        return None
    return {'user_id': actor, 'scope': None if scope is None else sorted(set(scope))}


def enqueue_completed_result(db, profile, result_id):
    """Use the source event for this exact profile, not an arbitrary last editor."""
    row = db.execute(select(OutboxEvent.payload).join(
        CasePipelineState, CasePipelineState.event_id == OutboxEvent.id).where(
        CasePipelineState.case_id == profile.case_id,
        CasePipelineState.source_hash == profile.source_hash,
        OutboxEvent.event_type == 'case.analysis.requested')).scalar_one_or_none()
    authority = row.get('road_authority') if isinstance(row, dict) else None
    if not isinstance(authority, dict) or row.get('source_hash') != profile.source_hash:
        return None  # Legacy/system-origin events have no implicit delegation.
    dialect = db.get_bind().dialect.name
    if dialect not in ('sqlite', 'postgresql'):
        raise ValueError('road_trigger_database_unsupported')
    insert = sqlite_insert if dialect == 'sqlite' else pg_insert
    key = hashlib.sha256(f'{REQUEST_TYPE}:{result_id}'.encode()).hexdigest()
    return db.scalar(insert(OutboxEvent).values(id=str(uuid4()), event_type=REQUEST_TYPE,
        aggregate_type='case_result', aggregate_id=result_id,
        payload={'result_id': result_id, 'authority': authority}, idempotency_key=key,
        status='pending', attempts=0).on_conflict_do_nothing(index_elements=['idempotency_key'])
        .returning(OutboxEvent.id))


def process_request(db, event_id):
    """Resolve the latest compatible graph under current, bounded authority."""
    from app.services.case_road_jobs import _identity, enqueue_comparison
    from app.services.vehicle_router import ENGINE_VERSION
    from app.services.road_network_contracts import RoadNetworkUnavailable
    from app.services.case_result_service import CaseResultService
    from app.services.case_road_vehicle import frozen_road_vehicle

    if db.new or db.dirty or db.deleted:
        raise ValueError('road_trigger_requires_clean_session')
    previous = dict(db.info)
    token = None
    failures = 0
    payload = None
    try:
        scheduled = db.get(OutboxEvent, event_id, populate_existing=True)
        if scheduled is not None and scheduled.event_type != REQUEST_TYPE:
            raise ValueError('unsupported_outbox_event')
        if scheduled is not None and scheduled.status in ('pending', 'retry', 'waiting_dependency'):
            available = scheduled.available_at
            if available is not None and (available.replace(tzinfo=timezone.utc)
                    if available.tzinfo is None else available) > datetime.now(timezone.utc):
                return {'event_id': event_id, 'status': scheduled.status, 'claimed': False}
            if scheduled.status == 'waiting_dependency':
                # Only this request type can wake a dependency wait. The normal
                # claim still owns the lease and fences the eventual commit.
                db.execute(update(OutboxEvent).where(OutboxEvent.id == event_id,
                    OutboxEvent.event_type == REQUEST_TYPE, OutboxEvent.status == 'waiting_dependency',
                    OutboxEvent.available_at <= datetime.now(timezone.utc))
                    .values(status='pending').execution_options(synchronize_session=False))
                db.expire_all()
        event, claimed = OutboxClaimService.claim(db, event_id, expected_type=REQUEST_TYPE)
        if not claimed:
            return {'event_id': event_id, 'status': event.status, 'claimed': False}
        token = event.worker_id
        payload = dict(event.payload)
        failures = payload.get('ordinary_failures', 0)
        if type(failures) is not int or not 0 <= failures <= 3:
            failures = 3
            raise ValueError('road_trigger_retry_metadata_invalid')
        authority = payload['authority']
        _identity(db, authority['user_id'], authority['scope'])
        vehicle = frozen_road_vehicle(CaseResultService.read(db, payload['result_id'])['content'])
        if vehicle is None:
            OutboxClaimService.finish(db, event_id=event_id, worker_id=token, status='completed',
                                     error='road_job_vehicle_information_missing')
            db.commit()
            return {'event_id': event_id, 'status': 'completed', 'outcome': 'vehicle_information_missing'}
        job = enqueue_comparison(db, result_id=payload['result_id'],
            analysis_at=datetime.now(timezone.utc),
            vehicle=vehicle,
            engine_version=ENGINE_VERSION, include_facility_pool=True)
        OutboxClaimService.finish(db, event_id=event_id, worker_id=token, status='completed')
        db.commit()
        return {'event_id': event_id, 'status': 'completed', 'job': job}
    except Exception as error:
        db.rollback()
        if token is None:
            raise
        waiting = isinstance(error, RoadNetworkUnavailable) and error.code == 'road_compatible_network_unavailable'
        # Missing setup is not a failed computation. Retain the request until
        # a compatible authorized graph exists; never spend native CPU here.
        if not waiting:
            failures += 1
            if payload is not None:
                db.execute(update(OutboxEvent).where(OutboxEvent.id == event_id,
                    OutboxEvent.worker_id == token, OutboxEvent.status == 'processing')
                    .values(payload={**payload, 'ordinary_failures': min(failures, 3)})
                    .execution_options(synchronize_session=False))
        status = 'waiting_dependency' if waiting else ('retry' if failures < 3 else 'failed')
        OutboxClaimService.finish(db, event_id=event_id, worker_id=token, status=status,
            error='road_trigger_waiting_network' if waiting else 'road_trigger_unavailable',
            available_at=datetime.now(timezone.utc) + timedelta(seconds=60 if waiting else 30))
        db.commit()
        return {'event_id': event_id, 'status': status}
    finally:
        db.info.clear()
        db.info.update(previous)
