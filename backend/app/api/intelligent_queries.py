"""Owner-bound query jobs. Submission never calls a model or broker."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services import intelligent_query_tasks as service


router = APIRouter()


class QueryCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=2000)


def _authorize(request, db, response):
    response.headers['Cache-Control'] = 'no-store'
    if not settings.ENABLE_AGENT_LAB or settings.AGENT_MODE == 'off':
        raise HTTPException(404, detail='智能查询未启用')
    principal = getattr(request.state, 'principal', None)
    if principal is None:
        raise HTTPException(401, detail='请先登录')
    if principal.role not in {'admin', 'analyst'}:
        raise HTTPException(403, detail='当前账号无权使用智能查询')
    db.info['principal_user_id'] = principal.user_id


def _call(db, operation, *args):
    try:
        return operation(db, *args)
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(403, detail={'code': 'query_access_changed',
            'message': '账号或数据范围已变化，请重新查询'}) from exc
    except ValueError as exc:
        db.rollback()
        if str(exc) == 'query_capacity_reached':
            raise HTTPException(429, detail='待处理查询过多，请等待完成或取消任务',
                                headers={'Retry-After': '5'}) from exc
        raise HTTPException(404 if str(exc) == 'query_not_found' else 422,
                            detail='查询不存在或参数不符合要求') from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(503, detail='查询存储暂不可用', headers={'Retry-After': '5'}) from exc


@router.post('', status_code=201)
def create(payload: QueryCreate, request: Request, response: Response, db: Session = Depends(get_db)):
    _authorize(request, db, response)
    result = _call(db, service.create_query, payload.query)
    response.headers['Location'] = f"/api/intelligent-queries/{result['id']}"
    return result


@router.get('/{run_id}')
def read(run_id: UUID, request: Request, response: Response, db: Session = Depends(get_db)):
    _authorize(request, db, response)
    return _call(db, service.read_query, str(run_id))


@router.post('/{run_id}/cancel')
def cancel(run_id: UUID, request: Request, response: Response, db: Session = Depends(get_db)):
    _authorize(request, db, response)
    return _call(db, service.cancel_query, str(run_id))
