"""No generic task execution surface: only known failed derived work."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import bind_principal_scope, get_db
from app.services import derived_operations as service

router = APIRouter()


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    expected_attempts: int = Field(ge=0)


def _authorized(request, db):
    principal = getattr(request.state, 'principal', None)
    if principal is None:
        raise HTTPException(401, '请先登录')
    bind_principal_scope(db, principal, method=request.method)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except PermissionError as error:
        raise HTTPException(403, '当前账号或原任务授权不可用') from error
    except LookupError as error:
        raise HTTPException(404, '当前授权内未找到可用任务') from error
    except (ValueError, KeyError) as error:
        raise HTTPException(409, '任务状态、来源或运行条件已变化，请刷新后核对') from error


@router.get('')
def directory(request: Request, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              status: str | None = Query(None, pattern='^(pending|retry|processing|waiting_dependency|failed)$'),
              db: Session = Depends(get_db)):
    _authorized(request, db)
    return _call(service.directory, db, page=page, page_size=page_size, status=status)


@router.post('/{event_id}/retry', status_code=202)
def retry(event_id: str, payload: RetryRequest, request: Request, db: Session = Depends(get_db)):
    _authorized(request, db)
    return _call(service.retry_failed, db, event_id, expected_attempts=payload.expected_attempts,
                 request_id=str(payload.request_id))
