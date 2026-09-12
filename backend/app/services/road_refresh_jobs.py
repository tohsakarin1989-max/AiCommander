"""Publication-driven refresh, bounded by graph applicability, not old edges.

Without a trustworthy topology delta the entire compatible graph is the
conservative affected connection region. This includes prior no-path results and
new shortcuts. Scan delegated request metadata in small durable pages; never
borrow the publishing administrator's business-data authority.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.case_pipeline import OutboxEvent
from app.services.case_road_jobs import EVENT_TYPE as COMPARE_TYPE, _identity, enqueue_comparison
from app.services.facility_analysis_versions import current_versions
from app.services.case_road_triggers import REQUEST_TYPE
from app.services.case_result_service import CaseResultService
from app.services.case_road_vehicle import frozen_road_vehicle
from app.services.outbox_claim_service import OutboxClaimService
from app.services.road_network_service import select_network
from app.services.road_network_contracts import RoadNetworkUnavailable
from app.services.vehicle_router import ENGINE_VERSION
from app.services.history_road_refresh import REFRESH_EVENT_TYPE as HISTORY_EVENT_TYPE

EVENT_TYPE = 'road.network.published'
UPGRADE_EVENT_TYPE = 'case.facilities.algorithm.upgraded'
PAGE_SIZE = 25


def enqueue_publication(db, network_id, *, valid_from=None):
    """Called only by the authorized publisher, in the ready transition transaction."""
    dialect = db.get_bind().dialect.name
    if dialect not in ('sqlite', 'postgresql'):
        raise ValueError('road_refresh_database_unsupported')
    insert = sqlite_insert if dialect == 'sqlite' else pg_insert
    key = hashlib.sha256(f'{EVENT_TYPE}:{network_id}'.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    start = OutboxClaimService._aware(valid_from)
    return db.scalar(insert(OutboxEvent).values(
        id=str(uuid4()), event_type=EVENT_TYPE, aggregate_type='road_network',
        aggregate_id=network_id, idempotency_key=key, status='pending', attempts=0,
        available_at=max(now, start),
        payload={'network_id': network_id, 'cutoff': now.isoformat(),
                 'cursor': '', 'scanned': 0, 'created': 0, 'skipped': {},
                 'affected_region_policy': 'whole_compatible_graph_conservative'})
        .on_conflict_do_nothing(index_elements=['idempotency_key']).returning(OutboxEvent.id))


def enqueue_algorithm_upgrade(db):
    """Record one bounded historical pass per version, not one pass per poll."""
    versions = current_versions()
    signature = hashlib.sha256(json.dumps(versions, sort_keys=True).encode()).hexdigest()
    dialect = db.get_bind().dialect.name
    if dialect not in ('sqlite', 'postgresql'):
        raise ValueError('road_refresh_database_unsupported')
    insert = sqlite_insert if dialect == 'sqlite' else pg_insert
    now = datetime.now(timezone.utc)
    return db.scalar(insert(OutboxEvent).values(
        id=str(uuid4()), event_type=UPGRADE_EVENT_TYPE, aggregate_type='facility_algorithm',
        aggregate_id=signature, idempotency_key=f'{UPGRADE_EVENT_TYPE}:{signature}',
        status='pending', attempts=0, available_at=now,
        payload={'network_id': None, 'versions': versions, 'cutoff': now.isoformat(),
                 'cursor': '', 'scanned': 0, 'created': 0, 'skipped': {},
                 'affected_region_policy': 'all_previously_delegated_current_results'})
        .on_conflict_do_nothing(index_elements=['idempotency_key']).returning(OutboxEvent.id))


def _refresh_request(db, request, network_id, *, history_change=None):
    authority = request.get('authority') if isinstance(request, dict) else None
    if not isinstance(authority, dict) or not {'user_id', 'scope'} <= authority.keys():
        return 'original_delegation_missing'
    _identity(db, authority['user_id'], authority['scope'])
    if history_change is not None:
        scope = db.info['authorized_area_ids']
        if (scope is not None and not history_change['unknown_area']
                and set(scope).isdisjoint(history_change['area_ids'])):
            return 'history_scope_unaffected'
    result = CaseResultService.read(db, request['result_id'])
    latest = CaseResultService.latest(db, result['content']['case_id'])
    if latest['id'] != request['result_id'] or latest['freshness'] != 'current':
        return 'stale_result'
    previous_job = db.scalar(select(OutboxEvent).where(
        OutboxEvent.event_type == COMPARE_TYPE,
        OutboxEvent.aggregate_id == request['result_id'])
        .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc()).limit(1))
    if previous_job is not None and previous_job.status == 'cancelled':
        return 'previous_comparison_cancelled'
    vehicle = frozen_road_vehicle(result['content'])
    if vehicle is None:
        return 'vehicle_information_missing'
    now = datetime.now(timezone.utc)
    selected = select_network(db, analysis_at=now, vehicle=vehicle, engine_version=ENGINE_VERSION)
    if network_id is not None and selected.network_id != network_id:
        return 'different_applicable_network'
    job = enqueue_comparison(db, result_id=request['result_id'], analysis_at=now,
                             vehicle=vehicle, engine_version=ENGINE_VERSION, include_facility_pool=True,
                             **({'history_revision': history_change['history_revision']}
                                if history_change is not None else {}))
    return 'created' if job['created'] else 'already_queued'


def process(db, event_id):
    """One metadata page per claim; cursor and child jobs commit behind one fence."""
    if db.new or db.dirty or db.deleted:
        raise ValueError('road_refresh_requires_clean_session')
    previous = dict(db.info)
    token = None
    try:
        scheduled = db.get(OutboxEvent, event_id, populate_existing=True)
        if scheduled is not None and scheduled.event_type not in (EVENT_TYPE, UPGRADE_EVENT_TYPE, HISTORY_EVENT_TYPE):
            raise ValueError('unsupported_outbox_event')
        if (scheduled is not None and scheduled.status in ('pending', 'retry')
                and OutboxClaimService._aware(scheduled.available_at) > datetime.now(timezone.utc)):
            return {'event_id': event_id, 'status': scheduled.status, 'claimed': False}
        event, claimed = OutboxClaimService.claim(db, event_id,
            expected_type=scheduled.event_type if scheduled is not None else EVENT_TYPE)
        if not claimed:
            return {'event_id': event_id, 'status': event.status, 'claimed': False}
        token = event.worker_id
        payload = dict(event.payload)
        if event.event_type == UPGRADE_EVENT_TYPE and payload['versions'] != current_versions():
            OutboxClaimService.finish(db, event_id=event_id, worker_id=token, status='superseded')
            db.commit()
            return {'event_id': event_id, 'status': 'superseded'}
        skipped = dict(payload['skipped'])
        rows = db.execute(select(OutboxEvent.id, OutboxEvent.payload).where(
            OutboxEvent.event_type == REQUEST_TYPE,
            OutboxEvent.id > payload['cursor'],
            OutboxEvent.created_at <= datetime.fromisoformat(payload['cutoff']),
            OutboxEvent.status != 'cancelled')
            .order_by(OutboxEvent.id).limit(PAGE_SIZE + 1)).all()
        for identifier, request in rows[:PAGE_SIZE]:
            db.info.clear()
            db.info.update(previous)
            try:
                outcome = _refresh_request(db, request, payload['network_id'],
                    **({'history_change': payload} if event.event_type == HISTORY_EVENT_TYPE else {}))
            except (PermissionError, RoadNetworkUnavailable, LookupError):
                outcome = 'source_or_authority_unavailable'
            if outcome == 'created':
                payload['created'] += 1
            else:
                skipped[outcome] = skipped.get(outcome, 0) + 1
            payload['scanned'] += 1
            payload['cursor'] = identifier
        payload['skipped'] = skipped
        payload['ordinary_failures'] = 0
        db.execute(update(OutboxEvent).where(OutboxEvent.id == event_id,
            OutboxEvent.worker_id == token, OutboxEvent.status == 'processing')
            .values(payload=payload).execution_options(synchronize_session=False))
        status = 'pending' if len(rows) > PAGE_SIZE else 'completed'
        OutboxClaimService.finish(db, event_id=event_id, worker_id=token, status=status,
                                 available_at=datetime.now(timezone.utc))
        db.commit()
        return {'event_id': event_id, 'status': status,
                'scanned': payload['scanned'], 'created': payload['created']}
    except Exception:
        db.rollback()
        if token is None:
            raise
        event = db.get(OutboxEvent, event_id, populate_existing=True)
        payload = dict(event.payload)
        failures = payload.get('ordinary_failures', 0) + 1
        payload['ordinary_failures'] = failures
        db.execute(update(OutboxEvent).where(OutboxEvent.id == event_id,
            OutboxEvent.worker_id == token, OutboxEvent.status == 'processing')
            .values(payload=payload).execution_options(synchronize_session=False))
        status = 'retry' if failures < 3 else 'failed'
        OutboxClaimService.finish(db, event_id=event_id, worker_id=token, status=status,
            error='road_refresh_unavailable',
            available_at=datetime.now(timezone.utc) + timedelta(seconds=30))
        db.commit()
        return {'event_id': event_id, 'status': status}
    finally:
        db.info.clear()
        db.info.update(previous)
