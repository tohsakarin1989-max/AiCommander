"""v3.1 生产地图数据治理 API。"""
from __future__ import annotations

import csv
import zipfile
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.map_foundation import MapImportTemplate, MapIngestRun, MapSource, OperationalArea
from app.services.map_foundation_service import MAX_UPLOAD_BYTES, MapFoundationService


router = APIRouter()


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
    if code in {"source_key_exists", "operational_area_code_exists"}:
        status = 409
    elif code.endswith("not_found"):
        status = 404
    elif code == "file_too_large":
        status = 413
    elif code in {"unsupported_file_type", "empty_file", "missing_header", "sheet_not_found"}:
        status = 400
    else:
        status = 422
    return HTTPException(status_code=status, detail=messages.get(code, str(exc).split("|", 1)[-1]))


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
    _require_admin(request)
    try:
        source = MapFoundationService.create_source(db, payload.model_dump())
    except ValueError as exc:
        raise _service_error(exc) from exc
    return MapFoundationService.source_to_dict(db, source)


@router.get("/map-sources")
def list_map_sources(
    request: Request,
    operational_area_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _require_admin(request)
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
    _require_admin(request)
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
    _require_admin(request)
    query = db.query(MapImportTemplate).filter(MapImportTemplate.is_active.is_(True))
    if source_id is not None:
        query = query.filter(MapImportTemplate.source_id == source_id)
    return [
        MapFoundationService.template_to_dict(item)
        for item in query.order_by(MapImportTemplate.id.desc()).all()
    ]


@router.post("/map-sources/{source_id}/preview")
async def preview_map_source(
    source_id: int,
    request: Request,
    file: UploadFile = File(...),
    template_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(request)
    filename, content = await _read_upload(file)
    try:
        return MapFoundationService.preview(
            db,
            source_id=source_id,
            filename=filename,
            content=content,
            template_id=template_id,
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
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    principal = _require_admin(request)
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
        )
    except (UnicodeDecodeError, InvalidFileException, csv.Error, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=400, detail="文件无法解析") from exc
    except ValueError as exc:
        raise _service_error(exc) from exc
    response.status_code = 200 if replay else 201
    return MapFoundationService.run_to_dict(run, idempotent_replay=replay)


@router.get("/map-ingest-runs/{run_id}")
def get_map_ingest_run(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(request)
    run = db.query(MapIngestRun).filter(MapIngestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    return MapFoundationService.run_to_dict(run)


@router.get("/map-conflicts")
def list_map_conflicts(
    request: Request,
    source_id: int | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _require_admin(request)
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
    _require_admin(request)
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
