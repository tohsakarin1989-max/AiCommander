"""Background replay of frozen road datasets; no raw routing output in API traces."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.case_pipeline import OutboxEvent
from app.models.governance import EvaluationRun
from app.models.user import User
from app.services.case_road_jobs import _identity
from app.services.coverage_road_jobs import DurableCancellation
from app.services.frozen_insight_inputs import checksum
from app.services.frozen_road_dataset import read_dataset
from app.services.frozen_road_inputs import replay_road_inputs
from app.services.outbox_claim_service import OutboxClaimService, OutboxClaimLostError, OUTBOX_LEASE_SECONDS
from app.services.vehicle_router import RoadCalculationError

EVENT_TYPE = 'evaluation.roads.replay'
SCHEMA = 'road-evaluation-run-4.5-1'


def _authorize(db, payload):
    ceiling = payload['scope']
    current = db.info.get('authorized_area_ids')
    if current is not None:
        ceiling = sorted(set(current) if ceiling is None else set(current).intersection(ceiling))
    _identity(db, payload['user_id'], ceiling)
    if db.scalar(select(User.role).where(User.id == payload['user_id'], User.is_active.is_(True))) != 'admin':
        raise PermissionError('road_evaluation_admin_required')
    dataset = read_dataset(db, payload['dataset_id'])
    if dataset.checksum != payload['dataset_checksum']:
        raise ValueError('road_evaluation_dataset_changed')
    return dataset


def enqueue(db, dataset_id, *, request_id):
    if 'authorized_area_ids' not in db.info or not isinstance(request_id, str) or not 1 <= len(request_id) <= 64:
        raise ValueError('road_evaluation_request_invalid')
    dataset = read_dataset(db, dataset_id)
    scope = db.info['authorized_area_ids']
    payload = {'schema': SCHEMA, 'user_id': db.info.get('principal_user_id'),
        'scope': None if scope is None else sorted(scope), 'dataset_id': dataset.id,
        'dataset_checksum': dataset.checksum, 'request_id': request_id}
    _authorize(db, payload)
    key = checksum({'type': EVENT_TYPE, 'user_id': payload['user_id'], 'request_id': request_id})
    dialect = db.get_bind().dialect.name
    if dialect not in ('sqlite', 'postgresql'):
        raise ValueError('road_evaluation_database_unsupported')
    insert = sqlite_insert if dialect == 'sqlite' else pg_insert
    identifier = db.scalar(insert(OutboxEvent).values(id=str(uuid4()), event_type=EVENT_TYPE,
        aggregate_type='evaluation_dataset', aggregate_id=str(dataset.id), payload=payload,
        idempotency_key=key, status='pending', attempts=0)
        .on_conflict_do_nothing(index_elements=['idempotency_key']).returning(OutboxEvent.id))
    created = identifier is not None
    if identifier is None:
        existing = db.query(OutboxEvent).filter_by(idempotency_key=key).one()
        if existing.payload != payload:
            raise ValueError('road_evaluation_request_conflict')
        identifier = existing.id
    return {'event_id': identifier, 'created': created}


def process(db, event_id, *, artifact_root, cancel_event=None):
    if db.new or db.dirty or db.deleted:
        raise ValueError('road_evaluation_requires_clean_session')
    previous_info, token = dict(db.info), None
    try:
        scheduled = db.get(OutboxEvent, event_id, populate_existing=True)
        if scheduled and scheduled.status in ('pending', 'retry') and OutboxClaimService._aware(scheduled.available_at) > datetime.now(timezone.utc):
            return {'event_id': event_id, 'status': scheduled.status, 'claimed': False}
        event, claimed = OutboxClaimService.claim(db, event_id, expected_type=EVENT_TYPE)
        if not claimed:
            return {'event_id': event_id, 'status': event.status, 'claimed': False}
        token, payload = event.worker_id, deepcopy(event.payload)
        if payload.get('schema') != SCHEMA:
            raise ValueError('road_evaluation_version_changed')
        dataset = _authorize(db, payload)
        entries = deepcopy(dataset.manifest['entries'])
        db.rollback()
        cancellation = DurableCancellation(sessionmaker(bind=db.get_bind()), event_id, token,
                                           cancel_event, event_type=EVENT_TYPE)
        records = []
        for envelope in entries:
            if cancellation.is_set():
                raise RoadCalculationError('road_calculation_cancelled')
            # Renew before each bounded native invocation, retaining the same fence.
            renewed = db.query(OutboxEvent).filter_by(id=event_id, status='processing', worker_id=token).update(
                {OutboxEvent.lease_until: datetime.now(timezone.utc) + timedelta(seconds=OUTBOX_LEASE_SECONDS)},
                synchronize_session=False)
            if renewed != 1:
                raise OutboxClaimLostError('outbox_claim_lost')
            db.commit()
            _authorize(db, payload)
            record = {'artifact_id': envelope['payload']['artifact_id'], 'input_checksum': envelope['checksum']}
            try:
                value = replay_road_inputs(db, envelope, artifact_root=artifact_root, cancel_event=cancellation)
                record.update(status='completed', result_checksum=value['result_checksum'])
            except (RoadCalculationError, OSError, RuntimeError) as error:
                if cancellation.is_set() or str(error) == 'road_calculation_cancelled':
                    raise RoadCalculationError('road_calculation_cancelled') from error
                record.update(status='failed', failure_reason='road_replay_unavailable')
            records.append(record)
        _authorize(db, payload)
        if cancellation.is_set():
            raise RoadCalculationError('road_calculation_cancelled')
        failures = sum(row['status'] == 'failed' for row in records)
        metrics = {'sample_count': len(records), 'failed_sample_count': failures,
                   'unlabeled_sample_count': len(records), 'accuracy': None}
        trace = {'dataset_checksum': payload['dataset_checksum'], 'records': records}
        algorithm = {'evaluation_schema': SCHEMA,
            'networks': [entry['payload']['network'] for entry in entries]}
        algorithm['result_checksum'] = checksum({'metrics': metrics, 'trace': trace, 'algorithm': deepcopy(algorithm)})
        db.add(EvaluationRun(id=event_id, dataset_id=payload['dataset_id'], algorithm_manifest=algorithm,
            scope_policy_version='current-case-road-authorization-4.5-1',
            status='partial_failure' if failures else 'completed', metrics=metrics, trace_manifest=trace,
            completed_at=datetime.now(timezone.utc)))
        OutboxClaimService.finish(db, event_id=event_id, worker_id=token, status='completed')
        db.commit()
        return {'event_id': event_id, 'status': 'completed', 'failed_sample_count': failures}
    except Exception as error:
        db.rollback()
        if token is None:
            raise
        current = db.get(OutboxEvent, event_id, populate_existing=True)
        if current is None or current.status != 'processing' or current.worker_id != token:
            return {'event_id': event_id, 'status': current.status if current else 'unavailable', 'claimed': False}
        cancelled = isinstance(error, RoadCalculationError) and str(error) == 'road_calculation_cancelled'
        OutboxClaimService.finish(db, event_id=event_id, worker_id=token,
            status='cancelled' if cancelled else 'failed', error='road_evaluation_cancelled' if cancelled else 'road_evaluation_unavailable')
        db.commit()
        return {'event_id': event_id, 'status': 'cancelled' if cancelled else 'failed'}
    finally:
        db.info.clear()
        db.info.update(previous_info)


def read_run(db, run_id):
    event = db.get(OutboxEvent, run_id, populate_existing=True)
    if event is None or event.event_type != EVENT_TYPE or event.payload.get('user_id') != db.info.get('principal_user_id'):
        raise PermissionError('road_evaluation_unavailable')
    _authorize(db, event.payload)
    run = db.get(EvaluationRun, run_id, populate_existing=True)
    if run is not None:
        algorithm = deepcopy(run.algorithm_manifest)
        expected = algorithm.pop('result_checksum', None)
        if (run.dataset_id != event.payload['dataset_id'] or algorithm.get('evaluation_schema') != SCHEMA
                or run.trace_manifest.get('dataset_checksum') != event.payload['dataset_checksum']
                or expected != checksum({'metrics': run.metrics, 'trace': run.trace_manifest, 'algorithm': algorithm})):
            raise ValueError('road_evaluation_result_invalid')
    return {'event_id': run_id, 'status': event.status,
            'result_status': run.status if run else None, 'metrics': run.metrics if run else None,
            'trace': run.trace_manifest if run else None, 'execution_task_created': False}


def cancel(db, event_id):
    # Allow the submitting active administrator to stop work even after source revocation.
    actor = db.info.get('principal_user_id')
    if db.scalar(select(User.role).where(User.id == actor, User.is_active.is_(True))) != 'admin':
        raise PermissionError('road_evaluation_unavailable')
    event = db.get(OutboxEvent, event_id, populate_existing=True)
    if event is None or event.event_type != EVENT_TYPE or event.payload.get('user_id') != actor:
        raise PermissionError('road_evaluation_unavailable')
    db.query(OutboxEvent).filter(OutboxEvent.id == event_id, OutboxEvent.status.in_(('pending', 'retry', 'processing'))).update({
        OutboxEvent.status: 'cancelled', OutboxEvent.worker_id: None, OutboxEvent.claimed_at: None,
        OutboxEvent.lease_until: None, OutboxEvent.processed_at: datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit()
    return {'event_id': event_id, 'status': db.get(OutboxEvent, event_id, populate_existing=True).status}


def list_jobs(db, *, page=1, page_size=20):
    """Owner-only task metadata, including cancellable jobs after source revocation."""
    if not 1 <= page <= 100000 or not 1 <= page_size <= 100:
        raise ValueError('road_evaluation_page_invalid')
    actor = db.info.get('principal_user_id')
    if db.scalar(select(User.role).where(User.id == actor, User.is_active.is_(True))) != 'admin':
        raise PermissionError('road_evaluation_unavailable')
    query = db.query(OutboxEvent).filter(OutboxEvent.event_type == EVENT_TYPE,
        OutboxEvent.payload['user_id'].as_integer() == actor)
    total = query.count()
    rows = query.order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc()).offset(
        (page - 1) * page_size).limit(page_size).all()
    items = []
    for row in rows:
        previous_info = dict(db.info)
        try:
            _authorize(db, row.payload)
            available = True
        except (PermissionError, ValueError):
            available = False
        finally:
            db.info.clear()
            db.info.update(previous_info)
        items.append({'event_id': row.id, 'status': row.status, 'created_at': row.created_at,
            'source_available': available,
            'dataset_id': row.payload['dataset_id'] if available else None})
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}
