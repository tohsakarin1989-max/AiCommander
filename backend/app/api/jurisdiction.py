"""辖区风险底座 API。"""
import csv
import io
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

import httpx
import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models.jurisdiction import JurisdictionAsset, JurisdictionFeedback
from app.services.jurisdiction_service import JurisdictionService
from app.services.well_attention_service import WellAttentionService

router = APIRouter()

ALLOWED_TABLE_EXTENSIONS = {".csv", ".xlsx", ".xlsm", ".xltx", ".xltm"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _maintain(db, operation, *args, **kwargs):
    """Scope is checked again by the write service, not by a menu or role alone."""
    try:
        return operation(db, *args, **kwargs)
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail='仅可维护已授权厂区的地图资料') from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404 if str(exc) == 'asset_not_found' else 400, detail=str(exc)) from exc


class JurisdictionAssetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    operational_area_id: Optional[int] = Field(default=None, ge=1)
    external_id: Optional[str] = Field(default=None, max_length=200)
    name: str = Field(..., min_length=1, max_length=200, description="要素名称")
    asset_type: str = Field(..., min_length=1, max_length=50, description="要素类型，如 well/camera/patrol_point；road/village 应优先来自地图参考数据")
    geometry_type: str = Field("point", max_length=20, description="point/line/polygon")
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    geometry: Optional[Dict[str, Any]] = None
    address: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = Field(default=None, max_length=2000)
    source: str = Field("manual", max_length=50, description="manual/map/import")
    status: str = Field("active", max_length=20, description="active/inactive")
    risk_level: Optional[int] = Field(None, ge=1, le=5)
    confidence_score: Optional[float] = Field(None, ge=0, le=1)
    verified: bool = False
    tags: Optional[List[str]] = Field(default=None, max_length=50)
    attributes: Optional[Dict[str, Any]] = None


class JurisdictionAssetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    external_id: Optional[str] = Field(default=None, max_length=200)
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    asset_type: Optional[str] = Field(default=None, min_length=1, max_length=50)
    geometry_type: Optional[str] = Field(default=None, max_length=20)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    geometry: Optional[Dict[str, Any]] = None
    address: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = Field(default=None, max_length=2000)
    source: Optional[str] = Field(default=None, max_length=50)
    status: Optional[str] = Field(default=None, max_length=20)
    risk_level: Optional[int] = Field(None, ge=1, le=5)
    confidence_score: Optional[float] = Field(None, ge=0, le=1)
    verified: Optional[bool] = None
    tags: Optional[List[str]] = Field(default=None, max_length=50)
    attributes: Optional[Dict[str, Any]] = None


class JurisdictionAssetBulkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: List[JurisdictionAssetCreate] = Field(min_length=1, max_length=1000)


class GeoJsonImportRequest(BaseModel):
    geojson: Dict[str, Any]
    source: str = "map"
    operational_area_id: Optional[int] = Field(default=None, ge=1)


class PublicMapSyncRequest(BaseModel):
    south: Optional[float] = Field(None, description="南边界纬度")
    west: Optional[float] = Field(None, description="西边界经度")
    north: Optional[float] = Field(None, description="北边界纬度")
    east: Optional[float] = Field(None, description="东边界经度")
    center_lat: Optional[float] = Field(None, description="中心点纬度；不填则按已有案件/资产坐标推断")
    center_lng: Optional[float] = Field(None, description="中心点经度；不填则按已有案件/资产坐标推断")
    radius_km: float = Field(6.0, ge=0.2, le=20.0, description="自动拉取半径，默认 6 公里")
    max_features: int = Field(160, ge=1, le=500, description="最多入库的公共地图要素数")


class WellAttentionRefreshRequest(BaseModel):
    days_back: int = Field(30, ge=1, le=365)
    radius_km: float = Field(1.0, ge=0.1, le=5.0)


class FacilitySearchMatch(BaseModel):
    kind: Literal["current_name", "external_id", "address", "historical_name", "source_alias"]
    value: str
    version_id: Optional[int] = None
    identity_id: Optional[int] = None
    source_id: Optional[int] = None


class JurisdictionAssetResponse(BaseModel):
    id: int
    operational_area_id: Optional[int]
    external_id: Optional[str]
    name: str
    asset_type: str
    geometry_type: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    geometry: Optional[Dict[str, Any]]
    address: Optional[str]
    description: Optional[str]
    source: Optional[str]
    status: Optional[str]
    risk_level: Optional[int]
    confidence_score: Optional[float]
    verified: Optional[bool]
    last_seen_at: Optional[datetime]
    tags: Optional[List[str]]
    attributes: Optional[Dict[str, Any]]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    search_match: Optional[FacilitySearchMatch] = None

    class Config:
        from_attributes = True


class MapDataIssueReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_group: Literal["identity", "coordinates", "water_cut", "production", "other"]
    source_claim_id: Optional[int] = Field(None, gt=0, strict=True)
    asset_version_id: Optional[int] = Field(None, gt=0, strict=True)


class JurisdictionFeedbackCreate(BaseModel):
    case_id: Optional[int] = None
    asset_id: Optional[int] = None
    feedback_type: str = Field(..., description="patrol/deployment/meeting/check/data_issue")
    adopted: bool = False
    result: Optional[str] = None
    effectiveness_score: Optional[float] = Field(None, ge=0, le=100)
    notes: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
    source_reference: Optional[MapDataIssueReference] = None


class JurisdictionFeedbackResponse(BaseModel):
    id: int
    case_id: Optional[int]
    asset_id: Optional[int]
    feedback_type: str
    adopted: bool
    result: Optional[str]
    effectiveness_score: Optional[float]
    notes: Optional[str]
    extra: Optional[Dict[str, Any]]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


@router.post("/assets", response_model=JurisdictionAssetResponse)
async def create_asset(
    payload: JurisdictionAssetCreate,
    db: Session = Depends(get_db),
) -> JurisdictionAsset:
    """录入油区业务资产、防控设施和内部路线；道路、村屯优先走地图参考导入。"""
    return _maintain(db, JurisdictionService.create_asset, payload.dict())


@router.post("/assets/bulk")
async def bulk_create_assets(
    payload: JurisdictionAssetBulkCreate,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """批量导入地图/GIS/内部台账要素，形成公共地图参考和油区业务资产。"""
    return _maintain(
        db, JurisdictionService.bulk_create_assets,
        [item.dict() for item in payload.items],
    )


@router.post("/assets/sync-public-map")
async def sync_public_map_assets(
    payload: PublicMapSyncRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """按已有案件/资产坐标自动拉取公共地图参考要素，并去重入库。"""
    if not settings.ENABLE_LEGACY_PUBLIC_MAP_SYNC:
        raise HTTPException(
            status_code=410,
            detail="内网已停用公网地图直连，请导入受控离线地图更新包",
        )
    try:
        return JurisdictionService.sync_public_map_references(
            db,
            south=payload.south,
            west=payload.west,
            north=payload.north,
            east=payload.east,
            center_lat=payload.center_lat,
            center_lng=payload.center_lng,
            radius_km=payload.radius_km,
            max_features=payload.max_features,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"公共地图服务暂不可用: {exc}") from exc


@router.post("/assets/import-geojson")
async def import_geojson_assets(
    payload: GeoJsonImportRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """导入完整 GeoJSON；身份由来源和编号决定，不按同名合并。"""
    return _maintain(
        db, JurisdictionService.import_geojson,
        payload.geojson,
        source=payload.source,
        operational_area_id=payload.operational_area_id,
    )


@router.post("/assets/import-table")
async def import_table_assets(
    file: UploadFile = File(...),
    dry_run: bool = False,
    source: str = "ledger",
    operational_area_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """兼容标准经纬度台账；特殊坐标和字段映射使用受管模板入口。"""
    filename = file.filename or ""
    lowered = filename.lower()
    if not any(lowered.endswith(ext) for ext in ALLOWED_TABLE_EXTENSIONS):
        raise HTTPException(status_code=400, detail="仅支持 CSV 或 Excel (.xlsx) 文件")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件过大，限制为 10MB")

    try:
        rows = _parse_asset_table(filename, content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"解析文件失败: {exc}") from exc

    if not rows:
        raise HTTPException(status_code=400, detail="文件中没有数据")
    return _maintain(
        db, JurisdictionService.import_tabular_assets,
        rows,
        source=source,
        dry_run=dry_run,
        operational_area_id=operational_area_id,
        filename=filename,
    )


@router.get("/assets", response_model=List[JurisdictionAssetResponse])
async def list_assets(
    asset_type: Optional[str] = None,
    source: Optional[str] = None,
    status: Optional[str] = "active",
    operational_area_id: Optional[int] = Query(default=None, ge=1),
    keyword: Optional[str] = Query(default=None, max_length=200),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> List[JurisdictionAsset]:
    """查询辖区基础要素，支持按类型、来源和状态筛选。"""
    return JurisdictionService.list_assets(
        db=db,
        asset_type=asset_type,
        source=source,
        status=status,
        operational_area_id=operational_area_id,
        keyword=keyword,
        skip=skip,
        limit=limit,
    )


@router.put("/assets/{asset_id:int}", response_model=JurisdictionAssetResponse)
async def update_asset(
    asset_id: int,
    payload: JurisdictionAssetUpdate,
    db: Session = Depends(get_db),
) -> JurisdictionAsset:
    """编辑辖区要素，供地图点位校正和台账维护使用。"""
    return _maintain(db, JurisdictionService.update_asset, asset_id, payload.dict(exclude_unset=True))


@router.delete("/assets/{asset_id:int}", response_model=JurisdictionAssetResponse)
async def deactivate_asset(
    asset_id: int,
    db: Session = Depends(get_db),
) -> JurisdictionAsset:
    """软停用辖区要素，保留历史导入和研判依据。"""
    return _maintain(db, JurisdictionService.deactivate_asset, asset_id)


@router.get("/assets/summary")
async def get_assets_summary(
    operational_area_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """获取辖区风险底座完整度概览。"""
    return JurisdictionService.summarize_assets(db, operational_area_id=operational_area_id)


@router.get("/data-quality")
async def get_data_quality(
    operational_area_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """审计业务资产完整度、坐标缺失、重复点、校验状态和公共地图参考缺口。"""
    return JurisdictionService.audit_data_quality(db, operational_area_id=operational_area_id)


@router.get("/well-attention/overview")
async def get_well_attention_overview(
    days_back: int = Query(30, ge=1, le=365),
    radius_km: float = Query(1.0, ge=0.1, le=5.0),
    operational_area_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """获取领导大屏使用的井点风险迹象热力与最新大模型研判快照。"""
    return WellAttentionService.build_overview(
        db,
        days_back=days_back,
        radius_km=radius_km,
        operational_area_id=operational_area_id,
    )


@router.post("/well-attention/refresh")
async def refresh_well_attention(
    payload: WellAttentionRefreshRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """基于最新井点和痕迹事实刷新关注区域、关注井点与布置建议。"""
    return await WellAttentionService.refresh_ai_analysis(
        db,
        days_back=payload.days_back,
        radius_km=payload.radius_km,
    )


@router.post("/feedback", response_model=JurisdictionFeedbackResponse)
async def create_feedback(
    payload: JurisdictionFeedbackCreate,
    db: Session = Depends(get_db),
) -> JurisdictionFeedback:
    """保留历史反馈；data_issue 只记录来源明确的问题，不修改设施。"""
    try:
        return JurisdictionService.record_feedback(db, payload.dict())
    except ValueError as exc:
        if str(exc).startswith("data_issue_"):
            raise HTTPException(422, "问题标注需包含本设施的有效来源引用和 1–2000 字说明") from exc
        if str(exc) in {
            "case_not_found_or_out_of_scope",
            "asset_not_found_or_out_of_scope",
        }:
            raise HTTPException(status_code=404, detail="案件或地图要素不存在") from exc
        if str(exc) == "feedback_scope_mismatch":
            raise HTTPException(status_code=409, detail="案件与地图要素不属于同一厂区") from exc
        if str(exc) == "feedback_scope_required":
            raise HTTPException(status_code=422, detail="反馈必须关联当前厂区内的案件或地图要素") from exc
        raise
    except LookupError as exc:
        raise HTTPException(404, "设施或所引用资料不存在或当前不可访问") from exc


@router.get("/data-issues")
def list_map_data_issues(
    response: Response, asset_id: int = Query(gt=0),
    page: int = Query(1, ge=1, le=10000), page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    from app.services.map_data_issues import list_issues
    response.headers["Cache-Control"] = "no-store"
    try:
        return list_issues(db, asset_id, page=page, page_size=page_size)
    except LookupError as exc:
        raise HTTPException(404, "设施不存在或当前不可访问") from exc


@router.get("/effectiveness")
async def get_effectiveness(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """汇总反馈采纳率和有效性评分，形成持续修正依据。"""
    return JurisdictionService.summarize_effectiveness(db)


def _parse_asset_table(filename: str, content: bytes) -> List[Dict[str, Any]]:
    lowered = filename.lower()
    if lowered.endswith(".csv"):
        text = content.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))

    from app.services.map_foundation_service import (
        MAX_CELL_TEXT_LENGTH,
        MAX_TABLE_COLUMNS,
        MAX_TABLE_ROWS,
        MapFoundationService,
    )

    MapFoundationService.validate_excel_archive(content)
    workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        iterator = worksheet.iter_rows(values_only=True)
        first_row = next(iterator, None)
        if first_row is None:
            return []
        if len(first_row) > MAX_TABLE_COLUMNS:
            raise ValueError("表格列数超过限制")
        headers = [str(value).strip() if value is not None else "" for value in first_row]
        rows = []
        for row_number, row in enumerate(iterator, start=2):
            if row_number > MAX_TABLE_ROWS + 1:
                raise ValueError("表格行数超过限制")
            record = {
                headers[index]: value
                for index, value in enumerate(row)
                if index < len(headers) and headers[index]
            }
            if any(isinstance(value, str) and len(value) > MAX_CELL_TEXT_LENGTH for value in record.values()):
                raise ValueError("单元格文本超过限制")
            rows.append(record)
        return rows
    finally:
        workbook.close()
