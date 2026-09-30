"""Durable bounded profile scans shared by saved questions and query continuations.

Outbox is the execution record. Chunks are committed behind its lease and source
generation fence; retries never silently restart a completed page or count twice.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from time import monotonic
from uuid import uuid4
import re
import logging

from sqlalchemy import or_, update

from app.models.analysis_topic import AnalysisTopic, TopicRefreshChunk
from app.models.case import Case
from app.models.case_pipeline import OutboxEvent
from app.models.event import Event
from app.services.case_search_service import CaseSearchService
from app.services.intelligent_query_context import result_hash
from app.services.intelligent_query_tools import AggregateProfiles
from app.services.outbox_claim_service import OutboxClaimService, OutboxClaimLostError
from app.services.profile_aggregate import build_aggregate, merge_aggregates, present_aggregate
from app.services.topic_definitions import context_case_ids, resolve_definition, validate_source
from app.services.topic_revision_fence import current_revision

EVENT_TYPE = 'topic.aggregate.requested'
PAGE_SIZE = 100
ACTIVE = ('pending', 'retry', 'processing')


def _authority(db):
    from app.services.analysis_topic_service import _owner
    return _owner(db)


def create_aggregate_job(db, args, query_id=None, *, topic=None):
    """Caller owns commit. Query id and canonical arguments give idempotent admission."""
    args = AggregateProfiles.model_validate(args)
    user, scope = _authority(db)
    now = datetime.now(timezone.utc)
    if topic is not None:
        definition = resolve_definition(topic, now)
        arguments = definition['resolved_filters']
        identity = {'topic': topic.id, 'generation': topic.requested_generation}
    else:
        definition = None
        arguments = args.model_dump(mode='json', exclude={'page', 'page_size'})
        identity = {'query': query_id, 'owner': user.id, 'args': arguments,
                    **({'nonce': str(uuid4())} if query_id is None else {})}
    allowed = db.info['authorized_area_ids']
    area = arguments.get('operational_area_id')
    if area is not None and allowed is not None and area not in allowed:
        raise PermissionError('topic_area_forbidden')
    key = result_hash({'type': EVENT_TYPE, **identity})
    existing = db.query(OutboxEvent).filter_by(idempotency_key=key).first()
    if existing is not None:
        return _view(existing)
    if db.query(OutboxEvent.id).filter(OutboxEvent.event_type == EVENT_TYPE,
        OutboxEvent.aggregate_type == f'query_owner:{user.id}', OutboxEvent.status.in_(ACTIVE)).count() >= 20:
        raise ValueError('topic_capacity_reached')
    identifier = str(uuid4())
    payload = {'owner_id': user.id, 'scope_version': scope, 'query_id': query_id,
        'topic_id': topic.id if topic else None, 'definition': definition,
        'generation': topic.requested_generation if topic else None, 'arguments': arguments,
        # Wait for writers already in flight before fixing the initial epoch.
        # Later chunks only compare it; final publication takes this fence again.
        'data_revision': current_revision(db, lock=True), 'as_of': now.isoformat(),
        'phase': 'cases', 'cursor': 0, 'sequence': 0, 'total_cases': None,
        'scanned_cases': 0, 'event_cursor': 0, 'reference_cursor': 0,
        'ordinary_failures': 0, 'result': None}
    row = OutboxEvent(id=identifier, event_type=EVENT_TYPE,
        aggregate_type='analysis_topic' if topic else f'query_owner:{user.id}',
        aggregate_id=topic.id if topic else str(query_id or identifier),
        idempotency_key=key, payload=payload, status='pending', available_at=now)
    db.add(row)
    if topic is not None:
        topic.latest_job_id = identifier
    db.flush()
    return _view(row)


def _view(row):
    data = row.payload
    return {'id': row.id, 'status': row.status,
        'status_path': f'/api/analysis-topics/aggregations/{row.id}',
        'progress': {'phase': data['phase'], 'scanned_cases': data['scanned_cases'],
                     'total_cases': data['total_cases']}, 'as_of': data['as_of'],
        'scope_version': data['scope_version'], 'error': row.error,
        'definition_revision': (data.get('definition') or {}).get('revision')}


def _owned(db, identifier):
    user, scope = _authority(db)
    row = db.query(OutboxEvent).filter_by(id=identifier, event_type=EVENT_TYPE).populate_existing().first()
    if row is None or row.payload['owner_id'] != user.id:
        raise ValueError('topic_aggregate_not_found')
    if row.payload['scope_version'] != scope:
        raise PermissionError('topic_scope_changed')
    validate_source(db, (row.payload.get('definition') or {}).get('source_context'))
    return row


def read_aggregate_job(db, identifier):
    row = _owned(db, identifier)
    value = _view(row)
    value['result'] = None
    if row.status == 'completed' and row.payload.get('result'):
        from app.services.analysis_topic_service import validate_aggregate_access
        aggregate = row.payload['result']
        validate_aggregate_access(db, aggregate)
        value['result'] = present_aggregate(aggregate)
    return value


def cancel_aggregate_job(db, identifier):
    row = _owned(db, identifier)
    if row.status in ACTIVE:
        db.execute(update(OutboxEvent).where(OutboxEvent.id == identifier, OutboxEvent.status.in_(ACTIVE))
            .values(status='cancelled', worker_id=None, lease_until=None,
                    processed_at=datetime.now(timezone.utc)))
        if row.payload.get('topic_id'):
            db.execute(update(AnalysisTopic).where(AnalysisTopic.id == row.payload['topic_id'],
                AnalysisTopic.latest_job_id == identifier).values(refresh_state='cancelled',
                    next_refresh_at=datetime.now(timezone.utc) + timedelta(hours=6)))
        db.commit()
    return _view(_owned(db, identifier))


def _case_query(db, payload):
    args = AggregateProfiles.model_validate(payload['arguments'])
    query = CaseSearchService.filtered_query(db, **args.model_dump(exclude={'conditions', 'page', 'page_size'}))
    source = (payload.get('definition') or {}).get('source_context')
    if source and source['kind'] == 'facility' and 'facility_case_ids' not in payload:
        # Freeze once per durable generation. The source fence invalidates this
        # set when a link, reference, evidence object or source revision changes.
        payload['facility_case_ids'] = context_case_ids(db, source, start_date=args.start_date, end_date=args.end_date)
    ids = payload.get('facility_case_ids')
    if ids is not None:
        query = query.filter(Case.id.in_(ids), Case.occurred_time.is_not(None))
    return query


def _chunks(db, job_id, phase):
    return [row.payload for row in db.query(TopicRefreshChunk).filter_by(job_id=job_id, phase=phase)
            .order_by(TopicRefreshChunk.sequence)]


def _append(db, row, data, phase, payload):
    db.add(TopicRefreshChunk(id=str(uuid4()), job_id=row.id, phase=phase,
        sequence=data['sequence'], payload=payload))
    data['sequence'] += 1
    db.flush()  # Production sessions disable autoflush; later phases read this chunk.


def _aggregate(db, row, data):
    args = AggregateProfiles.model_validate(data['arguments'])
    empty = build_aggregate(db, args, case_ids=[], deadline=monotonic() + 10)
    return merge_aggregates(_chunks(db, row.id, 'cases'), empty=empty, total=data['total_cases'])


def _case_page(db, row, data, deadline):
    args = AggregateProfiles.model_validate(data['arguments'])
    query = _case_query(db, data)
    if data['total_cases'] is None:
        data['total_cases'] = query.count()
    ids = [case.id for case in query.filter(Case.id > data['cursor']).order_by(Case.id).limit(PAGE_SIZE)]
    if not ids:
        data['phase'] = 'references' if data.get('topic_id') else 'publish'
        return
    aggregate = build_aggregate(db, args, case_ids=ids, deadline=deadline)
    if not aggregate['coverage']['complete']:
        raise ValueError('topic_page_budget_exceeded')
    _append(db, row, data, 'cases', aggregate)
    data['cursor'] = ids[-1]
    data['scanned_cases'] += len(ids)


def _reference_page(db, row, data, deadline):
    from app.services.topic_projections import freeze_references
    chunks = db.query(TopicRefreshChunk).filter(TopicRefreshChunk.job_id == row.id,
        TopicRefreshChunk.phase == 'cases', TopicRefreshChunk.sequence >= data['reference_cursor'])
    chunk = chunks.order_by(TopicRefreshChunk.sequence).first()
    if chunk is None:
        data['phase'] = 'events'
        return
    refs = freeze_references(db, chunk.payload, AggregateProfiles.model_validate(data['arguments']),
                            deadline=deadline, include_context=False)
    _append(db, row, data, 'references', refs)
    data['reference_cursor'] = chunk.sequence + 1


def _event_page(db, row, data, deadline):
    from app.services.analysis_topic_service import _event_query
    args = AggregateProfiles.model_validate(data['arguments'])
    query = _event_query(db).filter(Event.id > data['event_cursor'])
    if args.operational_area_id is not None:
        query = query.filter(Event.operational_area_id == args.operational_area_id)
    if args.start_date:
        query = query.filter(Event.occurred_time >= args.start_date)
    if args.end_date:
        query = query.filter(Event.occurred_time < args.end_date)
    source = (data.get('definition') or {}).get('source_context')
    if source and source['kind'] == 'facility':
        query = query.filter(Event.related_asset_id == source['id'])
    elif source and source['kind'] == 'case':
        query = query.filter(Event.related_case_id == source['id'])
    events = query.order_by(Event.id).limit(PAGE_SIZE).all()
    if not events:
        data['phase'] = 'publish'
        return
    aggregate = _aggregate(db, row, data)
    member_ids = {item['case_id'] for item in aggregate['members']}
    sources = []
    for event in events:
        if monotonic() >= deadline:
            raise ValueError('topic_page_budget_exceeded')
        if event.related_case_id is not None and event.related_case_id not in member_ids:
            continue
        sources.append({'event_id': event.id, 'case_id': event.related_case_id,
            'source_sha256': result_hash({column.name: getattr(event, column.name) for column in Event.__table__.columns})})
    _append(db, row, data, 'events', {'sources': sources})
    data['event_cursor'] = events[-1].id


def _valid(db, row, data, *, lock=False):
    _owned(db, row.id)
    if current_revision(db, lock=lock) != data['data_revision']:
        logging.getLogger(__name__).warning('topic input generation changed during scan')
        return False
    if data.get('topic_id'):
        from app.services.analysis_topic_service import _owned as owned_topic
        topic = owned_topic(db, data['topic_id'])
        valid = (not topic.paused and topic.latest_job_id == row.id
            and topic.requested_generation == data['generation']
            and topic.definition_revision == data['definition']['revision'])
        if not valid:
            logging.getLogger(__name__).warning('topic definition or execution generation changed during scan')
        return valid
    return True


def _publish(db, row, data, deadline, token):
    aggregate = _aggregate(db, row, data)
    if not aggregate['coverage']['complete'] or _case_query(db, data).count() != data['total_cases']:
        raise ValueError('topic_scan_incomplete')
    if not data.get('topic_id'):
        data['result'] = aggregate
        return {'status': 'completed'}
    from app.services.analysis_topic_service import publish_snapshot
    from app.services.topic_projections import freeze_references
    references = freeze_references(db, {**aggregate, 'members': []},
        AggregateProfiles.model_validate(data['arguments']), deadline=deadline)
    for chunk in _chunks(db, row.id, 'references'):
        for key in ('case_results', 'roads'):
            references[key].extend(chunk[key])
    sources = [source for chunk in _chunks(db, row.id, 'events') for source in chunk['sources']]
    events = {'independent_event_count': sum(source['case_id'] is None for source in sources),
        'case_linked_event_count': sum(source['case_id'] is not None for source in sources),
        'source_manifest': sources,
        'boundary': '独立事件和已关联案件事件分开，不与案件计数相加；不按文本相似去重。'}
    payload = {'definition': data['definition'], 'aggregate': aggregate, 'events': events, 'references': references}
    source = data['definition'].get('source_context')
    if source and source['kind'] == 'case':
        from fastapi.encoders import jsonable_encoder
        from app.services.case_workspace_service import CaseWorkspaceService
        workspace = CaseWorkspaceService.read(db, source['id'])
        payload['case_context'] = jsonable_encoder({key: workspace[key]
            for key in ('case', 'profile', 'result', 'pipeline', 'links', 'boundary')})
        # Keep the business gaps beside the saved profile, without copying the
        # compatibility workspace's unrelated report/meeting references.
        detail = workspace['detail_profile']['data']
        payload['case_context']['detail_profile'] = jsonable_encoder({'status': 'ready',
            'data': {key: detail[key] for key in ('quality', 'quality_gaps', 'boundary')}})
    if source and source['kind'] == 'facility':
        from fastapi.encoders import jsonable_encoder
        from app.services.facility_summary_service import read_dossier
        args = AggregateProfiles.model_validate(data['arguments'])
        payload['facility_context'] = jsonable_encoder(read_dossier(db, source['id'], start_date=args.start_date, end_date=args.end_date))
        from app.services.facility_material_service import freeze_dossier_sources
        payload['facility_sources'] = freeze_dossier_sources(db, payload['facility_context'])
        payload['population_boundary'] = '案件统计只包含有明确记录关联的案件；空间邻近与系统候选保留在设施资料分类中，不合并成涉案事实。'
    def publication_fence():
        # Match cancellation/definition edits: execution row before topic row.
        # All potentially long evidence reads happen before these write locks.
        owned = db.execute(update(OutboxEvent).where(OutboxEvent.id == row.id,
            OutboxEvent.worker_id == token, OutboxEvent.status == 'processing')
            .values(worker_id=token).execution_options(synchronize_session=False))
        if not owned.rowcount:
            raise OutboxClaimLostError('outbox_claim_lost')
        if not _valid(db, row, data, lock=True):
            raise ValueError('topic_source_changed')

    return publish_snapshot(db, data['topic_id'], payload, data_revision=data['data_revision'],
                            publication_fence=publication_fence)


def process_aggregate_job(db, identifier, *, max_pages=8):
    row = _owned(db, identifier)
    row, claimed = OutboxClaimService.claim(db, identifier, expected_type=EVENT_TYPE)
    if not claimed:
        return {'id': identifier, 'status': row.status, 'claimed': False}
    token = row.worker_id
    data = deepcopy(row.payload)
    deadline = monotonic() + 60
    try:
        if not _valid(db, row, data):
            raise ValueError('topic_source_changed')
        outcome = None
        for _ in range(max_pages):
            phase = data['phase']
            if phase == 'publish':
                if not _valid(db, row, data):
                    raise ValueError('topic_source_changed')
                outcome = _publish(db, row, data, deadline, token)
                break
            {'cases': _case_page, 'references': _reference_page, 'events': _event_page}[phase](db, row, data, deadline)
            if monotonic() >= deadline - 1:
                break
        if not _valid(db, row, data, lock=True):
            raise ValueError('topic_source_changed')
        changed = db.execute(update(OutboxEvent).where(OutboxEvent.id == identifier,
            OutboxEvent.worker_id == token, OutboxEvent.status == 'processing')
            .values(payload=data).execution_options(synchronize_session=False))
        if not changed.rowcount:
            raise OutboxClaimLostError('outbox_claim_lost')
        OutboxClaimService.finish(db, event_id=identifier, worker_id=token,
            status='completed' if outcome else 'pending', available_at=datetime.now(timezone.utc))
        db.commit()
        return {'id': identifier, **(outcome or {'status': 'running'}),
                'scanned_cases': data['scanned_cases'], 'total_cases': data['total_cases']}
    except (ValueError, PermissionError, OutboxClaimLostError) as error:
        db.rollback()
        current = db.query(OutboxEvent).filter_by(id=identifier).populate_existing().one()
        if current.status != 'processing' or current.worker_id != token:
            return {'id': identifier, 'status': 'superseded'}
        source_changed = str(error) == 'topic_source_changed'
        error_code = str(error) if re.fullmatch(r'[a-z_]{1,80}', str(error)) else 'topic_refresh_unavailable'
        status = 'superseded' if source_changed else 'cancelled' if isinstance(error, PermissionError) else 'retry'
        failures = current.payload.get('ordinary_failures', 0) + 1
        if status == 'retry' and failures >= 3:
            status = 'failed'
        db.execute(update(OutboxEvent).where(OutboxEvent.id == identifier).values(
            payload={**current.payload, 'ordinary_failures': failures}))
        OutboxClaimService.finish(db, event_id=identifier, worker_id=token, status=status,
            error=error_code,
            available_at=datetime.now(timezone.utc) + timedelta(seconds=10))
        if data.get('topic_id'):
            topic = db.query(AnalysisTopic).filter_by(id=data['topic_id']).populate_existing().first()
            if topic and topic.latest_job_id == identifier:
                topic.refresh_state = 'queued' if source_changed and not topic.paused else status
                if status != 'retry':
                    topic.latest_job_id = None
                    topic.requested_generation += 1
                    topic.next_refresh_at = datetime.now(timezone.utc) if source_changed else datetime.now(timezone.utc) + timedelta(hours=6)
        db.commit()
        return {'id': identifier, 'status': status, 'error': error_code}


def process_next_aggregate_job(db):
    now = datetime.now(timezone.utc)
    row = db.query(OutboxEvent).filter(OutboxEvent.event_type == EVENT_TYPE,
        or_(OutboxEvent.status.in_(('pending', 'retry')) & (OutboxEvent.available_at <= now),
            (OutboxEvent.status == 'processing') & (OutboxEvent.lease_until <= now)))
    row = row.order_by(OutboxEvent.available_at, OutboxEvent.id).first()
    if row is None:
        return None
    owner_id, identifier = row.payload['owner_id'], row.id
    db.rollback()
    db.info['principal_user_id'] = owner_id
    try:
        return process_aggregate_job(db, identifier)
    except PermissionError:
        db.rollback()
        db.execute(update(OutboxEvent).where(OutboxEvent.id == identifier, OutboxEvent.status.in_(ACTIVE))
            .values(status='cancelled', error='topic_access_changed', worker_id=None, lease_until=None))
        db.commit()
        return {'id': identifier, 'status': 'cancelled'}
