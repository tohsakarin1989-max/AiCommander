"""辖区风险底座 API。"""
import csv
import io
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.jurisdiction import JurisdictionAsset, JurisdictionFeedback
from app.services.jurisdiction_service import JurisdictionService

router = APIRouter()

ALLOWED_TABLE_EXTENSIONS = {".csv", ".xlsx", ".xlsm", ".xltx", ".xltm"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class JurisdictionAssetCreate(BaseModel):
    external_id: Optional[str] = None
    name: str = Field(..., description="要素名称")
    asset_type: str = Field(..., description="要素类型，如 well/camera/patrol_point；road/village 应优先来自地图参考数据")
    geometry_type: str = Field("point", description="point/line/polygon")
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geometry: Optional[Dict[str, Any]] = None
    address: Optional[str] = None
    description: Optional[str] = None
    source: str = Field("manual", description="manual/map/import")
    status: str = Field("active", description="active/inactive")
    risk_level: int = Field(1, ge=1, le=5)
    confidence_score: float = Field(1.0, ge=0, le=1)
    verified: bool = False
    tags: Optional[List[str]] = None
    attributes: Optional[Dict[str, Any]] = None


class JurisdictionAssetUpdate(BaseModel):
    external_id: Optional[str] = None
    name: Optional[str] = None
    asset_type: Optional[str] = None
    geometry_type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    geometry: Optional[Dict[str, Any]] = None
    address: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    risk_level: Optional[int] = Field(None, ge=1, le=5)
    confidence_score: Optional[float] = Field(None, ge=0, le=1)
    verified: Optional[bool] = None
    tags: Optional[List[str]] = None
    attributes: Optional[Dict[str, Any]] = None


class JurisdictionAssetBulkCreate(BaseModel):
    items: List[JurisdictionAssetCreate]


class GeoJsonImportRequest(BaseModel):
    geojson: Dict[str, Any]
    source: str = "map"


class PublicMapSyncRequest(BaseModel):
    south: Optional[float] = Field(None, description="南边界纬度")
    west: Optional[float] = Field(None, description="西边界经度")
    north: Optional[float] = Field(None, description="北边界纬度")
    east: Optional[float] = Field(None, description="东边界经度")
    center_lat: Optional[float] = Field(None, description="中心点纬度；不填则按已有案件/资产坐标推断")
    center_lng: Optional[float] = Field(None, description="中心点经度；不填则按已有案件/资产坐标推断")
    radius_km: float = Field(6.0, ge=0.2, le=20.0, description="自动拉取半径，默认 6 公里")
    max_features: int = Field(160, ge=1, le=500, description="最多入库的公共地图要素数")


class JurisdictionAssetResponse(BaseModel):
    id: int
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

    class Config:
        from_attributes = True


class PatrolPlanRequest(BaseModel):
    case_id: Optional[int] = None
    asset_ids: Optional[List[int]] = None
    limit: int = Field(6, ge=1, le=20)


class PatrolPlanMaterializeRequest(PatrolPlanRequest):
    officer_count: int = Field(1, ge=1, le=20)
    officer_names: Optional[str] = None
    created_by: Optional[str] = None


class JurisdictionFeedbackCreate(BaseModel):
    case_id: Optional[int] = None
    asset_id: Optional[int] = None
    feedback_type: str = Field(..., description="patrol/deployment/meeting/check")
    adopted: bool = False
    result: Optional[str] = None
    effectiveness_score: Optional[float] = Field(None, ge=0, le=100)
    notes: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


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
    return JurisdictionService.create_asset(db, payload.dict())


@router.post("/assets/bulk")
async def bulk_create_assets(
    payload: JurisdictionAssetBulkCreate,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """批量导入地图/GIS/内部台账要素，形成公共地图参考和油区业务资产。"""
    return JurisdictionService.bulk_create_assets(
        db,
        [item.dict() for item in payload.items],
    )


@router.post("/assets/sync-public-map")
async def sync_public_map_assets(
    payload: PublicMapSyncRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """按已有案件/资产坐标自动拉取公共地图参考要素，并去重入库。"""
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
    """导入 GeoJSON FeatureCollection，并按 external_id/name 去重更新。"""
    return JurisdictionService.import_geojson(db, payload.geojson, source=payload.source)


@router.post("/assets/import-table")
async def import_table_assets(
    file: UploadFile = File(...),
    dry_run: bool = False,
    source: str = "ledger",
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """导入 CSV/Excel 台账，支持预览和按 external_id/name 去重更新。"""
    filename = file.filename or ""
    lowered = filename.lower()
    if not any(lowered.endswith(ext) for ext in ALLOWED_TABLE_EXTENSIONS):
        raise HTTPException(status_code=400, detail="仅支持 CSV 或 Excel (.xlsx) 文件")

    content = await file.read()
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
    return JurisdictionService.import_tabular_assets(db, rows, source=source, dry_run=dry_run)


@router.get("/assets", response_model=List[JurisdictionAssetResponse])
async def list_assets(
    asset_type: Optional[str] = None,
    source: Optional[str] = None,
    status: Optional[str] = "active",
    skip: int = 0,
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db),
) -> List[JurisdictionAsset]:
    """查询辖区基础要素，支持按类型、来源和状态筛选。"""
    return JurisdictionService.list_assets(
        db=db,
        asset_type=asset_type,
        source=source,
        status=status,
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
    try:
        return JurisdictionService.update_asset(db, asset_id, payload.dict(exclude_unset=True))
    except ValueError as exc:
        if str(exc) == "asset_not_found":
            raise HTTPException(status_code=404, detail="辖区要素不存在") from exc
        raise


@router.delete("/assets/{asset_id:int}", response_model=JurisdictionAssetResponse)
async def deactivate_asset(
    asset_id: int,
    db: Session = Depends(get_db),
) -> JurisdictionAsset:
    """软停用辖区要素，保留历史导入和研判依据。"""
    try:
        return JurisdictionService.deactivate_asset(db, asset_id)
    except ValueError as exc:
        if str(exc) == "asset_not_found":
            raise HTTPException(status_code=404, detail="辖区要素不存在") from exc
        raise


@router.get("/assets/summary")
async def get_assets_summary(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """获取辖区风险底座完整度概览。"""
    return JurisdictionService.summarize_assets(db)


@router.get("/data-quality")
async def get_data_quality(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """审计业务资产完整度、坐标缺失、重复点、校验状态和公共地图参考缺口。"""
    return JurisdictionService.audit_data_quality(db)


@router.get("/assets/{asset_id:int}/risk-profile")
async def get_asset_risk_profile(
    asset_id: int,
    radius_km: float = Query(1.0, ge=0.1, le=10),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """生成点位风险画像，支撑阶段 3 风险画像研判。"""
    try:
        return JurisdictionService.build_asset_risk_profile(db, asset_id, radius_km=radius_km)
    except ValueError as exc:
        if str(exc) == "asset_not_found":
            raise HTTPException(status_code=404, detail="辖区要素不存在") from exc
        raise


@router.get("/cases/{case_id:int}/risk-context")
async def get_case_risk_context(
    case_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """基于地图参考和油区业务资产为案件生成道路、村屯、目标和防控条件画像。"""
    try:
        return JurisdictionService.build_case_risk_context(db, case_id)
    except ValueError as exc:
        if str(exc) == "case_not_found":
            raise HTTPException(status_code=404, detail="案件不存在") from exc
        raise


@router.get("/cases/{case_id:int}/experience-card")
async def get_case_experience_card(
    case_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """把已破案件转成可复用经验卡，支撑阶段 2 经验沉淀。"""
    try:
        return JurisdictionService.build_case_experience_card(db, case_id)
    except ValueError as exc:
        if str(exc) == "case_not_found":
            raise HTTPException(status_code=404, detail="案件不存在") from exc
        raise


@router.get("/similar-targets")
async def get_similar_targets(
    case_id: int,
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """用已破案件的空间条件检索辖区内相似生产目标。"""
    try:
        return JurisdictionService.find_similar_targets(db, case_id=case_id, limit=limit)
    except ValueError as exc:
        if str(exc) == "case_not_found":
            raise HTTPException(status_code=404, detail="案件不存在") from exc
        raise


@router.post("/patrol-plan")
async def create_patrol_plan(
    payload: PatrolPlanRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """根据案件经验卡和相似风险点生成控点、控线、控时布防建议。"""
    try:
        return JurisdictionService.build_patrol_plan(
            db,
            case_id=payload.case_id,
            asset_ids=payload.asset_ids,
            limit=payload.limit,
        )
    except ValueError as exc:
        if str(exc) == "case_not_found":
            raise HTTPException(status_code=404, detail="案件不存在") from exc
        raise


@router.post("/patrol-plan/materialize")
async def materialize_patrol_plan(
    payload: PatrolPlanMaterializeRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """把预防工作台的布防建议落成巡逻计划，进入巡逻执行模块。"""
    try:
        return JurisdictionService.materialize_patrol_plan(
            db,
            case_id=payload.case_id,
            asset_ids=payload.asset_ids,
            limit=payload.limit,
            officer_count=payload.officer_count,
            officer_names=payload.officer_names,
            created_by=payload.created_by,
        )
    except ValueError as exc:
        if str(exc) == "case_not_found":
            raise HTTPException(status_code=404, detail="案件不存在") from exc
        raise


@router.get("/roundtable-briefing")
async def get_roundtable_briefing(
    case_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """生成圆桌会议研判简报和任务清单，支撑阶段 5 决策闭环。"""
    try:
        return JurisdictionService.build_roundtable_briefing(db, case_id)
    except ValueError as exc:
        if str(exc) == "case_not_found":
            raise HTTPException(status_code=404, detail="案件不存在") from exc
        raise


@router.get("/prevention-workbench")
async def get_prevention_workbench(
    case_id: Optional[int] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """聚合经验卡、相似风险点、布防、会议和反馈，形成完整预防工作台。"""
    try:
        return JurisdictionService.build_prevention_workbench(db, case_id=case_id)
    except ValueError as exc:
        if str(exc) == "case_not_found":
            raise HTTPException(status_code=404, detail="案件不存在") from exc
        raise


@router.post("/feedback", response_model=JurisdictionFeedbackResponse)
async def create_feedback(
    payload: JurisdictionFeedbackCreate,
    db: Session = Depends(get_db),
) -> JurisdictionFeedback:
    """记录布防/巡逻/会议任务反馈，支撑阶段 6 效果评估。"""
    return JurisdictionService.record_feedback(db, payload.dict())


@router.get("/effectiveness")
async def get_effectiveness(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """汇总反馈采纳率和有效性评分，形成持续修正依据。"""
    return JurisdictionService.summarize_effectiveness(db)


def _parse_asset_table(filename: str, content: bytes) -> List[Dict[str, Any]]:
    lowered = filename.lower()
    if lowered.endswith(".csv"):
        text = content.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))

    workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    worksheet = workbook.active
    rows = list(worksheet.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(value).strip() if value is not None else "" for value in rows[0]]
    return [
        {
            headers[index]: value
            for index, value in enumerate(row)
            if index < len(headers) and headers[index]
        }
        for row in rows[1:]
    ]
