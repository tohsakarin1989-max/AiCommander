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
from sqlalchemy import update

from app.agent_runtime.service import AgentRunService, FINAL_RUN_STATUSES
from app.database import bind_principal_scope
from app.models.agent_run import AgentRun
from app.models.case import Case
from app.models.jurisdiction import JurisdictionAsset
from app.models.map_foundation import MapSnapshot
from app.models.user import User


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


def _stamp(db, user):
    # Until a central authorization revision exists, fingerprint membership.
    # This also catches a case/asset moved out of scope without changing grants.
    digest = hashlib.sha256(json.dumps({
        'user': user.id, 'role': user.role, 'session_version': user.session_version,
        'areas': db.info['authorized_area_ids'],
    }, sort_keys=True).encode())
    for model in (Case, JurisdictionAsset, MapSnapshot):
        digest.update(model.__tablename__.encode())
        for row in db.query(model.id, model.operational_area_id).order_by(model.id).yield_per(1000):
            digest.update(json.dumps(list(row), separators=(',', ':')).encode())
    return digest.hexdigest()


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
            'result': row.result_summary, 'result_kind': 'historical_query_snapshot'}


def create_query(db, question):
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
        raise ValueError('invalid_query_question')
    user = _identity(db)
    # Serialize each owner's admission before checking pending capacity. A no-op
    # UPDATE obtains the same lock on SQLite and PostgreSQL without broker I/O.
    db.execute(update(User).where(User.id == user.id).values(id=User.id))
    pending = db.query(AgentRun.id).filter(AgentRun.task_type == TASK_TYPE,
        AgentRun.created_by == user.id, AgentRun.status.in_(['queued', 'running'])).count()
    if pending >= 4:
        db.rollback()
        raise ValueError('query_capacity_reached')
    row = AgentRun(id=str(uuid4()), task_type=TASK_TYPE, query=question.strip(),
        case_ids=[], asset_ids=[], mode='shadow', status='queued', created_by=user.id,
        data_version=_stamp(db, user), input_payload={'scope_contract': 'membership-v1'},
        runtime_state={}, result_summary={})
    db.add(row)
    db.flush()
    _event(db, row, 'query_created')
    db.commit()
    return _view(row)


def read_query(db, run_id):
    row, user = _owned(db, run_id)
    if row.data_version != _stamp(db, user):
        raise PermissionError('query_scope_changed')
    return _view(row)


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
    if row.data_version != _stamp(db, user):
        raise PermissionError('query_scope_changed')
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
    row, user = _owned(db, run_id)
    if row.data_version != _stamp(db, user):
        return False
    if result.get('status') not in FINAL_RUN_STATUSES:
        raise ValueError('invalid_query_result_status')
    now = datetime.now(timezone.utc)
    changed = db.execute(update(AgentRun).where(AgentRun.id == row.id,
        AgentRun.status == 'running', AgentRun.attempt_count == attempt,
        AgentRun.started_at > now - timedelta(seconds=120))
        .execution_options(synchronize_session=False)
        .values(status=result['status'], result_summary=jsonable_encoder(result), completed_at=now))
    if changed.rowcount:
        db.refresh(row)
        _event(db, row, 'query_finished')
    db.commit()
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
    question = read_query(db, run_id)['query']

    def cancelled():
        try:
            row, user = _owned(db, run_id)
            return (row.status != 'running' or row.attempt_count != attempt
                    or row.data_version != _stamp(db, user))
        except (ValueError, PermissionError):
            return True

    try:
        selected_model = model if model is not None else create_query_model(db)
    except ValueError:
        result = {'status': 'degraded', 'cards': [], 'trace': [],
                  'error_code': 'query_model_unavailable'}
    else:
        result = await run_query(db, question, selected_model, cancelled=cancelled)
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
