"""Authenticated synthetic executions and owner-bound immutable replay.

Only archive data goes to the application database. The execution itself creates
its own disposable database and accepts no business identifiers or model input.
"""
from datetime import datetime, timedelta, timezone
from threading import BoundedSemaphore
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.agent_run import AgentRun
from app.models.user import User
from app.services.showcase_execution import DATASET_VERSION, execute_scenario


router = APIRouter()
_slots = BoundedSemaphore(2)


class ShowcaseRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scenario: Literal['normal', 'missing_location', 'model_unavailable']
    request_id: UUID


def _authorize(request, response, db):
    response.headers['Cache-Control'] = 'no-store'
    if not settings.ENABLE_SHOWCASE:
        raise HTTPException(404, '展示未启用')
    principal = getattr(request.state, 'principal', None)
    if principal is None:
        raise HTTPException(401, '请先登录')
    user = db.query(User).filter_by(id=principal.user_id, is_active=True).populate_existing().first()
    if user is None or user.role not in {'admin', 'analyst'}:
        raise HTTPException(403, '当前账号无权进入展示')
    return user


def _view(row, *, live=False):
    return {'id': row.id, 'status': row.status, 'scenario': row.input_payload['scenario'],
            'created_at': row.created_at, 'completed_at': row.completed_at,
            'view_kind': 'live_result' if live else 'historical_replay',
            'result': row.result_summary, 'error': row.error_message,
            'boundary': '仅合成数据；历史回放不重新执行工具，不代表当前业务态势。'}


def _find(db, uid, run_id):
    return db.query(AgentRun).filter_by(id=str(run_id), task_type='showcase', created_by=uid).first()


def _expire(db, uid):
    db.execute(update(AgentRun).where(AgentRun.task_type == 'showcase', AgentRun.created_by == uid,
        AgentRun.status == 'running', AgentRun.started_at < datetime.now(timezone.utc) - timedelta(seconds=120))
        .values(status='expired', completed_at=datetime.now(timezone.utc),
                error_message='演示执行中断或超过120秒，请使用新的请求重新运行。')
        .execution_options(synchronize_session=False))
    db.commit()
    db.expire_all()


@router.get('/runs')
def history(request: Request, response: Response, db: Session = Depends(get_db)):
    user = _authorize(request, response, db)
    _expire(db, user.id)
    rows = db.query(AgentRun).filter_by(task_type='showcase', created_by=user.id).order_by(
        AgentRun.created_at.desc(), AgentRun.id.desc()).limit(20).all()
    return {'items': [_view(row) for row in rows]}


@router.get('/runs/{run_id}')
def read(run_id: UUID, request: Request, response: Response, db: Session = Depends(get_db)):
    user = _authorize(request, response, db)
    _expire(db, user.id)
    row = _find(db, user.id, run_id)
    if row is None:
        raise HTTPException(404, '展示记录不存在')
    return _view(row)


@router.post('/runs', status_code=201)
def create(payload: ShowcaseRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = _authorize(request, response, db)
    _expire(db, user.id)
    if not _slots.acquire(blocking=False):
        raise HTTPException(429, '展示运行繁忙，请稍后重试', headers={'Retry-After': '10'})
    try:
        # Serialize admission, not execution. Never hold the core write lock while
        # executing the synthetic pipeline.
        db.execute(update(User).where(User.id == user.id).values(id=User.id))
        row = _find(db, user.id, payload.request_id)
        if row:
            if row.input_payload['scenario'] != payload.scenario:
                raise HTTPException(409, '同一请求编号不能更换演示场景')
            response.status_code = 200
            return _view(row)
        if db.query(AgentRun.id).filter_by(id=str(payload.request_id)).first():
            raise HTTPException(409, '请求编号不可用，请使用新的编号')
        recent = db.query(AgentRun.id).filter(AgentRun.created_by == user.id,
            AgentRun.task_type == 'showcase', AgentRun.created_at >= datetime.now(timezone.utc) - timedelta(minutes=1)).count()
        if recent >= 3:
            raise HTTPException(429, '每分钟最多运行三次展示', headers={'Retry-After': '60'})
        row = AgentRun(id=str(payload.request_id), task_type='showcase', query='合成数据展示',
            case_ids=[], asset_ids=[], mode='shadow', status='running', created_by=user.id,
            data_version=DATASET_VERSION, input_payload={'scenario': payload.scenario},
            runtime_state={}, result_summary={}, started_at=datetime.now(timezone.utc))
        db.add(row)
        db.commit()
        try:
            result = execute_scenario(payload.scenario)
            values = {'result_summary': result, 'status': 'completed'}
        except Exception:
            # Persist an honest failed run; never serve canned success on failure.
            values = {'status': 'failed', 'error_message': '合成演示执行失败，未修改正式业务数据；请由管理员检查。'}
        db.execute(update(AgentRun).where(AgentRun.id == row.id, AgentRun.status == 'running',
            AgentRun.started_at >= datetime.now(timezone.utc) - timedelta(seconds=120))
            .values(**values, completed_at=datetime.now(timezone.utc)).execution_options(synchronize_session=False))
        db.commit()
        _expire(db, user.id)
        db.refresh(row)
        # A disabled account cannot retrieve a late result.
        _authorize(request, response, db)
        response.headers['Location'] = f'/api/showcase/runs/{row.id}'
        return _view(row, live=True)
    finally:
        db.rollback()
        _slots.release()
