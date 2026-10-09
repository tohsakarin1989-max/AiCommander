"""v3.1 生产地图数据治理 API。"""
from __future__ import annotations

import csv
import json
import zipfile
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.map_foundation import MapImportTemplate, MapIngestRun, MapSource, OperationalArea
from app.services.map_foundation_service import MAX_UPLOAD_BYTES, MapFoundationService
from app.services.road_public_alias_service import AliasDecision
from app.services.road_new_geometry import NewRoadGeometryEvidence


router = APIRouter()


def _road_admin(request: Request):
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(401, "请先登录")
    if principal.role != "admin":
        raise HTTPException(403, "仅地图管理员可管理内部道路")
    return principal


def _alias_source(db, source_id, import_id, feature_id, *, write=False):
    from app.models.internal_roads import InternalRoadImport
    from app.services.internal_road_service import authorized_source
    authorized_source(db, source_id, write=write)
    batch = db.query(InternalRoadImport).filter_by(id=import_id, source_id=source_id).first()
    if batch is None or not any(feature['id'] == feature_id and feature['properties']['kind'] == 'road'
                                for feature in batch.features):
        raise LookupError('road_alias_source_unavailable')


@router.post('/map-sources/{source_id}/roads/public-aliases')
def create_road_public_alias(source_id: int, payload: AliasDecision, request: Request,
                             db: Session = Depends(get_db)):
    from app.services.road_public_alias_service import record_alias_decision, describe_alias
    _road_admin(request)
    try:
        _alias_source(db, source_id, payload.import_id, payload.feature_id, write=True)
        record, created = record_alias_decision(db, payload)
        result = describe_alias(record)
        db.commit()
    except PermissionError:
        db.rollback()
        raise HTTPException(403, '缺少道路来源写入权限') from None
    except LookupError:
        db.rollback()
        raise HTTPException(404, '道路来源或要素不存在或不可访问') from None
    except ValueError as error:
        db.rollback()
        conflict = str(error) in {'road_alias_request_conflict', 'road_alias_review_changed', 'road_alias_concurrent_review'}
        raise HTTPException(409 if conflict else 422, '道路关联状态已变化，请刷新核验' if conflict else '道路关联参数不适用') from None
    return Response(json.dumps({**result, 'created': created}, ensure_ascii=False),
                    status_code=201 if created else 200, media_type='application/json',
                    headers={'Cache-Control': 'no-store'})


@router.get('/map-sources/{source_id}/roads/imports/{import_id}/features/{feature_id}/public-aliases')
def list_road_public_aliases(source_id: int, import_id: int, feature_id: str, request: Request,
                             public_source_sha256: str = Query(pattern='^[a-f0-9]{64}$'),
                             limit: int = Query(20, ge=1, le=100), before_id: int | None = Query(None, gt=0),
                             db: Session = Depends(get_db)):
    from app.services.road_public_alias_service import alias_history
    _road_admin(request)
    try:
        _alias_source(db, source_id, import_id, feature_id)
        result = alias_history(db, import_id=import_id, feature_id=feature_id,
            public_source_sha256=public_source_sha256, limit=limit, before_id=before_id)
    except PermissionError:
        raise HTTPException(403, '缺少道路来源读取权限') from None
    except LookupError:
        raise HTTPException(404, '道路来源或要素不存在或不可访问') from None
    except ValueError:
        raise HTTPException(422, '道路关联查询参数不适用') from None
    return Response(json.dumps(result, ensure_ascii=False), media_type='application/json',
                    headers={'Cache-Control': 'no-store'})


class EntranceConnectionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    road_import_id: int = Field(gt=0)
    road_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["connected", "disconnected", "unknown"]
    facility_asset_id: int | None = Field(default=None, gt=0)


class InternalRoadReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    previous_review_id: int | None = Field(default=None, gt=0)
    decision: Literal["verified", "rejected", "pending_verification"]
    note: str = Field(min_length=1, max_length=2000)
    evidence_reference: str = Field(min_length=1, max_length=500)
    connection_evidence: EntranceConnectionEvidence | NewRoadGeometryEvidence | None = None


@router.post("/map-sources/{source_id}/roads/imports/{import_id}/features/{feature_id}/reviews")
def review_internal_road_feature(source_id: int, import_id: int, feature_id: str,
                                 payload: InternalRoadReviewCreate, request: Request,
                                 db: Session = Depends(get_db)):
    from app.services.internal_road_service import RoadReviewConflict, review_feature

    principal = _road_admin(request)
    try:
        data = payload.model_dump()
        if payload.connection_evidence is not None:
            data['connection_evidence'] = payload.connection_evidence.model_dump(exclude_none=True)
        result, created = review_feature(db, source_id, import_id, feature_id, data, principal.user_id)
        db.commit()
    except PermissionError:
        raise HTTPException(403, "缺少道路来源写入权限") from None
    except LookupError:
        raise HTTPException(404, "道路版本或要素不存在或不可访问") from None
    except RoadReviewConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError:
        raise HTTPException(422, "道路来源不允许核验") from None
    return Response(content=json.dumps({**result, "created": created}, ensure_ascii=False),
                    status_code=201 if created else 200, media_type="application/json",
                    headers={"Cache-Control": "no-store"})


@router.post("/map-sources/{source_id}/roads/ingest")
async def ingest_internal_road_source(source_id: int, request: Request, db: Session = Depends(get_db)):
    from app.services.internal_road_import import MAX_ROAD_UPLOAD_BYTES
    from app.services.internal_road_service import authorized_source, ingest_roads

    principal = _road_admin(request)
    try:
        authorized_source(db, source_id, write=True)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_ROAD_UPLOAD_BYTES:
                raise HTTPException(413, "道路导入数据超过2MiB")
        result, created = ingest_roads(db, source_id, json.loads(raw), principal.user_id)
        db.commit()
    except PermissionError:
        raise HTTPException(403, "缺少道路来源写入权限") from None
    except LookupError:
        raise HTTPException(404, "来源不存在或不可访问") from None
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(422, "道路来源或数据无效，请先预检并修正全部错误") from None
    return Response(content=json.dumps({**result, "created": created}, ensure_ascii=False, allow_nan=False),
                    status_code=201 if created else 200, media_type="application/json",
                    headers={"Cache-Control": "no-store"})


@router.get("/map-sources/{source_id}/roads/imports")
def list_internal_road_imports(source_id: int, request: Request, db: Session = Depends(get_db),
                               before_id: int | None = Query(None, gt=0), limit: int = Query(20, ge=1, le=100)):
    from app.services.internal_road_service import list_imports

    _road_admin(request)
    try:
        result = list_imports(db, source_id, before_id, limit)
    except PermissionError:
        raise HTTPException(403, "缺少有效数据范围") from None
    except (LookupError, ValueError):
        raise HTTPException(404, "来源不存在或不可访问") from None
    return Response(content=json.dumps(result, ensure_ascii=False), media_type="application/json",
                    headers={"Cache-Control": "no-store"})


@router.get("/map-sources/{source_id}/roads/imports/{import_id}/features/{feature_id}/reviews")
def get_internal_road_reviews(source_id: int, import_id: int, feature_id: str, request: Request,
                              db: Session = Depends(get_db), before_id: int | None = Query(None, gt=0),
                              limit: int = Query(20, ge=1, le=100)):
    from app.services.internal_road_service import review_history

    _road_admin(request)
    try:
        result = review_history(db, source_id, import_id, feature_id, before_id, limit)
    except PermissionError:
        raise HTTPException(403, "缺少有效数据范围") from None
    except (LookupError, ValueError):
        raise HTTPException(404, "道路版本或要素不存在或不可访问") from None
    return Response(content=json.dumps(result, ensure_ascii=False), media_type="application/json",
                    headers={"Cache-Control": "no-store"})


@router.get("/map-sources/{source_id}/roads/compare")
def compare_internal_road_imports(source_id: int, request: Request,
                                  before_id: int = Query(..., gt=0), after_id: int = Query(..., gt=0),
                                  db: Session = Depends(get_db)):
    from app.services.internal_road_service import compare_imports

    _road_admin(request)
    try:
        result = compare_imports(db, source_id, before_id, after_id)
    except PermissionError:
        raise HTTPException(403, "缺少有效数据范围") from None
    except (LookupError, ValueError):
        raise HTTPException(404, "来源或比较版本不存在或不可访问") from None
    return Response(content=json.dumps(result, ensure_ascii=False), media_type="application/json",
                    headers={"Cache-Control": "no-store"})


@router.get("/map-sources/{source_id}/roads/catalog")
def internal_road_catalog(source_id: int, request: Request, db: Session = Depends(get_db),
                          after_feature: str | None = Query(None, max_length=100),
                          limit: int = Query(20, ge=1, le=100)):
    from app.services.internal_road_service import road_catalog

    _road_admin(request)
    try:
        result = road_catalog(db, source_id, after_feature, limit)
    except PermissionError:
        raise HTTPException(403, "缺少有效数据范围") from None
    except (LookupError, ValueError):
        raise HTTPException(404, "来源不存在或不可访问") from None
    return Response(content=json.dumps(result, ensure_ascii=False), media_type="application/json",
                    headers={"Cache-Control": "no-store"})


@router.get("/map-sources/{source_id}/roads/imports/{import_id}")
def get_internal_road_import(source_id: int, import_id: int, request: Request, db: Session = Depends(get_db)):
    from app.services.internal_road_service import read_import

    _road_admin(request)
    try:
        result = read_import(db, source_id, import_id)
    except PermissionError:
        raise HTTPException(403, "缺少有效数据范围") from None
    except (LookupError, ValueError):
        raise HTTPException(404, "道路版本不存在或不可访问") from None
    return Response(content=json.dumps(result, ensure_ascii=False, allow_nan=False),
                    media_type="application/json", headers={"Cache-Control": "no-store"})


@router.post("/map-sources/{source_id}/roads/preview")
async def preview_internal_road_source(source_id: int, request: Request, db: Session = Depends(get_db)):
    from app.services.internal_road_import import MAX_ROAD_UPLOAD_BYTES, preview_internal_roads

    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(401, "请先登录")
    if principal.role != "admin":
        raise HTTPException(403, "仅地图管理员可预检内部道路")
    if "authorized_area_ids" not in db.info:
        raise HTTPException(403, "缺少有效数据范围")
    source = db.query(MapSource).filter(MapSource.id == source_id, MapSource.status == "active").first()
    if source is None:
        raise HTTPException(404, "来源不存在或不可访问")
    if source.source_type == "public_map":
        raise HTTPException(409, "内部道路资料不能放入公共地图来源")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_ROAD_UPLOAD_BYTES:
            raise HTTPException(413, "道路导入数据超过2MiB")
    try:
        result = preview_internal_roads(json.loads(raw))
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(422, "道路数据格式或坐标声明不合法，请检查输入范围") from None
    return Response(content=json.dumps({**result, "source_id": source.id, "operational_area_id": source.operational_area_id},
                                      ensure_ascii=False, allow_nan=False), media_type="application/json",
                    headers={"Cache-Control": "no-store"})


class MapSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_key: str = Field(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=200)
    source_type: Literal["ledger", "manual", "internal_gis", "public_map"]
    trust_rank: int | None = Field(default=None, ge=0, le=100)
    operational_area_id: int | None = None
    description: str | None = Field(default=None, max_length=1000)
    configuration: dict[str, Any] | None = None


class OperationalAreaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=200)
    boundary: list[float] | dict[str, Any] | None = None
    is_default: bool = False
    status: Literal["active", "inactive"] = "active"


class OperationalAreaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    boundary: list[float] | dict[str, Any] | None = None
    is_default: bool | None = None
    status: Literal["active", "inactive"] | None = None


class MapImportTemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: int
    name: str = Field(min_length=1, max_length=200)
    sheet_name: str | None = Field(default=None, max_length=200)
    header_row: int = Field(default=1, ge=1, le=100)
    field_mapping: dict[str, str]
    coordinate_system: Literal[
        "wgs84",
        "cgcs2000_geographic",
        "gcj02",
        "bd09",
        "cgcs2000_gauss_kruger",
        "local_control_points",
    ]
    axis_order: Literal["lon_lat", "lat_lon"] = "lon_lat"
    coordinate_unit: Literal["degree", "meter"] = "degree"
    transformation: dict[str, float] | None = None
    expected_structure: dict[str, Any] | None = None
    field_units: dict[str, str] | None = None

    @field_validator("field_mapping")
    @classmethod
    def validate_field_mapping(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 50:
            raise ValueError("字段映射不能超过50项")
        required = {"name", "asset_type", "longitude", "latitude"}
        if not required.issubset(value):
            raise ValueError("字段映射必须包含名称、类型、经度和纬度")
        cleaned = {str(key).strip(): str(item).strip() for key, item in value.items()}
        if any(not item or len(item) > 200 for item in cleaned.values()):
            raise ValueError("字段映射不能包含空列名")
        return cleaned


class ConflictResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["reject", "retry"]
    note: str | None = Field(default=None, max_length=1000)


class MapRowCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: int = Field(gt=0)
    values: dict[str, Any]


class MapRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: str = Field(min_length=8, max_length=80)
    template_id: int | None = Field(default=None, gt=0)
    rows: list[MapRowCorrection] = Field(min_length=1, max_length=200)
    plan_token: str | None = Field(default=None, min_length=64, max_length=64)
    note: str | None = Field(default=None, max_length=1000)


class MapFieldSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    group: Literal["geometry", "water_cut", "production", "details"]
    request_id: str = Field(min_length=8, max_length=80)
    note: str = Field(min_length=1, max_length=1000)
    expected_asset_version: int = Field(ge=0)
    expected_decision_id: int | None


def _require_admin(request: Request):
    principal = getattr(request.state, "principal", None)
    if principal is None and settings.AUTH_REQUIRED:
        raise HTTPException(status_code=401, detail="请先登录")
    role = getattr(principal, "role", "admin" if not settings.AUTH_REQUIRED else None)
    if role != "admin":
        raise HTTPException(status_code=403, detail="仅地图管理员可以维护生产地图来源")
    return principal


def _principal_user_id(principal) -> int | None:
    return getattr(principal, "user_id", getattr(principal, "id", None))


def _require_data_manager(request: Request, db: Session):
    """Narrow even reads to managed areas; normal write scope is insufficient."""
    principal = getattr(request.state, 'principal', None)
    if principal is None or getattr(principal, 'role', None) == 'admin':
        return _require_admin(request)
    areas = tuple(area for area, level in (db.info.get('area_access_levels') or {}).items() if level == 'manage')
    if getattr(principal, 'role', None) != 'analyst' or not areas:
        raise HTTPException(403, '需要明确的厂区资料维护权限，普通编辑权限不足')
    db.info['authorized_area_ids'] = areas
    db.info['default_operational_area_id'] = areas[0]
    return principal


@router.get('/map-maintenance-scope')
def map_maintenance_scope(request: Request, db: Session = Depends(get_db)):
    principal = _require_data_manager(request, db)
    query = db.query(OperationalArea).filter_by(status='active')
    allowed = db.info.get('authorized_area_ids')
    if allowed is not None:
        query = query.filter(OperationalArea.id.in_(allowed))
    return {'areas': [MapFoundationService.area_to_dict(area) for area in query.order_by(OperationalArea.id)],
            'can_publish_map': getattr(principal, 'role', 'admin') == 'admin',
            'can_download_original': getattr(principal, 'role', 'admin') == 'admin',
            'boundary': '资料维护不授予地图发布、整份原件下载、系统配置或道路通行许可'}


def _service_error(exc: ValueError) -> HTTPException:
    code = str(exc).split("|", 1)[0]
    messages = {
        "source_key_exists": "地图来源标识已存在",
        "source_not_found": "地图来源不存在或已停用",
        "operational_area_not_found": "厂区不存在或已停用",
        "operational_area_code_exists": "厂区代码已存在",
        "invalid_operational_area_boundary": "厂区边界必须是有效经纬度范围或多边形",
        "default_area_must_remain_active": "默认厂区必须保持启用",
        "default_area_cannot_be_unset": "请先把其他厂区设为默认",
        "template_not_found": "导入模板不存在、已停用或不属于该来源",
        "transformation_required": "该坐标系必须配置经控制点核验的转换参数",
        "invalid_transformation": "坐标转换参数无效",
        "unsupported_coordinate_system": "不支持的坐标系",
        "conflict_not_found": "异常记录不存在或已经处理",
        "unsupported_resolution": "不支持的处理决定",
    }
    if isinstance(exc, PermissionError):
        status = 403
    elif code in {"source_key_exists", "operational_area_code_exists", "plan_stale", "template_drift",
                "retry_request_conflict", "retry_row_superseded", "retry_successful_row_forbidden",
                "retry_parent_stale", "retry_identifier_taken"}:
        status = 409
    elif code.endswith("not_found"):
        status = 404
    elif code == "file_too_large":
        status = 413
    elif code in {"unsupported_file_type", "empty_file", "missing_header", "sheet_not_found"}:
        status = 400
    else:
        status = 422
    message = messages.get(code, str(exc).split("|", 1)[-1])
    detail = {"code": code, "message": message} if code in {
        "plan_stale", "template_drift", "retry_request_conflict", "retry_row_superseded", "retry_successful_row_forbidden",
        "retry_parent_stale", "retry_identifier_taken"
    } else message
    return HTTPException(status_code=status, detail=detail)


async def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    filename = (file.filename or "").strip()
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    # 常量定义在服务模块，parse_table 会再次执行同一套限制校验。
    return filename, content


@router.get("/operational-areas")
def list_operational_areas(
    request: Request,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _require_admin(request)
    areas = db.query(OperationalArea).order_by(OperationalArea.id).all()
    return [MapFoundationService.area_to_dict(item) for item in areas]


@router.post("/operational-areas", status_code=201)
def create_operational_area(
    payload: OperationalAreaCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(request)
    try:
        area = MapFoundationService.create_area(db, payload.model_dump())
    except ValueError as exc:
        raise _service_error(exc) from exc
    return MapFoundationService.area_to_dict(area)


@router.put("/operational-areas/{area_id}")
def update_operational_area(
    area_id: int,
    payload: OperationalAreaUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(request)
    try:
        area = MapFoundationService.update_area(
            db,
            area_id,
            payload.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise _service_error(exc) from exc
    return MapFoundationService.area_to_dict(area)


@router.post("/map-sources", status_code=201)
def create_map_source(
    payload: MapSourceCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_data_manager(request, db)
    try:
        from app.database import require_area_manage_access
        data = payload.model_dump()
        if db.info.get('area_access_levels') is not None:
            data['operational_area_id'] = require_area_manage_access(db, data.get('operational_area_id'))
        source = MapFoundationService.create_source(db, data)
    except (ValueError, PermissionError) as exc:
        raise _service_error(exc) from exc
    return MapFoundationService.source_to_dict(db, source)


@router.get("/map-sources")
def list_map_sources(
    request: Request,
    operational_area_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _require_data_manager(request, db)
    query = db.query(MapSource)
    if operational_area_id is not None:
        query = query.filter(MapSource.operational_area_id == operational_area_id)
    return [
        MapFoundationService.source_to_dict(db, item)
        for item in query.order_by(MapSource.id.desc()).all()
    ]


@router.post("/map-import-templates", status_code=201)
def create_map_import_template(
    payload: MapImportTemplateCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_data_manager(request, db)
    try:
        template = MapFoundationService.create_template(db, payload.model_dump())
    except ValueError as exc:
        raise _service_error(exc) from exc
    return MapFoundationService.template_to_dict(template)


@router.get("/map-import-templates")
def list_map_import_templates(
    request: Request,
    source_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _require_data_manager(request, db)
    query = db.query(MapImportTemplate).filter(MapImportTemplate.is_active.is_(True))
    if source_id is not None:
        query = query.filter(MapImportTemplate.source_id == source_id)
    return [
        MapFoundationService.template_to_dict(item)
        for item in query.order_by(MapImportTemplate.id.desc()).all()
    ]


@router.post("/map-sources/{source_id}/inspect")
async def inspect_map_table(source_id: int, request: Request, file: UploadFile = File(...),
                            sheet_name: str | None = Query(default=None, max_length=200),
                            header_row: int = Query(default=1, ge=1, le=100),
                            db: Session = Depends(get_db)):
    _require_data_manager(request, db)
    filename, content = await _read_upload(file)
    from app.services.map_ingest_tables import inspect_table
    try:
        return inspect_table(db, source_id, filename, content, sheet_name=sheet_name, header_row=header_row)
    except (UnicodeDecodeError, InvalidFileException, csv.Error, zipfile.BadZipFile) as exc:
        raise HTTPException(400, "文件无法解析") from exc
    except ValueError as exc:
        raise _service_error(exc) from exc


@router.post("/map-sources/{source_id}/preview")
async def preview_map_source(
    source_id: int,
    request: Request,
    file: UploadFile = File(...),
    template_id: int | None = Query(default=None),
    sheet_name: str | None = Query(default=None, max_length=200),
    header_row: int = Query(default=1, ge=1, le=100),
    ledger_declaration: str | None = Form(default=None, max_length=3000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_data_manager(request, db)
    filename, content = await _read_upload(file)
    try:
        return MapFoundationService.preview(
            db,
            source_id=source_id,
            filename=filename,
            content=content,
            template_id=template_id,
            sheet_name=sheet_name, header_row=header_row,
            ledger_declaration=ledger_declaration,
        )
    except (UnicodeDecodeError, InvalidFileException, csv.Error, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=400, detail="文件无法解析") from exc
    except ValueError as exc:
        raise _service_error(exc) from exc


@router.post("/map-sources/{source_id}/ingest", status_code=201)
async def ingest_map_source(
    source_id: int,
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    template_id: int = Query(...),
    source_revision: str | None = Query(default=None, max_length=200),
    plan_token: str | None = Form(default=None, min_length=64, max_length=64),
    ledger_declaration: str | None = Form(default=None, max_length=3000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _require_data_manager(request, db)
    filename, content = await _read_upload(file)
    try:
        run, replay = MapFoundationService.ingest(
            db,
            source_id=source_id,
            template_id=template_id,
            filename=filename,
            content=content,
            source_revision=source_revision,
            created_by=_principal_user_id(principal),
            plan_token=plan_token or request.query_params.get("plan_token"),
            ledger_declaration=ledger_declaration,
        )
    except (UnicodeDecodeError, InvalidFileException, csv.Error, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=400, detail="文件无法解析") from exc
    except (ValueError, PermissionError) as exc:
        raise _service_error(exc) from exc
    response.status_code = 200 if replay else 201
    return MapFoundationService.run_to_dict(run, idempotent_replay=replay)


@router.get("/map-ingest-runs/{run_id}")
def get_map_ingest_run(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_data_manager(request, db)
    from app.services.map_ingest_execution import get_run
    try:
        run = get_run(db, run_id)
    except ValueError as exc:
        raise _service_error(exc) from exc
    return MapFoundationService.run_to_dict(run)


@router.post("/map-sources/{source_id}/jobs", status_code=202)
async def prepare_map_ingest_job(source_id: int, request: Request, response: Response,
                                template_id: int = Query(gt=0), file: UploadFile = File(...),
                                source_revision: str | None = Query(default=None, max_length=200),
                                input_kind: Literal['file', 'clipboard'] = Query(default='file'),
                                ledger_declaration: str | None = Form(default=None, max_length=3000),
                                db: Session = Depends(get_db)):
    principal = _require_data_manager(request, db)
    filename, content = await _read_upload(file)
    from app.services.map_ingest_jobs import enqueue
    try:
        run, replay = enqueue(db, source_id=source_id, template_id=template_id, filename=filename,
            content=content, source_revision=source_revision, actor_id=_principal_user_id(principal),
            ledger_declaration=ledger_declaration, input_kind=input_kind)
        response.status_code = 200 if replay else 202
        return MapFoundationService.run_to_dict(run, idempotent_replay=replay)
    except (UnicodeDecodeError, InvalidFileException, csv.Error, zipfile.BadZipFile) as exc:
        raise HTTPException(400, "文件无法解析") from exc
    except (ValueError, PermissionError) as exc:
        raise _service_error(exc) from exc


@router.get("/map-ingest-runs/{run_id}/job-preview")
def get_map_job_preview(run_id: str, request: Request, db: Session = Depends(get_db)):
    _require_data_manager(request, db)
    from app.services.map_ingest_jobs import preview_job
    try:
        return preview_job(db, run_id)
    except ValueError as exc:
        raise _service_error(exc) from exc


class MapJobControl(BaseModel):
    action: Literal['pause', 'resume', 'cancel', 'adopt']
    plan_token: str | None = Field(default=None, min_length=64, max_length=64)


class MapIssueResolution(BaseModel):
    state: Literal['needs_information', 'checked_no_change', 'corrected']
    expected_state: Literal['reported', 'needs_information', 'checked_no_change', 'corrected']
    note: str = Field(min_length=1, max_length=2000)
    request_id: str = Field(min_length=8, max_length=80)
    source_reference: dict[str, Any] | None = None


@router.get('/map-data-issues')
def list_map_issue_work(request: Request, source_id: int | None = None, operational_area_id: int | None = None,
                        state: Literal['reported', 'needs_information', 'checked_no_change', 'corrected'] | None = None,
                        page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                        db: Session = Depends(get_db)):
    _require_data_manager(request, db)
    from app.services.map_data_issues import list_work
    return list_work(db, source_id=source_id, area_id=operational_area_id, state=state, page=page, page_size=page_size)


@router.post('/map-data-issues/{issue_id}/resolve')
def resolve_map_issue_work(issue_id: int, payload: MapIssueResolution, request: Request, db: Session = Depends(get_db)):
    principal = _require_data_manager(request, db)
    from app.services.map_data_issues import resolve_issue
    try:
        return resolve_issue(db, issue_id, payload.model_dump(), actor_id=_principal_user_id(principal))
    except LookupError as exc:
        raise HTTPException(404, '资料标注或关联来源当前不可访问') from exc
    except (ValueError, PermissionError) as exc:
        raise _service_error(exc) from exc


@router.post("/map-ingest-runs/{run_id}/control")
def control_map_job(run_id: str, payload: MapJobControl, request: Request, db: Session = Depends(get_db)):
    principal = _require_data_manager(request, db)
    from app.services.map_ingest_jobs import control
    try:
        return MapFoundationService.run_to_dict(control(db, run_id, action=payload.action,
            actor_id=_principal_user_id(principal), plan_token=payload.plan_token))
    except (ValueError, PermissionError) as exc:
        raise _service_error(exc) from exc


@router.get("/map-import-fields")
def map_import_fields(request: Request, db: Session = Depends(get_db)):
    _require_data_manager(request, db)
    from app.services.map_import_contract import field_contract
    return field_contract()


@router.get("/map-ingest-runs/{run_id}/ledger-comparison")
def get_map_ledger_comparison(run_id: str, request: Request, db: Session = Depends(get_db)):
    _require_data_manager(request, db)
    from app.services.map_ledger_completeness import read_comparison
    try:
        return read_comparison(db, run_id)
    except ValueError as exc:
        raise _service_error(exc) from exc


@router.get("/map-import-example")
def map_import_example(request: Request, db: Session = Depends(get_db)):
    _require_data_manager(request, db)
    from app.services.map_import_contract import example_csv
    return Response(content=example_csv(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="production-ledger-example.csv"', "Cache-Control": "no-store"})


@router.get("/map-ingest-runs")
def list_map_ingest_runs(request: Request, source_id: int | None = None,
                         offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100),
                         db: Session = Depends(get_db)):
    _require_data_manager(request, db)
    from app.services.map_ingest_execution import list_runs
    return list_runs(db, source_id=source_id, offset=offset, limit=limit)


@router.get("/map-ingest-runs/{run_id}/claims")
def list_map_ingest_claims(run_id: str, request: Request, classification: Literal[
    "new", "updated", "unchanged", "identity_pending", "conflict", "failed"] | None = None,
    offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db)):
    _require_data_manager(request, db)
    from app.services.map_ingest_execution import list_claims
    try:
        return list_claims(db, run_id, classification=classification, offset=offset, limit=limit)
    except ValueError as exc:
        raise _service_error(exc) from exc


@router.post("/map-ingest-runs/{run_id}/retry-preview")
def preview_map_ingest_retry(run_id: str, payload: MapRetryRequest, request: Request, db: Session = Depends(get_db)):
    _require_data_manager(request, db)
    from app.services.map_ingest_execution import retry_rows
    try:
        return retry_rows(db, run_id, payload.model_dump(), preview=True)
    except ValueError as exc:
        raise _service_error(exc) from exc


@router.post("/map-ingest-runs/{run_id}/retry", status_code=201)
def retry_map_ingest(run_id: str, payload: MapRetryRequest, request: Request, response: Response,
                     db: Session = Depends(get_db)):
    principal = _require_data_manager(request, db)
    from app.services.map_ingest_execution import retry_rows
    try:
        run, replay = retry_rows(db, run_id, payload.model_dump(), created_by=_principal_user_id(principal))
    except (ValueError, PermissionError) as exc:
        raise _service_error(exc) from exc
    response.status_code = 200 if replay else 201
    return MapFoundationService.run_to_dict(run, idempotent_replay=replay)


@router.get("/map-conflicts/{claim_id}/field-decision-preview")
def preview_field_selection(claim_id: int, request: Request,
    group: Literal["geometry", "water_cut", "production", "details"], db: Session = Depends(get_db)):
    _require_data_manager(request, db)
    from app.services.map_ingest_execution import field_decision_preview
    try:
        return field_decision_preview(db, claim_id, group)
    except (ValueError, PermissionError) as exc:
        raise _service_error(exc) from exc


@router.post("/map-conflicts/{claim_id}/field-decision", status_code=201)
def select_field_group(claim_id: int, payload: MapFieldSelection, request: Request, response: Response,
                       db: Session = Depends(get_db)):
    principal = _require_data_manager(request, db)
    from app.services.map_ingest_execution import decide_field_group
    try:
        run, replay = decide_field_group(db, claim_id, payload.model_dump(), actor_id=_principal_user_id(principal))
    except (ValueError, PermissionError) as exc:
        raise _service_error(exc) from exc
    response.status_code = 200 if replay else 201
    return MapFoundationService.run_to_dict(run, idempotent_replay=replay)


@router.get("/map-conflicts")
def list_map_conflicts(
    request: Request,
    source_id: int | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _require_data_manager(request, db)
    return [
        MapFoundationService.claim_to_dict(item)
        for item in MapFoundationService.list_conflicts(db, source_id=source_id)[:limit]
    ]


@router.post("/map-conflicts/{claim_id}/resolve")
def resolve_map_conflict(
    claim_id: int,
    payload: ConflictResolution,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_data_manager(request, db)
    try:
        claim = MapFoundationService.resolve_conflict(
            db,
            claim_id,
            decision=payload.decision,
            note=payload.note,
        )
    except ValueError as exc:
        raise _service_error(exc) from exc
    return MapFoundationService.claim_to_dict(claim)
