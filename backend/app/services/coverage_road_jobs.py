"""Durable coverage road work using the existing road queue and fenced Outbox."""
import hashlib
import json
import math
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.case_pipeline import OutboxEvent
from app.models.user import User
from app.services.case_road_jobs import _identity
from app.services.coverage_road_comparison import compare_coverage_roads
from app.services.outbox_claim_service import OutboxClaimService
from app.services.road_access_policy import VehicleAssumption
from app.services.road_network_service import select_network, resolve_network
from app.services.spatial_coverage_service import read_comparison
from app.services.vehicle_router import ENGINE_VERSION, RoadCalculationError

EVENT_TYPE = 'coverage.roads.compare'
JOB_VERSION = 'coverage-road-job-4.4-1'


class DurableCancellation:
    """Fresh short reads; never reuse the long-running worker transaction."""

    def __init__(self, factory, event_id, token, external=None, *, event_type=EVENT_TYPE):
        self.factory, self.event_id, self.token, self.external = factory, event_id, token, external
        self.event_type = event_type
        self.checked_at = float('-inf')
        self.stopped = False

    def is_set(self):
        if self.stopped or (self.external is not None and self.external.is_set()):
            return True
        now = time.monotonic()
        if now - self.checked_at < 0.25:
            return False
        try:
            with self.factory() as session:
                row = session.execute(select(OutboxEvent.status, OutboxEvent.worker_id).where(
                    OutboxEvent.id == self.event_id, OutboxEvent.event_type == self.event_type)).first()
        except Exception as error:
            raise RoadCalculationError('coverage_job_status_unavailable') from error
        self.checked_at = now
        self.stopped = row is None or row.status != 'processing' or row.worker_id != self.token
        return self.stopped


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def enqueue(db, comparison_id, *, at, vehicle, distance_budget_m):
    if (type(distance_budget_m) not in (int, float) or not math.isfinite(distance_budget_m)
            or not 0 < distance_budget_m <= 50000):
        raise ValueError('coverage_road_budget_invalid')
    actor = db.info.get('principal_user_id')
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('coverage_job_scope_missing')
    ceiling = db.info['authorized_area_ids']
    _identity(db, actor, None if ceiling is None else list(ceiling))
    source = read_comparison(db, comparison_id, now=at)
    if source['freshness'] != 'unchanged_inputs':
        raise ValueError('coverage_source_changed')
    binding = select_network(db, analysis_at=at, vehicle=vehicle, engine_version=ENGINE_VERSION)
    scope = db.info['authorized_area_ids']
    payload = {'job_version': JOB_VERSION, 'comparison_id': comparison_id, 'user_id': actor,
        'scope': None if scope is None else list(scope), 'coverage_input_digest': source['input_digest'],
        'network_id': binding.network_id, 'graph_sha256': binding.graph_sha256,
        'policy_revision': binding.policy_revision, 'vehicle': vehicle.model_dump(),
        'distance_budget_m': distance_budget_m}
    key = digest(payload)
    payload['analysis_at'] = at.isoformat()
    dialect = db.get_bind().dialect.name
    if dialect not in ('sqlite', 'postgresql'):
        raise ValueError('coverage_job_database_unsupported')
    insert = sqlite_insert if dialect == 'sqlite' else pg_insert
    identifier = db.scalar(insert(OutboxEvent).values(id=str(uuid4()), event_type=EVENT_TYPE,
        aggregate_type='coverage_comparison', aggregate_id=comparison_id, payload=payload,
        idempotency_key=key, status='pending', attempts=0)
        .on_conflict_do_nothing(index_elements=['idempotency_key']).returning(OutboxEvent.id))
    created = identifier is not None
    if identifier is None:
        identifier = db.scalar(select(OutboxEvent.id).where(OutboxEvent.idempotency_key == key))
    return {'event_id': identifier, 'created': created}


def _authorize(db, payload):
    ceiling = payload['scope']
    current = db.info.get('authorized_area_ids')
    if current is not None:
        ceiling = sorted(set(current) if ceiling is None else set(current).intersection(ceiling))
    _identity(db, payload['user_id'], ceiling)
    vehicle = VehicleAssumption.model_validate(payload['vehicle'])
    at = datetime.fromisoformat(payload['analysis_at'])
    source = read_comparison(db, payload['comparison_id'], now=datetime.now(timezone.utc))
    binding = resolve_network(db, payload['network_id'], analysis_at=at, vehicle=vehicle)
    if (source['freshness'] != 'unchanged_inputs' or source['input_digest'] != payload['coverage_input_digest']
            or binding.graph_sha256 != payload['graph_sha256'] or binding.policy_revision != payload['policy_revision']):
        raise ValueError('coverage_job_inputs_changed')
    return at, vehicle


def process(db, event_id, *, artifact_root, cancel_event=None):
    if db.new or db.dirty or db.deleted:
        raise ValueError('coverage_job_requires_clean_session')
    previous_info = dict(db.info)
    token = None
    try:
        scheduled = db.get(OutboxEvent, event_id, populate_existing=True)
        if scheduled and scheduled.status in ('pending', 'retry') and OutboxClaimService._aware(scheduled.available_at) > datetime.now(timezone.utc):
            return {'event_id': event_id, 'status': scheduled.status, 'claimed': False}
        event, claimed = OutboxClaimService.claim(db, event_id, expected_type=EVENT_TYPE)
        if not claimed:
            return {'event_id': event_id, 'status': event.status, 'claimed': False}
        token, attempts, payload = event.worker_id, event.attempts, dict(event.payload)
        if payload.get('job_version') != JOB_VERSION:
            raise ValueError('coverage_job_version_changed')
        at, vehicle = _authorize(db, payload)
        db.rollback()
        cancel_event = DurableCancellation(sessionmaker(bind=db.get_bind()), event_id, token, cancel_event)
        if cancel_event is not None and cancel_event.is_set():
            raise RoadCalculationError('road_calculation_cancelled')
        result = compare_coverage_roads(db, payload['comparison_id'], at=at, vehicle=vehicle,
            distance_budget_m=payload['distance_budget_m'], artifact_root=artifact_root,
            cancel_event=cancel_event, network_id=payload['network_id'])
        _authorize(db, payload)
        if cancel_event is not None and cancel_event.is_set():
            raise RoadCalculationError('road_calculation_cancelled')
        # Both payload update and terminal status are guarded by the claim token
        # and committed together; an expired worker cannot publish an artifact.
        from app.services.outbox_claim_service import OutboxClaimLostError
        updated = db.query(OutboxEvent).filter(OutboxEvent.id == event_id,
            OutboxEvent.status == 'processing', OutboxEvent.worker_id == token).update(
                {OutboxEvent.payload: {**payload, 'artifact': result, 'artifact_checksum': digest(result)}},
                synchronize_session=False)
        if updated != 1:
            raise OutboxClaimLostError('outbox_claim_lost')
        OutboxClaimService.finish(db, event_id=event_id, worker_id=token, status='completed')
        db.commit()
        return {'event_id': event_id, 'status': 'completed', 'outcome': result['state']}
    except Exception as error:
        db.rollback()
        if token is None:
            raise
        current = db.get(OutboxEvent, event_id, populate_existing=True)
        if current is not None and current.status == 'cancelled':
            return {'event_id': event_id, 'status': 'cancelled'}
        cancelled = isinstance(error, RoadCalculationError) and str(error) == 'road_calculation_cancelled'
        terminal = isinstance(error, (PermissionError, ValueError))
        status = 'cancelled' if cancelled else 'failed' if terminal or attempts >= 3 else 'retry'
        OutboxClaimService.finish(db, event_id=event_id, worker_id=token, status=status,
            error='coverage_job_cancelled' if cancelled else 'coverage_job_unavailable',
            available_at=datetime.now(timezone.utc) + timedelta(seconds=min(60, 2 ** attempts)))
        db.commit()
        return {'event_id': event_id, 'status': status}
    finally:
        db.info.clear()
        db.info.update(previous_info)


def read_job(db, event_id):
    actor = db.info.get('principal_user_id')
    event = db.get(OutboxEvent, event_id, populate_existing=True)
    if event is None or event.event_type != EVENT_TYPE or event.payload.get('user_id') != actor:
        raise PermissionError('coverage_job_unavailable')
    payload = event.payload
    _authorize(db, payload)
    artifact = payload.get('artifact') if event.status == 'completed' else None
    if artifact is not None and digest(artifact) != payload.get('artifact_checksum'):
        raise ValueError('coverage_artifact_invalid')
    return {'event_id': event_id, 'status': event.status, 'artifact': artifact,
            'error': event.error, 'execution_task_created': False}


def list_jobs(db, comparison_id, *, page=1, page_size=20):
    """Owner-only metadata; opening an artifact rechecks road authorization."""
    if not 1 <= page <= 100000 or not 1 <= page_size <= 100:
        raise ValueError('coverage_job_page_invalid')
    actor = db.info.get('principal_user_id')
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('coverage_job_scope_missing')
    scope = db.info['authorized_area_ids']
    _identity(db, actor, None if scope is None else list(scope))
    read_comparison(db, comparison_id, now=datetime.now(timezone.utc))
    query = db.query(OutboxEvent).filter(OutboxEvent.event_type == EVENT_TYPE,
        OutboxEvent.aggregate_type == 'coverage_comparison', OutboxEvent.aggregate_id == comparison_id,
        OutboxEvent.payload['user_id'].as_integer() == actor)
    total = query.count()
    rows = query.with_entities(OutboxEvent.id, OutboxEvent.status, OutboxEvent.created_at).order_by(
        OutboxEvent.created_at.desc(), OutboxEvent.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {'items': [{'event_id': row.id, 'status': row.status, 'created_at': row.created_at} for row in rows],
            'total': total, 'page': page, 'page_size': page_size,
            'boundary': '仅列本人提交的后台任务；结果读取重新检查当前道路许可、来源和版本。'}


def cancel_job(db, event_id):
    actor = db.info.get('principal_user_id')
    if type(actor) is not int or not db.scalar(select(User.id).where(User.id == actor, User.is_active.is_(True))):
        raise PermissionError('coverage_job_unavailable')
    event = db.get(OutboxEvent, event_id, populate_existing=True)
    if event is None or event.event_type != EVENT_TYPE or event.payload.get('user_id') != actor:
        raise PermissionError('coverage_job_unavailable')
    db.query(OutboxEvent).filter(OutboxEvent.id == event_id,
        OutboxEvent.status.in_(('pending', 'retry', 'processing'))).update({
            OutboxEvent.status: 'cancelled', OutboxEvent.worker_id: None,
            OutboxEvent.claimed_at: None, OutboxEvent.lease_until: None,
            OutboxEvent.processed_at: datetime.now(timezone.utc),
            OutboxEvent.error: 'coverage_job_cancelled'}, synchronize_session=False)
    db.commit()
    current = db.get(OutboxEvent, event_id, populate_existing=True)
    return {'event_id': event_id, 'status': current.status, 'execution_task_created': False}
