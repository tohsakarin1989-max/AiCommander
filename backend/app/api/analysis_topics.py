"""Saved topics; reads never enqueue work or call a model."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import analysis_topic_service as service
from app.services.intelligent_query_tools import ProfileFilters
from app.services import topic_query_bridge
from app.services.topic_document import export_topic_document
from app.services.case_result_export import CaseResultExportError


router = APIRouter()


class TopicCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=120)
    notes: str = Field(default='', max_length=4000)
    filters: ProfileFilters = Field(default_factory=ProfileFilters)


class TopicUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=4000)
    paused: bool | None = Field(default=None, strict=True)


class TopicFromQuery(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    query_id: UUID
    title: str = Field(min_length=1, max_length=120)
    notes: str = Field(default='', max_length=4000)


class TopicQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=2000)
    revision: int = Field(ge=1, strict=True)


def _authorize(request, response, db):
    response.headers['Cache-Control'] = 'no-store'
    principal = getattr(request.state, 'principal', None)
    if principal is None:
        raise HTTPException(401, detail='请先登录')
    db.info['principal_user_id'] = principal.user_id


def _call(db, action, *args, **kwargs):
    try:
        return action(db, *args, **kwargs)
    except PermissionError as error:
        db.rollback()
        raise HTTPException(403, detail={'code': 'topic_access_changed',
            'message': '专题权限或来源已变化，当前成果不可读取'}) from error
    except ValueError as error:
        db.rollback()
        if str(error) == 'topic_capacity_reached':
            raise HTTPException(429, detail='持续专题过多，请先暂停不再使用的专题',
                                headers={'Retry-After': '60'}) from error
        status = 404 if str(error) in {'topic_not_found', 'topic_snapshot_not_found', 'topic_source_not_found'} else 422
        if str(error) == 'topic_paused':
            status = 409
        if str(error) == 'topic_query_conditions_unsupported':
            raise HTTPException(422, detail='本次查询包含相似度、道路或成果时间等专用条件，不能等价保存为案件专题；请使用画像条件统计后保存。') from error
        raise HTTPException(status, detail='专题不存在、已暂停或参数不符合要求') from error
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(503, detail='专题存储暂不可用', headers={'Retry-After': '5'}) from error


@router.post('', status_code=201)
def create(payload: TopicCreate, request: Request, response: Response, db: Session = Depends(get_db)):
    _authorize(request, response, db)
    result = _call(db, service.create_topic, payload.title, payload.filters.model_dump(mode='json'), payload.notes)
    response.headers['Location'] = f"/api/analysis-topics/{result['id']}"
    return result


@router.get('')
def listing(request: Request, response: Response, page: int = Query(1, ge=1, le=10000),
            page_size: int = Query(20, ge=1, le=50), db: Session = Depends(get_db)):
    _authorize(request, response, db)
    return _call(db, service.list_topics, page=page, page_size=page_size)


@router.post('/from-query', status_code=201)
def from_query(payload: TopicFromQuery, request: Request, response: Response, db: Session = Depends(get_db)):
    _authorize(request, response, db)
    result = _call(db, topic_query_bridge.save_query_as_topic, str(payload.query_id), payload.title, payload.notes)
    response.headers['Location'] = f"/api/analysis-topics/{result['id']}"
    return result


@router.post('/{topic_id}/queries', status_code=201)
def question(topic_id: UUID, payload: TopicQuestion, request: Request, response: Response, db: Session = Depends(get_db)):
    from app.config import settings
    _authorize(request, response, db)
    if not settings.ENABLE_AGENT_LAB or settings.AGENT_MODE == 'off':
        raise HTTPException(404, detail='智能查询未启用；专题统计仍可使用')
    result = _call(db, topic_query_bridge.query_topic, str(topic_id), payload.revision, payload.query)
    response.headers['Location'] = f"/api/intelligent-queries/{result['id']}"
    return result


@router.get('/{topic_id}')
def read(topic_id: UUID, request: Request, response: Response, revision: int | None = Query(None, ge=1),
         page: int = Query(1, ge=1, le=10000), page_size: int = Query(20, ge=1, le=20),
         db: Session = Depends(get_db)):
    _authorize(request, response, db)
    return _call(db, service.read_topic, str(topic_id), revision=revision, page=page, page_size=page_size)


@router.patch('/{topic_id}')
def amend(topic_id: UUID, payload: TopicUpdate, request: Request, response: Response,
          db: Session = Depends(get_db)):
    _authorize(request, response, db)
    return _call(db, service.update_topic, str(topic_id), **payload.model_dump(exclude_unset=True))


@router.post('/{topic_id}/refresh', status_code=202)
def refresh(topic_id: UUID, request: Request, response: Response, db: Session = Depends(get_db)):
    _authorize(request, response, db)
    return _call(db, service.request_refresh, str(topic_id))


@router.get('/{topic_id}/history')
def history(topic_id: UUID, request: Request, response: Response, page: int = Query(1, ge=1, le=10000),
            page_size: int = Query(20, ge=1, le=50), db: Session = Depends(get_db)):
    _authorize(request, response, db)
    return _call(db, service.topic_history, str(topic_id), page=page, page_size=page_size)


@router.get('/{topic_id}/evidence/{case_id}')
def evidence(topic_id: UUID, case_id: int, request: Request, response: Response,
             revision: int = Query(..., ge=1), db: Session = Depends(get_db)):
    _authorize(request, response, db)
    return _call(db, service.read_topic_evidence, str(topic_id), case_id, revision=revision)


@router.get('/{topic_id}/views')
def views(topic_id: UUID, request: Request, response: Response, revision: int = Query(..., ge=1),
          page: int = Query(1, ge=1, le=10000), page_size: int = Query(20, ge=1, le=20),
          db: Session = Depends(get_db)):
    _authorize(request, response, db)
    return _call(db, service.read_topic_views, str(topic_id), revision=revision, page=page, page_size=page_size)


def _download(topic_id, revision, format, request, response, db):
    _authorize(request, response, db)
    try:
        document, content = _call(db, export_topic_document, str(topic_id), revision, format)
    except CaseResultExportError as error:
        raise HTTPException(503, detail='文档导出暂不可用，请稍后重试',
                            headers={'Cache-Control': 'no-store'}) from error
    return Response(content, media_type=('application/pdf' if format == 'pdf' else
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'), headers={
        'Cache-Control': 'no-store', 'X-Result-Content-SHA256': document.content_sha256,
        'Content-Disposition': f'attachment; filename="topic-{topic_id}-v{revision}.{format}"'})


@router.get('/{topic_id}/document.docx')
def download_docx(topic_id: UUID, request: Request, response: Response,
                  revision: int = Query(..., ge=1), db: Session = Depends(get_db)):
    return _download(topic_id, revision, 'docx', request, response, db)


@router.get('/{topic_id}/document.pdf')
def download_pdf(topic_id: UUID, request: Request, response: Response,
                 revision: int = Query(..., ge=1), db: Session = Depends(get_db)):
    return _download(topic_id, revision, 'pdf', request, response, db)
