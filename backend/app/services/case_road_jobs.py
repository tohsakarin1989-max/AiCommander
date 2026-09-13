"""Durable, identity-bound road jobs. No system-wide principal or source writes.

Internal callers enqueue in their own transaction. This is not an HTTP API;
the periodic automatic trigger is integrated separately from this worker core.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import bind_principal_scope
from app.models.case_pipeline import OutboxEvent
from app.models.user import User
from app.services.case_result_service import CaseResultService
from app.services.case_road_artifact_service import freeze_road_artifact
from app.services.case_road_comparison import compare_result_roads
from app.services.outbox_claim_service import OutboxClaimService
from app.services.road_access_policy import VehicleAssumption
from app.services.road_network_service import resolve_network, select_network
from app.services.vehicle_router import RoadCalculationError
from app.services.facility_analysis_versions import current_versions

EVENT_TYPE = 'case.roads.compare'
JOB_VERSION = 'case-road-job-4.2.0-1'


def _identity(db, user_id, ceiling):
    if type(user_id) is not int or user_id <= 0:
        raise PermissionError('road_job_identity_unavailable')
    if ceiling is not None and (not isinstance(ceiling, list)
            or any(type(value) is not int or value <= 0 for value in ceiling)):
        raise ValueError('road_job_scope_invalid')
    role = db.scalar(select(User.role).where(User.id == user_id, User.is_active.is_(True)))
    if role not in ('admin', 'analyst'):
        raise PermissionError('road_job_identity_unavailable')
    bind_principal_scope(db, SimpleNamespace(user_id=user_id, role=role), method='GET')
    current = db.info['authorized_area_ids']
    if ceiling is not None:
        db.info['authorized_area_ids'] = tuple(sorted(set(ceiling).intersection(
            ceiling if current is None else current)))


def enqueue_comparison(db, *, result_id, analysis_at, vehicle, engine_version,
                       include_facility_pool=False, history_revision=None):
    """Persist once per frozen input/scope/graph, without committing caller work."""
    actor = db.info.get('principal_user_id')
    if 'authorized_area_ids' not in db.info:
        raise PermissionError('road_job_identity_unavailable')
    ceiling = db.info['authorized_area_ids']
    ceiling = None if ceiling is None else list(ceiling)
    _identity(db, actor, ceiling)
    source = CaseResultService.read(db, result_id)
    binding = select_network(db, analysis_at=analysis_at, vehicle=vehicle, engine_version=engine_version)
    scope = db.info['authorized_area_ids']
    payload = {'job_version': JOB_VERSION, 'result_id': result_id, 'user_id': actor,
        'scope': None if scope is None else sorted(scope), 'content_sha256': source['content_sha256'],
        'network_id': binding.network_id, 'graph_sha256': binding.graph_sha256,
        'policy_revision': binding.policy_revision, 'vehicle': vehicle.model_dump()}
    if include_facility_pool:
        payload['facility_versions'] = current_versions()
        payload['facility_algorithm'] = payload['facility_versions']['scorer']
    if history_revision is not None:
        if not include_facility_pool:
            raise ValueError('history_refresh_requires_facility_pool')
        # Internal event identity, not a claim that the entire corpus was frozen.
        payload['history_refresh_event_id'] = str(UUID(history_revision))
    key = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    payload['analysis_at'] = analysis_at.isoformat()
    dialect = db.get_bind().dialect.name
    if dialect not in ('sqlite', 'postgresql'):
        raise ValueError('road_job_database_unsupported')
    insert = sqlite_insert if dialect == 'sqlite' else pg_insert
    identifier = db.scalar(insert(OutboxEvent).values(id=str(uuid4()), event_type=EVENT_TYPE,
        aggregate_type='case_result', aggregate_id=result_id, payload=payload,
        idempotency_key=key, status='pending', attempts=0, created_at=datetime.now(timezone.utc))
        .on_conflict_do_nothing(index_elements=['idempotency_key']).returning(OutboxEvent.id))
    created = identifier is not None
    if not identifier:
        identifier = db.scalar(select(OutboxEvent.id).where(OutboxEvent.idempotency_key == key))
    return {'event_id': identifier, 'created': created}


def process_comparison(db, event_id, *, artifact_root, cancel_event=None):
    """Use a dedicated worker session; artifact and fenced completion commit together."""
    if db.new or db.dirty or db.deleted:
        raise ValueError('road_job_requires_clean_session')
    previous_info = dict(db.info)
    token = None
    try:
        scheduled = db.get(OutboxEvent, event_id, populate_existing=True)
        if scheduled is not None and scheduled.status in ('pending', 'retry'):
            available = scheduled.available_at
            if available is not None and (available.replace(tzinfo=timezone.utc)
                    if available.tzinfo is None else available) > datetime.now(timezone.utc):
                return {'event_id': event_id, 'status': scheduled.status, 'claimed': False}
        event, claimed = OutboxClaimService.claim(db, event_id, expected_type=EVENT_TYPE)
        if not claimed:
            return {'event_id': event_id, 'status': event.status, 'claimed': False}
        token, attempts = event.worker_id, event.attempts
        payload = dict(event.payload)
        if (payload.get('job_version') != JOB_VERSION or
                (payload.get('facility_algorithm') and payload.get('facility_versions') != current_versions())):
            OutboxClaimService.finish(db, event_id=event_id, worker_id=token, status='superseded')
            db.commit()
            return {'event_id': event_id, 'status': 'superseded'}
        _identity(db, payload['user_id'], payload['scope'])
        at = datetime.fromisoformat(payload['analysis_at'])
        vehicle = VehicleAssumption.model_validate(payload['vehicle'])
        def authorize():
            _identity(db, payload['user_id'], payload['scope'])
            source = CaseResultService.read(db, payload['result_id'])
            binding = resolve_network(db, payload['network_id'], analysis_at=at, vehicle=vehicle)
            if (source['content_sha256'] != payload['content_sha256']
                    or binding.graph_sha256 != payload['graph_sha256']
                    or binding.policy_revision != payload['policy_revision']):
                raise ValueError('road_job_inputs_changed')
        authorize()
        db.rollback()  # Release read transaction before potentially long native work.
        if cancel_event is not None and cancel_event.is_set():
            raise RoadCalculationError('road_calculation_cancelled')
        calculate = compare_result_roads
        if payload.get('facility_algorithm'):
            from app.services.case_facility_comparison import compare_case_facilities
            if payload['facility_algorithm'] != current_versions()['scorer']:
                raise ValueError('facility_job_algorithm_unavailable')
            calculate = compare_case_facilities
        result = calculate(db, result_id=payload['result_id'], analysis_at=at,
            vehicle=vehicle, artifact_root=artifact_root, cancel_event=cancel_event,
            network_id=payload['network_id'])
        if payload.get('history_refresh_event_id'):
            result = {**result, 'history_refresh_event_id': payload['history_refresh_event_id']}
        authorize()
        if cancel_event is not None and cancel_event.is_set():
            raise RoadCalculationError('road_calculation_cancelled')
        has_calculation = isinstance(result.get('matrix'), dict) or isinstance(result.get('calculation'), dict)
        artifact = freeze_road_artifact(db, result) if has_calculation else None
        if cancel_event is not None and cancel_event.is_set():
            raise RoadCalculationError('road_calculation_cancelled')
        OutboxClaimService.finish(db, event_id=event_id, worker_id=token, status='completed',
                                 error=None if artifact else 'road_job_information_missing')
        db.commit()
        return {'event_id': event_id, 'status': 'completed', 'artifact': artifact,
                'outcome': 'calculated' if artifact else 'information_missing'}
    except Exception as error:
        db.rollback()
        if token is None:
            raise
        cancelled = isinstance(error, RoadCalculationError) and str(error) == 'road_calculation_cancelled'
        status = 'cancelled' if cancelled else ('retry' if attempts < 3 else 'failed')
        try:
            OutboxClaimService.finish(db, event_id=event_id, worker_id=token, status=status,
                error='road_job_cancelled' if cancelled else 'road_job_failed',
                available_at=datetime.now(timezone.utc) + timedelta(seconds=min(60, 2 ** attempts)))
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {'event_id': event_id, 'status': status}
    finally:
        db.info.clear()
        db.info.update(previous_info)
