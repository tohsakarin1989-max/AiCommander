"""Read-only complete-filter exports; caller authorization is rebound per download."""
from datetime import datetime
import json
from time import perf_counter
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from app.database import get_db, AreaWriteAccessError
from app.services.case_table_export import ledger_snapshot, render_ledger, COLUMNS
from app.services import output_template_service
from app.utils.logger import logger

router = APIRouter()


def _prepare(request, response, db):
    principal = getattr(request.state, 'principal', None)
    if principal is None:
        raise HTTPException(401, '请先登录')
    db.info['principal_user_id'] = principal.user_id
    response.headers['Cache-Control'] = 'no-store'


def _template_call(db, function, *args, **kwargs):
    try:
        return function(db, *args, **kwargs)
    except AreaWriteAccessError:
        db.rollback()
        raise HTTPException(403, '没有目标范围写权限') from None
    except PermissionError:
        db.rollback()
        raise HTTPException(403, '输出模板当前不可访问或无保存权限') from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None


@router.get('/columns')
def columns(request: Request, response: Response, db=Depends(get_db)):
    _prepare(request, response, db)
    return [{'key': key, 'label': label} for key, label in COLUMNS]


@router.get('/templates')
def templates(request: Request, response: Response,
              kind: Literal['case_ledger', 'material_sections'] = 'case_ledger',
              operational_area_id: int | None = Query(None, ge=1), db=Depends(get_db)):
    _prepare(request, response, db)
    return _template_call(db, output_template_service.list_templates, kind, operational_area_id)


class TemplateCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    kind: Literal['case_ledger', 'material_sections']
    operational_area_id: int | None = Field(None, ge=1)
    configuration: dict = Field(max_length=1)


@router.post('/templates', status_code=201)
def create_template(payload: TemplateCreate, request: Request, response: Response, db=Depends(get_db)):
    _prepare(request, response, db)
    result = _template_call(db, output_template_service.save_template, **payload.model_dump())
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@router.get('/ledger.{format}')
def ledger(format: Literal['csv', 'xlsx'], request: Request,
           keyword: str | None = Query(None, max_length=200),
           statuses: list[str] | None = Query(None, max_length=20),
           case_types: list[str] | None = Query(None, max_length=50),
           oil_types: list[str] | None = Query(None, max_length=50),
           start_date: datetime | None = None, end_date: datetime | None = None,
           time_basis: Literal['discovery', 'incident', 'entry'] = 'discovery',
           output_template_id: str | None = Query(None, min_length=1, max_length=36),
           output_configuration: str | None = Query(None, max_length=8000),
           has_geo: bool | None = None, operational_area_id: int | None = Query(None, ge=1),
           db=Depends(get_db)):
    started = perf_counter()
    if getattr(request.state, 'principal', None) is None:
        raise HTTPException(401, '请先登录')
    if any(len(item) > 100 for values in (statuses, case_types, oil_types) for item in (values or [])):
        raise HTTPException(422, '筛选项过长')
    try:
        configuration = None
        if output_template_id and output_configuration:
            raise ValueError('请选择已存配置或本次自定义配置，不可同时指定')
        if output_configuration:
            try:
                configuration = json.loads(output_configuration)
            except (ValueError, TypeError):
                raise ValueError('台账配置无效') from None
            if configuration is None:
                raise ValueError('台账配置无效')
        if output_template_id:
            db.info['principal_user_id'] = request.state.principal.user_id
            configuration = _template_call(db, output_template_service.read_template,
                output_template_id, 'case_ledger')['configuration']
        snapshot = ledger_snapshot(db, output_configuration=configuration,
                                   keyword=keyword, statuses=statuses, case_types=case_types,
                                   oil_types=oil_types, start_date=start_date, end_date=end_date,
                                   time_basis=time_basis, has_geo=has_geo,
                                   operational_area_id=operational_area_id)
    except ValueError as exc:
        logger.info('output_operation kind=case_ledger format=%s outcome=invalid', format)
        raise HTTPException(422, str(exc)) from None
    try:
        content = render_ledger(snapshot, format)
    except Exception:
        logger.warning('output_operation kind=case_ledger format=%s outcome=failed', format)
        raise
    logger.info('output_operation kind=case_ledger format=%s outcome=generated elapsed_ms=%d',
                format, round((perf_counter() - started) * 1000))
    return Response(content, media_type=(
        'text/csv; charset=utf-8' if format == 'csv' else
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
        headers={'Content-Disposition': f'attachment; filename="case-ledger.{format}"',
                 'Cache-Control': 'no-store', 'X-Result-Content-SHA256': snapshot['content_sha256']})
