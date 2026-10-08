"""Clarifications use the existing query row; waiting owns no worker lease."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import update

from app.agent_runtime.execution_contract import TaskEnvelope
from app.models.agent_run import AgentRun
from app.models.user import User
from app.services.business_answer import (
    ClarificationReply, missing_context, normalize_context, source_binding, validate_answer,
)
from app.services.intelligent_query_context import result_hash


def validate_context(db, row, user):
    from app.services import intelligent_query_tasks as tasks
    payload = row.input_payload
    context = normalize_context(db, payload['question_type'], payload['source_context'])
    parent_binding = payload.get('business_parent')
    if parent_binding:
        parent, _ = tasks._owned(db, parent_binding['id'])
        if (parent.data_version != tasks._current_stamp(db, user, parent)
                or parent.status not in {'completed', 'degraded'}
                or result_hash(parent.result_summary) != parent_binding['result_hash']):
            raise PermissionError('business_answer_parent_changed')
        validate_answer(db, parent.result_summary)
    return context


def create(db, question, question_type, source_context, parent_query_id):
    from app.services import intelligent_query_tasks as tasks
    user = tasks._identity(db)
    area_origin = 'user' if (source_context or {}).get('area_id') is not None else 'derived'
    parent_binding, consumed, changes = None, {'tool_steps': 0, 'active_ms': 0}, []
    if parent_query_id:
        parent, _ = tasks._owned(db, parent_query_id)
        if parent.data_version != tasks._current_stamp(db, user, parent):
            raise PermissionError('query_scope_changed')
        if parent.status not in {'completed', 'degraded'} or not parent.input_payload.get('question_type'):
            raise ValueError('business_answer_parent_invalid')
        tasks.read_query(db, parent.id)
        inherited = parent.input_payload['source_context']
        area_origin = parent.input_payload.get('area_origin', 'derived')
        if question_type and question_type != parent.input_payload['question_type']:
            raise ValueError('business_answer_question_changed')
        for key, value in (source_context or {}).items():
            if inherited.get(key) != value:
                if key not in {'time_basis', 'period'} or parent.input_payload['question_type'] == 'case_history':
                    raise ValueError('business_answer_context_changed')
                changes.append({'field': key, 'previous': inherited.get(key), 'current': value,
                                'basis': 'explicit_source_context'})
        question_type, source_context = parent.input_payload['question_type'], {**inherited, **(source_context or {})}
        parent_binding = {'id': parent.id, 'result_hash': result_hash(parent.result_summary)}
        consumed = parent.result_summary['chain_usage']
    context = normalize_context(db, question_type, source_context)
    db.execute(update(User).where(User.id == user.id).values(id=User.id))
    pending = db.query(AgentRun.id).filter(AgentRun.task_type == tasks.TASK_TYPE,
        AgentRun.created_by == user.id, AgentRun.status.in_(['queued', 'running', 'waiting_clarification'])).count()
    if pending >= 4:
        raise ValueError('query_capacity_reached')
    identifier, now = str(uuid4()), datetime.now(timezone.utc)
    missing = missing_context(question_type, context)
    state = {'consumed': consumed}
    if changes:
        state['version_note'] = '已按明确选择变更时间口径或周期；本轮重新计算，不将不同条件的数值直接称为实际情况变化。'
    if missing:
        state['clarification'] = {'id': str(uuid4()), 'field': missing[0], 'prompt': missing[1],
            'expires_at': (now + timedelta(hours=24)).isoformat()}
    stamp = tasks._stamp(db, user, 'membership-v2')
    envelope = TaskEnvelope(identifier, 'deterministic_business_question', user.id, stamp,
        source_bindings={'question_type': question_type, 'source_context': context}).public()
    row = AgentRun(id=identifier, task_type=tasks.TASK_TYPE, query=question.strip(), case_ids=[], asset_ids=[],
        mode='shadow', status='waiting_clarification' if missing else 'queued', created_by=user.id,
        data_version=stamp, created_at=now, input_payload={'scope_contract': 'membership-v2', 'task_envelope': envelope,
            'question_type': question_type, 'source_context': context, 'source_binding': source_binding(db, context),
            'area_origin': area_origin,
            'history_area_filter': context.get('area_id') if area_origin == 'user' and question_type == 'case_history' else None,
            'condition_changes': changes,
            **({'business_parent': parent_binding} if parent_binding else {})},
        runtime_state=state, result_summary={})
    db.add(row)
    db.flush()
    tasks._event(db, row, 'query_waiting_clarification' if missing else 'query_created')
    db.commit()
    return tasks._view(row)


def expire_waiting(db, row):
    from app.services import intelligent_query_tasks as tasks
    if row.status != 'waiting_clarification':
        return False
    expires = datetime.fromisoformat(row.runtime_state['clarification']['expires_at'])
    if datetime.now(timezone.utc) < expires:
        return False
    changed = db.execute(update(AgentRun).where(AgentRun.id == row.id, AgentRun.status == 'waiting_clarification')
        .values(status='expired', completed_at=datetime.now(timezone.utc)))
    if changed.rowcount:
        db.refresh(row)
        tasks._event(db, row, 'query_clarification_expired')
        db.commit()
    return bool(changed.rowcount)


def clarify(db, run_id, reply):
    from app.services import intelligent_query_tasks as tasks
    parsed = ClarificationReply.model_validate(reply).model_dump()
    row, user = tasks._owned(db, run_id)
    # Serialize duplicate replies in both SQLite and PostgreSQL; no business write.
    db.execute(update(AgentRun).where(AgentRun.id == row.id).values(id=AgentRun.id))
    db.refresh(row)
    if row.data_version != tasks._current_stamp(db, user, row):
        raise PermissionError('query_scope_changed')
    if not row.input_payload.get('question_type'):
        raise ValueError('business_answer_clarification_not_expected')
    validate_context(db, row, user)
    accepted = (row.runtime_state or {}).get('accepted_reply')
    if accepted:
        if accepted != parsed:
            raise ValueError('business_answer_clarification_conflict')
        db.commit()
        return tasks.read_query(db, run_id)
    if expire_waiting(db, row) or row.status == 'expired':
        return tasks._view(row)
    pending = (row.runtime_state or {}).get('clarification')
    if row.status != 'waiting_clarification' or not pending or pending['id'] != parsed['clarification_id']:
        raise ValueError('business_answer_clarification_not_expected')
    context = normalize_context(db, row.input_payload['question_type'],
        {**row.input_payload['source_context'], pending['field']: parsed['value']})
    if missing_context(row.input_payload['question_type'], context):
        raise ValueError('business_answer_clarification_incomplete')
    binding = source_binding(db, context)
    state = {**row.runtime_state, 'accepted_reply': parsed}
    state.pop('clarification', None)
    old_binding = row.input_payload.get('source_binding', {})
    if any(binding.get(key) != value for key, value in old_binding.items()):
        state['version_note'] = '等待期间来源版本已变化；本轮已重新读取当前资料，未混用旧证据。'
    payload = {**row.input_payload, 'source_context': context, 'source_binding': binding}
    payload['task_envelope'] = {**payload['task_envelope'], 'source_bindings': {
        'question_type': payload['question_type'], 'source_context': context}}
    row.input_payload, row.runtime_state, row.status = payload, state, 'queued'
    tasks._event(db, row, 'query_clarification_accepted')
    db.commit()
    return tasks._view(row)


def refresh_for_execution(db, row):
    context = row.input_payload['source_context']
    binding = source_binding(db, context)
    if binding != row.input_payload.get('source_binding'):
        row.runtime_state = {**row.runtime_state,
            'version_note': '排队或等待期间来源版本已变化；本轮重新读取当前资料，未混用旧证据。'}
        row.input_payload = {**row.input_payload, 'source_binding': binding}
