"""Admin metadata and one explicit retry of failed derived work only.

This is not a generic Outbox replay API. It cannot execute approved mutations,
revive cancellation, run a model inline, or borrow an administrator's road scope.
"""
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.models.case import Case
from app.models.case_pipeline import CasePipelineState, OutboxEvent
from app.models.user import AuditLog
from app.services.intelligent_query_tasks import _identity
from app.services.case_result_service import CaseResultService

KINDS = {'case.analysis.requested': '案件画像', 'case.roads.requested': '道路分析准备',
         'case.roads.compare': '道路与设施比较', 'case.history.index.retry': '历史检索索引'}
STATES = {'pending', 'retry', 'processing', 'waiting_dependency', 'failed'}
ACTION = 'derived_task.explicit_retry'


def _admin(db):
    user = _identity(db)
    if user.role != 'admin':
        raise PermissionError('derived_operations_admin_required')
    return user


def _source(db, event):
    if event.event_type not in KINDS:
        raise ValueError('derived_task_type_not_allowed')
    if event.event_type in {'case.analysis.requested', 'case.history.index.retry'}:
        case = db.query(Case).filter_by(id=int(event.aggregate_id)).first()
        if case is None:
            raise LookupError('derived_task_unavailable')
        return case
    return CaseResultService.read(db, event.payload['result_id'])


def _current(db, event, source):
    if event.event_type == 'case.history.index.retry':
        from app.services.case_history_index_debt import current_input_stamp
        return current_input_stamp(db, source)['input_hash'] == event.payload.get('input_hash')
    if event.event_type == 'case.analysis.requested':
        from app.services.case_pipeline_service import CasePipelineService, CASE_PROFILE_SCHEMA_VERSION
        from app.services.case_local_semantic_model import resolve_model_plan
        from app.services.case_source_service import CaseSourceService
        state = db.query(CasePipelineState).filter_by(case_id=source.id).first()
        revision = CaseSourceService.latest_revision(db, source.id)
        return bool(state and state.event_id == event.id
            and CasePipelineService.source_hash(db, source) == event.payload.get('source_hash')
            and (revision.id if revision else None) == event.payload.get('source_revision_id')
            and event.payload.get('schema_version') == CASE_PROFILE_SCHEMA_VERSION
            and event.payload.get('dictionary_version') == resolve_model_plan(db).version)
    return _road_current(db, event)


def _road_current(db, event):
    """The directory and retry use the same original-actor input fence."""
    from app.services.case_road_jobs import _identity as road_identity, JOB_VERSION
    from app.services.road_access_policy import VehicleAssumption
    from app.services.road_network_service import resolve_network
    payload, original = event.payload, dict(db.info)
    try:
        authority = payload if event.event_type == 'case.roads.compare' else payload['authority']
        road_identity(db, authority['user_id'], authority['scope'])
        source = CaseResultService.read(db, payload['result_id'])
        latest = CaseResultService.latest_base(db, source['content']['case_id'])
        if latest['id'] != source['id'] or latest['freshness'] != 'current':
            return False
        if event.event_type != 'case.roads.compare':
            return True
        binding = resolve_network(db, payload['network_id'],
            analysis_at=datetime.fromisoformat(payload['analysis_at']),
            vehicle=VehicleAssumption.model_validate(payload['vehicle']))
        if (payload.get('job_version') != JOB_VERSION
                or source['content_sha256'] != payload.get('content_sha256')
                or binding.graph_sha256 != payload['graph_sha256']
                or binding.policy_revision != payload['policy_revision']):
            return False
        if payload.get('facility_algorithm'):
            from app.services.facility_analysis_versions import current_versions
            from app.services.facility_dependency_guard import require_dependencies, VERSION
            from app.services.facility_job_checkpoint import check_checkpoint
            scope = db.info['authorized_area_ids']
            dependencies = payload.get('dependencies') or {}
            if (payload.get('facility_versions') != current_versions()
                    or payload['scope'] != (None if scope is None else sorted(scope))
                    or dependencies.get('schema') != VERSION
                    or dependencies.get('sha256') != payload.get('dependency_sha256')
                    or dependencies.get('user_id') != authority['user_id']
                    or dependencies.get('scope') != payload['scope']):
                return False
            require_dependencies(db, dependencies)
            if payload.get('facility_checkpoint'):
                checkpoint = check_checkpoint(payload['facility_checkpoint'])
                if checkpoint['dependencies'] != dependencies:
                    return False
        return True
    finally:
        db.info.clear()
        db.info.update(original)


def directory(db, *, page=1, page_size=20, status=None):
    _admin(db)
    if not 1 <= page_size <= 100 or page < 1 or status is not None and status not in STATES:
        raise ValueError('derived_task_filter_invalid')
    counts = {key: 0 for key in sorted(STATES)}
    total, items, oldest = 0, [], None
    now = datetime.now(timezone.utc)
    with db.no_autoflush:
        rows = db.query(OutboxEvent).filter(OutboxEvent.event_type.in_(KINDS),
            OutboxEvent.status.in_(STATES)).order_by(OutboxEvent.created_at, OutboxEvent.id).yield_per(100)
        for event in rows:
            try:
                source = _source(db, event)
            except (PermissionError, ValueError, LookupError, KeyError):
                continue  # Authorization precedes counts and pagination.
            counts[event.status] += 1
            if event.status in {'pending', 'retry', 'processing'}:
                created = event.created_at.replace(tzinfo=timezone.utc) if event.created_at.tzinfo is None else event.created_at
                oldest = max(oldest or 0, max(0, int((now - created).total_seconds())))
            if status and event.status != status:
                continue
            if (page - 1) * page_size <= total < page * page_size:
                try:
                    current = _current(db, event, source)
                except (PermissionError, ValueError, LookupError):
                    current = False
                items.append({'id': event.id, 'kind': event.event_type, 'label': KINDS[event.event_type],
                    'status': event.status, 'attempts': event.attempts, 'created_at': event.created_at,
                    'available_at': event.available_at, 'retryable': event.status == 'failed' and current,
                    'source_state': 'current' if current else 'outdated_or_unavailable'})
            total += 1
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size, 'counts': counts,
            'oldest_wait_seconds': oldest, 'worker_capacity': 'deployment_configuration_not_measured',
            'boundary': '仅当前授权的画像、检索索引和道路派生任务；不含正式写入、审批和模型实验。重试不保证成功，不改变原案件。'}


def _receipt(db, event_id, user_id, request_id, expected_attempts):
    row = db.query(AuditLog).filter_by(action=ACTION, user_id=user_id, request_id=request_id).first()
    if row is None:
        return None
    if row.detail != {'event_id': event_id, 'expected_attempts': expected_attempts}:
        raise ValueError('derived_retry_request_conflict')
    return {'event_id': event_id, 'accepted': True, 'replayed': True}


def retry_failed(db, event_id, *, expected_attempts, request_id):
    admin = _admin(db)
    event = db.query(OutboxEvent).filter_by(id=event_id).populate_existing().first()
    if event is None:
        raise LookupError('derived_task_unavailable')
    source = _source(db, event)
    receipt = _receipt(db, event_id, admin.id, request_id, expected_attempts)
    if receipt:
        return receipt
    if event.status != 'failed' or event.attempts != expected_attempts:
        raise ValueError('derived_task_state_changed')
    if not _current(db, event, source):
        raise ValueError('derived_task_source_outdated')
    now = datetime.now(timezone.utc)
    changed = db.execute(update(OutboxEvent).where(OutboxEvent.id == event_id,
        OutboxEvent.status == 'failed', OutboxEvent.attempts == expected_attempts).values(
            status='retry', error=None, available_at=now, processed_at=None,
            claimed_at=None, lease_until=None, worker_id=None,
            payload={**event.payload, 'ordinary_failures': 0}).execution_options(synchronize_session=False)).rowcount
    if changed != 1:
        db.rollback()
        receipt = _receipt(db, event_id, admin.id, request_id, expected_attempts)
        if receipt:
            return receipt
        raise ValueError('derived_task_state_changed')
    db.add(AuditLog(user_id=admin.id, username=admin.username, action=ACTION, request_id=request_id,
                   detail={'event_id': event_id, 'expected_attempts': expected_attempts}))
    try:
        # The partial unique audit key binds one request to one task/attempt.
        # A conflicting request rolls back the preceding state CAS as well.
        db.commit()
    except IntegrityError:
        db.rollback()
        receipt = _receipt(db, event_id, admin.id, request_id, expected_attempts)
        if receipt:
            return receipt
        raise
    return {'event_id': event_id, 'accepted': True, 'replayed': False}
