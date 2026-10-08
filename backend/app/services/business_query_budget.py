"""One active-time deadline through business-answer computation and publication."""
from contextlib import contextmanager
from datetime import datetime, timezone
import time

from sqlalchemy import update

from app.agent_runtime.execution_contract import ExecutionBudget, ExecutionCancelled, sql_budget
from app.models.agent_run import AgentRun


def clock():
    return time.monotonic()


def check(db, *, poll=False):
    budget = db.info.get('business_execution_budget')
    if budget is not None:
        budget.check(poll=poll)


@contextmanager
def bind(db, budget):
    previous = db.info.get('business_execution_budget')
    db.info['business_execution_budget'] = budget
    try:
        yield
    finally:
        if previous is None:
            db.info.pop('business_execution_budget', None)
        else:
            db.info['business_execution_budget'] = previous


def for_run(db, row, *, cancelled):
    started = row.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    consumed = (row.runtime_state or {}).get('consumed', {}).get('active_ms', 0)
    elapsed = max(0, (datetime.now(timezone.utc) - started).total_seconds())
    return ExecutionBudget(clock() + max(0, 120 - consumed / 1000 - elapsed),
                           cancelled=cancelled, clock=clock)


def _terminal(db, run_id, attempt, result, *, cancelled, elapsed_ms):
    """A deadline permits only a small terminal receipt, never late evidence."""
    from app.services import intelligent_query_tasks as tasks
    row = db.query(AgentRun).filter_by(id=run_id, task_type=tasks.TASK_TYPE).first()
    if row is None:
        return False
    consumed = (row.runtime_state or {}).get('consumed', {'active_ms': 0, 'tool_steps': 0})
    chain = result.get('chain_usage') or consumed
    old_usage = result.get('usage') or {}
    status = 'cancelled' if cancelled else 'degraded'
    boundary = '执行已停止；未交付超时或未经重新授权的证据。'
    context = row.input_payload['source_context']
    answer = {'schema_version': 'business-answer-8.4-1', 'question_type': row.input_payload['question_type'],
        'direct_answer': '本条问题链的执行预算已用尽，未交付不完整的晚到结果。',
        'summary': '本条问题链的执行预算已用尽，未交付不完整的晚到结果。',
        'completeness': 'service_unavailable', 'evidence': [], 'differences': [], 'findings': [],
        'unanswered': ['请缩小范围后重新提问。'], 'information_gaps': ['请缩小范围后重新提问。'],
        'boundary': boundary, 'map_context': None,
        'time_scope_versions': {'source_context': context, 'algorithm_version': 'business-answer-8.4-1',
            'scope_version': row.data_version, 'source_versions': [],
            'answered_at': datetime.now(timezone.utc).isoformat()}}
    clean = {'status': status, 'cards': [], 'trace': [], 'source_manifest': [],
        'error_code': 'query_access_changed' if cancelled else 'query_budget_exhausted',
        'execution_mode': 'deterministic_business_question', 'task_envelope': row.input_payload['task_envelope'],
        'chain_usage': {'tool_steps': max(consumed['tool_steps'], chain.get('tool_steps', 0)),
                        'active_ms': max(consumed['active_ms'] + elapsed_ms, chain.get('active_ms', 0))},
        'usage': {'model_requests': 0, 'tool_calls': old_usage.get('tool_calls', 0), 'input_tokens': 0,
                  'output_tokens': 0, 'token_state': 'not_used', 'duration_ms': elapsed_ms},
        'boundary': boundary, **({'answer': answer} if not cancelled else {})}
    changed = db.execute(update(AgentRun).where(AgentRun.id == run_id, AgentRun.task_type == tasks.TASK_TYPE,
        AgentRun.status == 'running', AgentRun.attempt_count == attempt).values(
            status=status, result_summary=clean, completed_at=datetime.now(timezone.utc)))
    if changed.rowcount:
        db.refresh(row)
        tasks._event(db, row, 'query_access_cancelled' if cancelled else 'query_budget_exhausted')
        result.clear()
        result.update(clean)
    db.commit()
    return bool(changed.rowcount)


def finish(db, run_id, attempt, result, publish):
    from app.services import intelligent_query_tasks as tasks
    row = db.query(AgentRun).filter_by(id=run_id, task_type=tasks.TASK_TYPE).one()
    initial_start = row.started_at
    if initial_start.tzinfo is None:
        initial_start = initial_start.replace(tzinfo=timezone.utc)

    def cancelled():
        try:
            current, user = tasks._owned(db, run_id)
            return (current.status in {'cancelled', 'expired'} or current.attempt_count != attempt
                    or current.data_version != tasks._current_stamp(db, user, current))
        except (PermissionError, ValueError):
            return True

    budget = for_run(db, row, cancelled=cancelled)
    try:
        if result.get('error_code') == 'query_budget_exhausted':
            raise TimeoutError('business_answer_budget_exhausted')
        with bind(db, budget), sql_budget(db, budget):
            changed = publish(db, run_id, attempt, result)
            budget.check(poll=False)
        # All answer validation, encoding and SQL work above share the deadline.
        # Commit only after the final check; a failed check rolls back the row,
        # events and usage before writing the small terminal receipt.
        budget.check(poll=False)
        db.commit()
        return changed
    except (TimeoutError, ExecutionCancelled) as error:
        db.rollback()
        elapsed_ms = max(0, round((datetime.now(timezone.utc) - initial_start).total_seconds() * 1000))
        return _terminal(db, run_id, attempt, result, cancelled=isinstance(error, ExecutionCancelled),
                         elapsed_ms=elapsed_ms)
