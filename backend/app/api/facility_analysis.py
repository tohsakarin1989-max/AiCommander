"""Current facility and regional views; all endpoints are read-only."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.map_foundation import OperationalArea
from app.services.intelligent_query_tasks import _identity
from app.services.facility_summary_service import read_dossier

router = APIRouter()


def _prepare(request, response, db, start_date, end_date, allowed_keys):
    response.headers['Cache-Control'] = 'no-store'
    principal = getattr(request.state, 'principal', None)
    if principal is None:
        raise HTTPException(401, detail='请先登录')
    if set(request.query_params) - set(allowed_keys):
        raise HTTPException(422, detail='存在不支持的筛选条件')
    db.info['principal_user_id'] = principal.user_id
    try:
        _identity(db)
    except PermissionError as error:
        raise HTTPException(403, detail='当前账号不可访问') from error
    start = start_date.replace(tzinfo=timezone.utc) if start_date and start_date.tzinfo is None else start_date
    end = end_date.replace(tzinfo=timezone.utc) if end_date and end_date.tzinfo is None else end_date
    if start and end and start >= end:
        raise HTTPException(422, detail='起始时间必须早于结束时间（结束时间不包含在内）')
    return start, end


def _call(db, action, *args, **kwargs):
    try:
        return action(db, *args, **kwargs)
    except PermissionError as error:
        raise HTTPException(403, detail='当前范围或来源不可访问，不返回历史摘要或数量') from error
    except ValueError as error:
        code = 404 if str(error) in {'facility_not_found', 'asset_not_found'} else 422
        raise HTTPException(code, detail='设施不存在或筛选条件不符合要求') from error
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(503, detail='设施资料暂不可用，请稍后重试', headers={'Retry-After': '5'}) from error


@router.get('/assets/{asset_id}')
def dossier(asset_id: int, request: Request, response: Response,
            start_date: datetime | None = Query(None), end_date: datetime | None = Query(None),
            db: Session = Depends(get_db)):
    start, end = _prepare(request, response, db, start_date, end_date, ('start_date', 'end_date'))
    return _call(db, read_dossier, asset_id, start_date=start, end_date=end)


@router.get('/region')
def region(request: Request, response: Response,
           operational_area_id: int | None = Query(None, ge=1),
           start_date: datetime | None = Query(None), end_date: datetime | None = Query(None),
           page: int = Query(1, ge=1, le=10000), page_size: int = Query(20, ge=1, le=100),
           db: Session = Depends(get_db)):
    from app.services.facility_condition_comparison import build_region_content
    start, end = _prepare(request, response, db, start_date, end_date,
        ('operational_area_id', 'start_date', 'end_date', 'page', 'page_size'))
    allowed = db.info['authorized_area_ids']
    if operational_area_id is not None:
        if allowed is not None and operational_area_id not in allowed:
            raise HTTPException(403, detail='当前厂区不可访问')
        if not db.query(OperationalArea.id).filter_by(id=operational_area_id, status='active').first():
            raise HTTPException(404, detail='厂区不存在或未启用')
    return _call(db, build_region_content, operational_area_id=operational_area_id,
                 start_date=start, end_date=end, page=page, page_size=page_size)
