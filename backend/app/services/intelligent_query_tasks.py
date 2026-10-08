"""Durable query lifecycle on existing AgentRun/Event tables.

Each mutator owns its transaction; callers must use a dedicated session. Queue
dispatch is separate so a broker outage cannot erase a created query. Routes
are opt-in. Read scope is refreshed from the current user on each access.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import update, select

from app.agent_runtime.service import AgentRunService, FINAL_RUN_STATUSES
from app.database import bind_principal_scope
from app.models.agent_run import AgentRun
from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshot
from app.models.user import User
from app.models.query_scope_revision import QueryScopeRevision
from app.services.intelligent_query_context import freeze_context, result_hash
from app.services.intelligent_query_roads import validate_road_query_evidence
from app.services.intelligent_query_history import validate_history_query_evidence
from app.services.intelligent_query_initial_context import freeze_initial_context, require_source_case_version
from app.services.intelligent_query_business import validate_business_query_evidence
from app.services.intelligent_query_presets import QueryPreset
from app.agent_runtime.execution_contract import TaskEnvelope
from app.services.business_answer import validate_answer


TASK_TYPE = 'intelligent_query'


def _identity(db):
    uid = db.info.get('principal_user_id')
    if uid is None:
        raise PermissionError('query_auth_required')
    user = db.query(User).filter_by(id=uid, is_active=True).populate_existing().first()
    if user is None:
        raise PermissionError('query_auth_required')
    bind_principal_scope(db, SimpleNamespace(user_id=user.id, role=user.role), method='GET')
    return user


def _stamp(db, user, contract='membership-v1'):
    # Until a central authorization revision exists, fingerprint membership.
    # This also catches a case/asset moved out of scope without changing grants.
    digest = hashlib.sha256(json.dumps({
        'user': user.id, 'role': user.role, 'session_version': user.session_version,
        'areas': db.info['authorized_area_ids'],
    }, sort_keys=True).encode())
    if contract == 'membership-v2':
        revision = db.scalar(select(QueryScopeRevision.revision).where(QueryScopeRevision.id == 1))
        if revision is None:
            raise PermissionError('query_scope_revision_unavailable')
        digest.update(f'scope-revision-v1:{revision}'.encode())
        return digest.hexdigest()
    for model in (Case, JurisdictionAsset, MapSnapshot):
        digest.update(model.__tablename__.encode())
        for row in db.query(model.id, model.operational_area_id).order_by(model.id).yield_per(1000):
            digest.update(json.dumps(list(row), separators=(',', ':')).encode())
    return digest.hexdigest()


def _current_stamp(db, user, row):
    contract = (row.input_payload or {}).get('scope_contract', 'membership-v1')
    return _stamp(db, user, contract)


def _owned(db, run_id):
    user = _identity(db)
    row = db.query(AgentRun).filter_by(id=run_id, task_type=TASK_TYPE, created_by=user.id).populate_existing().first()
    if row is None:
        raise ValueError('query_not_found')
    return row, user


def _event(db, row, kind):
    AgentRunService.append_event(db, row, event_type=kind, status=row.status,
                                actor_user_id=db.info['principal_user_id'])


def _view(row):
    return {'id': row.id, 'status': row.status, 'query': row.query,
            'created_at': row.created_at, 'completed_at': row.completed_at,
            'result': row.result_summary, 'result_kind': 'historical_query_snapshot',
            'preset': (row.input_payload or {}).get('preset'),
            'followup_context': (row.input_payload or {}).get('followup_context'),
            'initial_context': (row.input_payload or {}).get('initial_context'),
            'question_type': (row.input_payload or {}).get('question_type'),
            'source_context': (row.input_payload or {}).get('source_context'),
            'condition_changes': (row.input_payload or {}).get('condition_changes', []),
            'clarification': (row.runtime_state or {}).get('clarification') if row.status == 'waiting_clarification' else None}


def _validate_context(db, row, user):
    if (row.input_payload or {}).get('question_type'):
        from app.services.business_query_lifecycle import validate_context
        return validate_context(db, row, user)
    context = (row.input_payload or {}).get('followup_context')
    initial = (row.input_payload or {}).get('initial_context')
    if context is not None and initial is not None:
        raise PermissionError('query_context_changed')
    require_source_case_version(db, context or initial)
    from app.services.topic_query_bridge import validate_topic_source
    validate_topic_source(db, (context or initial or {}).get('topic_source'))
    if context:
        parent = db.query(AgentRun).filter_by(id=context['parent_query_id'], task_type=TASK_TYPE,
            created_by=user.id).populate_existing().first()
        if (parent is None or parent.data_version != _current_stamp(db, user, parent)
                or context['parent_scope_version'] != parent.data_version
                or parent.status not in {'completed', 'degraded'}
                or result_hash(parent.result_summary) != context['parent_result_hash']):
            raise PermissionError('query_context_changed')
        validate_road_query_evidence(db, parent.result_summary)
        validate_history_query_evidence(db, parent.result_summary)
        validate_business_query_evidence(db, parent.result_summary)
    return context


def create_query(db, question, parent_query_id=None, initial_context=None, preset=None,
                 question_type=None, source_context=None, *, topic_source=None):
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
        raise ValueError('invalid_query_question')
    user = _identity(db)
    if parent_query_id is not None and initial_context is not None:
        raise ValueError('query_context_conflict')
    if parent_query_id and question_type is None:
        parent, _ = _owned(db, parent_query_id)
        question_type = (parent.input_payload or {}).get('question_type')
    if question_type is not None:
        if initial_context is not None or preset is not None or topic_source is not None:
            raise ValueError('query_context_conflict')
        from app.services.business_query_lifecycle import create
        return create(db, question, question_type, source_context, parent_query_id)
    if source_context is not None:
        raise ValueError('business_answer_question_type_required')
    selected_preset = QueryPreset.model_validate(preset).model_dump(mode='json') if preset is not None else None
    if selected_preset and initial_context is None and parent_query_id is None:
        case_id = selected_preset['arguments'].get('case_id')
        if case_id is not None:
            initial_context = {'source_case_id': case_id}
    if topic_source is not None:
        from app.services.topic_query_bridge import validate_topic_source
        from app.services.intelligent_query_context import empty_conditions, remember
        from app.services.intelligent_query_tools import ProfileFilters
        validate_topic_source(db, topic_source)
        filters = ProfileFilters.model_validate((initial_context or {})['filters']).model_dump(mode='json', exclude_none=True)
        initial = {'schema_version': 'topic-query-context-5.3-1', 'source_case': None,
                   'conditions': remember(empty_conditions(), 'aggregate_case_profiles', filters),
                   'topic_source': topic_source, 'boundary': '继承专题条件；重新读取授权内数据，不把旧统计当作本轮证据。'}
    else:
        initial = freeze_initial_context(db, initial_context) if initial_context is not None else None
    context = None
    if parent_query_id is not None:
        parent, user = _owned(db, parent_query_id)
        if parent.data_version != _current_stamp(db, user, parent):
            raise PermissionError('query_scope_changed')
        _validate_context(db, parent, user)
        validate_road_query_evidence(db, parent.result_summary)
        validate_history_query_evidence(db, parent.result_summary)
        validate_business_query_evidence(db, parent.result_summary)
        context = freeze_context(parent)
    # Serialize each owner's admission before checking pending capacity. A no-op
    # UPDATE obtains the same lock on SQLite and PostgreSQL without broker I/O.
    db.execute(update(User).where(User.id == user.id).values(id=User.id))
    pending = db.query(AgentRun.id).filter(AgentRun.task_type == TASK_TYPE,
        AgentRun.created_by == user.id, AgentRun.status.in_(['queued', 'running', 'waiting_clarification'])).count()
    if pending >= 4:
        db.rollback()
        raise ValueError('query_capacity_reached')
    run_id = str(uuid4())
    stamp = _stamp(db, user, 'membership-v2')
    bindings = {key: value for key, value in (context or initial or {}).items()
                if key in {'source_case', 'topic_source', 'parent_query_id', 'parent_result_hash'}}
    envelope = TaskEnvelope(run_id, 'deterministic_preset' if selected_preset else 'intranet_model', user.id, stamp,
                            source_bindings=bindings).public()
    if selected_preset:
        from app.services.intelligent_query_context import inherit, empty_conditions
        from app.services.intelligent_query_presets import PRESETS
        inherit(PRESETS[selected_preset['name']], selected_preset['arguments'],
                (context or initial or {}).get('conditions', empty_conditions()), question=question)
    row = AgentRun(id=run_id, task_type=TASK_TYPE, query=question.strip(),
        case_ids=[], asset_ids=[], mode='shadow', status='queued', created_by=user.id,
        data_version=stamp, input_payload={'scope_contract': 'membership-v2', 'task_envelope': envelope,
            **({'preset': selected_preset} if selected_preset else {}),
            **({'followup_context': context} if context else {}),
            **({'initial_context': initial} if initial else {})},
        runtime_state={}, result_summary={})
    db.add(row)
    db.flush()
    _event(db, row, 'query_created')
    db.commit()
    return _view(row)


def read_query(db, run_id):
    row, user = _owned(db, run_id)
    if row.data_version != _current_stamp(db, user, row):
        raise PermissionError('query_scope_changed')
    _validate_context(db, row, user)
    validate_road_query_evidence(db, row.result_summary)
    validate_history_query_evidence(db, row.result_summary)
    validate_business_query_evidence(db, row.result_summary)
    validate_answer(db, row.result_summary)
    if row.status == 'waiting_clarification':
        from app.services.business_query_lifecycle import expire_waiting
        expire_waiting(db, row)
    return _view(row)


def clarify_query(db, run_id, reply):
    from app.services.business_query_lifecycle import clarify
    return clarify(db, run_id, reply)


def cancel_query(db, run_id):
    row, _ = _owned(db, run_id)
    changed = db.execute(update(AgentRun).where(AgentRun.id == row.id,
        AgentRun.status.notin_(FINAL_RUN_STATUSES)).values(
            status='cancelled', completed_at=datetime.now(timezone.utc)))
    if changed.rowcount:
        db.refresh(row)
        _event(db, row, 'query_cancelled')
    db.commit()
    # Cancellation remains possible after scope revocation, but never returns
    # cached results or question text that could contain revoked information.
    return {'id': row.id, 'status': row.status}


def claim_query(db, run_id):
    row, user = _owned(db, run_id)
    if row.data_version != _current_stamp(db, user, row):
        raise PermissionError('query_scope_changed')
    _validate_context(db, row, user)
    if row.status == 'queued' and (row.input_payload or {}).get('question_type'):
        from app.services.business_query_lifecycle import refresh_for_execution
        refresh_for_execution(db, row)
        db.flush()
    now = datetime.now(timezone.utc)
    attempt = row.attempt_count + 1
    changed = db.execute(update(AgentRun).where(AgentRun.id == row.id,
        AgentRun.status == 'queued', AgentRun.attempt_count == row.attempt_count)
        .values(status='running', attempt_count=attempt, started_at=now))
    if changed.rowcount:
        db.refresh(row)
        _event(db, row, 'query_started')
    db.commit()
    return attempt if changed.rowcount else None


def finish_query(db, run_id, attempt, result):
    row = db.query(AgentRun).filter_by(id=run_id, task_type=TASK_TYPE).first()
    if row is not None and (row.input_payload or {}).get('question_type'):
        from app.services.business_query_budget import finish
        return finish(db, run_id, attempt, result, _publish_query)
    return _publish_query(db, run_id, attempt, result)


def _publish_query(db, run_id, attempt, result):
    row, user = _owned(db, run_id)
    if row.data_version != _current_stamp(db, user, row):
        return False
    _validate_context(db, row, user)
    validate_road_query_evidence(db, result)
    validate_history_query_evidence(db, result)
    validate_business_query_evidence(db, result)
    validate_answer(db, result)
    if result.get('status') not in FINAL_RUN_STATUSES:
        raise ValueError('invalid_query_result_status')
    from app.services.business_query_budget import check as check_budget
    budget = db.info.get('business_execution_budget')
    check_budget(db, poll=True)
    encoded = jsonable_encoder(result)
    check_budget(db, poll=True)
    now = datetime.now(timezone.utc)
    timeout = 120
    if (row.input_payload or {}).get('question_type'):
        consumed = (row.runtime_state or {}).get('consumed', {'active_ms': 0, 'tool_steps': 0})
        started = row.started_at.replace(tzinfo=timezone.utc) if row.started_at.tzinfo is None else row.started_at
        result['chain_usage'] = {**result.get('chain_usage', consumed),
            'active_ms': consumed['active_ms'] + max(0, round((now - started).total_seconds() * 1000))}
        encoded['chain_usage'] = result['chain_usage']
        if isinstance(result.get('answer'), dict) and isinstance(result['answer'].get('time_scope_versions'), dict):
            result['answer']['time_scope_versions']['condition_changes'] = row.input_payload.get('condition_changes', [])
            encoded['answer']['time_scope_versions']['condition_changes'] = row.input_payload.get('condition_changes', [])
        if result.get('error_code') != 'query_budget_exhausted':
            timeout = max(0, 120 - consumed['active_ms'] / 1000)
    changed = db.execute(update(AgentRun).where(AgentRun.id == row.id,
        AgentRun.status == 'running', AgentRun.attempt_count == attempt,
        AgentRun.started_at > now - timedelta(seconds=timeout))
        .execution_options(synchronize_session=False)
        .values(status=result['status'], result_summary=encoded, completed_at=now))
    if changed.rowcount:
        db.refresh(row)
        partial_scans = [card for card in result.get('cards', [])
                         if card.get('tool') == 'aggregate_case_profiles'
                         and not (card.get('data') or {}).get('coverage', {}).get('complete', True)]
        if partial_scans and result['status'] == 'degraded':
            from copy import deepcopy
            from app.services.profile_aggregate_jobs import create_aggregate_job
            updated_result = deepcopy(result)
            for card in updated_result['cards']:
                if card not in partial_scans:
                    continue
                try:
                    card['continuation'] = create_aggregate_job(db, card['evidence']['filters'], query_id=run_id)
                except ValueError as error:
                    if str(error) != 'topic_capacity_reached':
                        raise
                    card['continuation'] = {'status': 'unavailable', 'error_code': 'background_capacity_reached'}
            row.result_summary = jsonable_encoder(updated_result)
        usage = result.get('usage')
        if usage is not None:
            AgentRunService.record_usage(db, row, provider=result.get('execution_mode', 'intranet_model'),
                model_name=row.model_name or ('not_used' if not usage['model_requests'] else 'configured_query_model'),
                status='completed' if usage['token_state'] != 'unavailable' else 'usage_unavailable',
                request_count=usage['model_requests'], input_tokens=usage.get('input_tokens') or 0,
                output_tokens=usage.get('output_tokens') or 0, duration_ms=usage['duration_ms'],
                error_code='token_usage_unavailable' if usage['token_state'] == 'unavailable' else None)
        _event(db, row, 'query_finished')
    if budget is None:
        db.commit()
    else:
        check_budget(db, poll=False)
    return changed.rowcount == 1


def expire_query(db, run_id):
    row, _ = _owned(db, run_id)
    now = datetime.now(timezone.utc)
    changed = db.execute(update(AgentRun).where(AgentRun.id == row.id,
        AgentRun.status == 'running', AgentRun.started_at <= now - timedelta(seconds=120))
        .execution_options(synchronize_session=False)
        .values(status='expired', completed_at=now))
    if changed.rowcount:
        db.refresh(row)
        _event(db, row, 'query_expired')
    db.commit()
    return {'id': row.id, 'status': row.status}


async def execute_query(db, run_id, *, model=None):
    """Dedicated owner-bound session. Test injection is not exposed to clients."""
    from app.services.intelligent_query_loop import create_query_model, run_query
    attempt = claim_query(db, run_id)
    if attempt is None:
        return expire_query(db, run_id)
    request = read_query(db, run_id)
    question = request['query']

    def cancelled():
        try:
            row, user = _owned(db, run_id)
            _validate_context(db, row, user)
            return (row.status != 'running' or row.attempt_count != attempt
                    or row.data_version != _current_stamp(db, user, row))
        except (ValueError, PermissionError):
            return True

    # Never share the worker's active SQL connection with the cancellation
    # watcher. StaticPool in-memory test DBs cannot supply another connection;
    # they retain statement deadlines and between-step cancellation.
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool, SingletonThreadPool
    engine = db.get_bind()
    if hasattr(engine, 'pool') and not isinstance(engine.pool, (StaticPool, SingletonThreadPool)):
        owner = db.info['principal_user_id']
        def cancellation_probe():
            with Session(engine) as probe:
                probe.info['principal_user_id'] = owner
                candidate, user = _owned(probe, run_id)
                return (candidate.status != 'running' or candidate.attempt_count != attempt
                        or candidate.data_version != _current_stamp(probe, user, candidate))
        db.info['execution_cancel_probe'] = cancellation_probe
    row = db.query(AgentRun).filter_by(id=run_id).one()
    envelope = row.input_payload.get('task_envelope')
    try:
        if request.get('question_type'):
            from app.services.business_answer import run_business_answer
            from app.services.business_query_budget import for_run
            result = run_business_answer(db, request['question_type'], request['source_context'],
                cancelled=cancelled, envelope=envelope, consumed=(row.runtime_state or {}).get('consumed'),
                version_note=(row.runtime_state or {}).get('version_note'),
                history_area_filter=row.input_payload.get('history_area_filter'),
                budget=for_run(db, row, cancelled=cancelled))
        elif request.get('preset'):
            from app.services.intelligent_query_presets import run_preset
            result = await run_preset(db, question, request['preset'], cancelled=cancelled,
                context=request['followup_context'] or request['initial_context'], envelope=envelope)
        else:
            try:
                selected_model = model if model is not None else create_query_model(db)
            except ValueError:
                from app.services.intelligent_query_answers import compose_answer
                result = {'status': 'degraded', 'cards': [], 'trace': [],
                          'execution_mode': 'intranet_model', 'task_envelope': envelope,
                          'answer': compose_answer([]), 'error_code': 'query_model_unavailable'}
            else:
                result = await run_query(db, question, selected_model, cancelled=cancelled,
                    context=request['followup_context'] or request['initial_context'], envelope=envelope)
    finally:
        db.info.pop('execution_cancel_probe', None)
    if result['status'] == 'cancelled':
        # The worker has already claimed this attempt. Revoked/disabled users
        # must not prevent a system-only terminal transition (no data returned).
        changed = db.execute(update(AgentRun).where(AgentRun.id == run_id,
            AgentRun.task_type == TASK_TYPE, AgentRun.status == 'running',
            AgentRun.attempt_count == attempt).values(
                status='cancelled', completed_at=datetime.now(timezone.utc)))
        if changed.rowcount:
            row = db.query(AgentRun).filter_by(id=run_id).populate_existing().one()
            AgentRunService.append_event(db, row, event_type='query_access_cancelled',
                                         status='cancelled', actor_type='system')
        db.commit()
        return {'id': run_id, 'status': 'cancelled'}
    if not finish_query(db, run_id, attempt, result):
        # Never replace a cancellation with the late model's answer.
        return expire_query(db, run_id)
    return {'id': run_id, 'status': result['status']}
