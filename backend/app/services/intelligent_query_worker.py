"""Claim durable query jobs with freshly loaded owner permissions."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.agent_runtime.service import AgentRunService
from app.config import settings
from app.models.agent_run import AgentRun
from app.services.intelligent_query_tasks import TASK_TYPE, execute_query


async def process_next(db):
    if not settings.ENABLE_AGENT_LAB or settings.AGENT_MODE == 'off':
        return None
    now = datetime.now(timezone.utc)
    expired = db.query(AgentRun.id).filter(AgentRun.task_type == TASK_TYPE,
        AgentRun.status == 'running', AgentRun.started_at <= now - timedelta(seconds=120))
    old = expired.order_by(AgentRun.started_at, AgentRun.id).first()
    if old:
        changed = db.execute(update(AgentRun).where(AgentRun.id == old.id,
            AgentRun.task_type == TASK_TYPE, AgentRun.status == 'running',
            AgentRun.started_at <= now - timedelta(seconds=120))
            .execution_options(synchronize_session=False)
            .values(status='expired', completed_at=now))
        if changed.rowcount:
            row = db.query(AgentRun).filter_by(id=old.id).populate_existing().one()
            AgentRunService.append_event(db, row, event_type='query_worker_expired',
                                         status='expired', actor_type='system')
        db.commit()
        return {'id': old.id, 'status': 'expired' if changed.rowcount else 'claimed_elsewhere'}
    candidate = db.query(AgentRun.id, AgentRun.created_by).filter(
        AgentRun.task_type == TASK_TYPE, AgentRun.status == 'queued')
    row = candidate.order_by(AgentRun.created_at, AgentRun.id).first()
    if row is None:
        return None
    run_id, owner_id = row
    db.rollback()
    db.info['principal_user_id'] = owner_id
    try:
        return await execute_query(db, run_id)
    except PermissionError:
        db.rollback()
        # A revoked/deleted owner cannot authorize execution; system-only state
        # cleanup requires no data access and never returns question/results.
        changed = db.execute(update(AgentRun).where(AgentRun.id == run_id,
            AgentRun.task_type == TASK_TYPE, AgentRun.status.in_(['queued', 'running']))
            .values(status='cancelled', completed_at=datetime.now(timezone.utc)))
        if changed.rowcount:
            item = db.query(AgentRun).filter_by(id=run_id).populate_existing().one()
            AgentRunService.append_event(db, item, event_type='query_worker_access_cancelled',
                                         status='cancelled', actor_type='system')
        db.commit()
        return {'id': run_id, 'status': 'cancelled' if changed.rowcount else 'claimed_elsewhere'}
