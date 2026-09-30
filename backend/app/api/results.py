"""Unified, authenticated material reading and optional version decisions."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_db, AreaWriteAccessError
from app.services import result_catalog
from app.services.case_result_export import CaseResultExportError
from app.services.case_map_image import CaseMapImageError

router = APIRouter()


def _prepare(request, response, db):
    principal = getattr(request.state, 'principal', None)
    if principal is None:
        raise HTTPException(401, '请先登录')
    db.info['principal_user_id'] = principal.user_id
    response.headers['Cache-Control'] = 'no-store'


def _call(db, action, *args, **kwargs):
    try:
        return action(db, *args, **kwargs)
    except AreaWriteAccessError:
        db.rollback()
        raise HTTPException(403, '没有目标范围写权限') from None
    except PermissionError:
        db.rollback()
        raise HTTPException(404, '材料不存在、引用失效或当前不可访问', headers={'Cache-Control': 'no-store'}) from None
    except CaseMapImageError:
        raise HTTPException(503, '固定版本地图渲染暂不可用', headers={'Cache-Control': 'no-store'}) from None
    except ValueError:
        db.rollback()
        raise HTTPException(409, '材料版本、请求条件或引用不一致，请刷新后重试', headers={'Cache-Control': 'no-store'}) from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, '材料存储暂不可用，请稍后重试', headers={'Cache-Control': 'no-store'}) from None
    except CaseResultExportError:
        raise HTTPException(503, '本地文档或地图渲染暂不可用，未提供省略内容的替代材料', headers={'Cache-Control': 'no-store'}) from None


@router.get('')
def catalog(request: Request, response: Response, q: str = Query('', max_length=100),
            kind: str | None = None, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=10000),
            subject_kind: str | None = None, subject_id: str | None = None, db=Depends(get_db)):
    _prepare(request, response, db)
    return _call(db, result_catalog.catalog, query=q, kind=kind, limit=limit, offset=offset,
                 subject_kind=subject_kind, subject_id=subject_id)


class FacilityFreeze(BaseModel):
    model_config = ConfigDict(extra='forbid')
    start_date: datetime | None = None
    end_date: datetime | None = None
    valid_at: datetime | None = None
    known_at: datetime | None = None
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')


@router.post('/facilities/{asset_id}', status_code=201)
def freeze_facility(asset_id: int, payload: FacilityFreeze, request: Request, response: Response, db=Depends(get_db)):
    from app.services.facility_material_service import freeze_facility as freeze
    _prepare(request, response, db)
    row, created = _call(db, freeze, asset_id, **payload.model_dump())
    result = _call(db, result_catalog.read_result, 'facility', row.id)
    db.commit()
    response.status_code = 201 if created else 200
    response.headers['Location'] = f'/api/results/facility/{row.id}'
    return result


class SourceReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: str = Field(min_length=1, max_length=24)
    id: str = Field(min_length=1, max_length=80)
    content_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class JudgmentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    decision: Literal['confirm', 'retain_reference', 'insufficient_evidence', 'exclude_with_evidence']
    note: str = Field(min_length=1, max_length=4000)
    additional_sources: list[SourceReference] = Field(default_factory=list, max_length=10)
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')


@router.post('/{kind}/{identifier}/judgments', status_code=201)
def judgment(kind: str, identifier: str, payload: JudgmentInput, request: Request, response: Response, db=Depends(get_db)):
    from app.services.result_judgment_service import record_judgment
    _prepare(request, response, db)
    row, created = _call(db, record_judgment, kind, identifier, **payload.model_dump())
    result = _call(db, result_catalog.read_result, kind, identifier)
    db.commit()
    response.status_code = 201 if created else 200
    return result


@router.get('/{kind}/{identifier}')
def reader(kind: str, identifier: str, request: Request, response: Response, db=Depends(get_db)):
    _prepare(request, response, db)
    return _call(db, result_catalog.read_result, kind, identifier)


@router.get('/{kind}/{identifier}/document.{format}')
def document(kind: str, identifier: str, format: Literal['docx', 'pdf'], request: Request, response: Response, db=Depends(get_db)):
    from app.services.result_document import export_result
    _prepare(request, response, db)
    saved, data = _call(db, export_result, kind, identifier, format)
    media = 'application/pdf' if format == 'pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    return Response(data, media_type=media, headers={'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff', 'X-Result-Content-SHA256': saved.content_sha256,
        'Content-Disposition': f'attachment; filename="material-{saved.content_sha256[:16]}.{format}"'})


@router.get('/{kind}/{identifier}/map')
def map_context(kind: str, identifier: str, request: Request, response: Response, db=Depends(get_db)):
    from app.services.result_map_service import map_context as load
    _prepare(request, response, db)
    return _call(db, load, kind, identifier)


@router.get('/{kind}/{identifier}/map.png')
def map_image(kind: str, identifier: str, request: Request, response: Response, db=Depends(get_db)):
    from app.services.result_map_service import render_material_map
    from app.services.case_map_image import CaseMapImageError
    from app.services.document_budget import document_budget
    _prepare(request, response, db)
    source = _call(db, result_catalog.read_result, kind, identifier, include_judgments=False)
    try:
        data = _call(db, document_budget(render_material_map), kind, identifier)
    except CaseMapImageError:
        raise HTTPException(503, '固定版本地图渲染暂不可用', headers={'Cache-Control': 'no-store'}) from None
    return Response(data, media_type='image/png', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'X-Result-Content-SHA256': source['content_sha256']})
